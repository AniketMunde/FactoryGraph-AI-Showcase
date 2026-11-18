"""Causal features are independent of labels and never inspect failure records."""

import numpy as np
import pandas as pd

from factorygraph.config import FeatureConfig, SplitConfig
from factorygraph.data import COMPONENTS, ERRORS, SENSORS

KEYS = ["machineID", "datetime"]
LABEL_COLUMNS = ["label", "label_end", "next_failure"]


def nanos(values: pd.Series | pd.DatetimeIndex) -> np.ndarray:
    return pd.DatetimeIndex(values).as_unit("ns").asi8


def feature_columns(config: FeatureConfig) -> list[str]:
    return [
        "age",
        "model_code",
        *[
            f"{sensor}_{stat}_{w}h"
            for w in config.windows_hours
            for sensor in SENSORS
            for stat in ["mean", "std", "count"]
        ],
        *[f"{error}_count_{w}h" for w in config.windows_hours for error in ERRORS],
        *[f"{comp}_hours_since_maint" for comp in COMPONENTS],
    ]


def build_features(tables: dict[str, pd.DataFrame], config: FeatureConfig) -> pd.DataFrame:
    """At t, use [t-window,t) and maintenance strictly before t.

    Source telemetry must be unique per machine/time. Time windows are durations,
    never row counts. Missing maintenance history remains NaN, with no backfill.
    """
    metadata = tables["machines"].set_index("machineID")
    frames = []
    for machine, telemetry in tables["telemetry"].groupby("machineID", sort=True):
        history = telemetry.sort_values("datetime").set_index("datetime")[SENSORS]
        hour_ns = 3_600_000_000_000
        aligned = nanos(history.index) % (config.snapshot_hours * hour_ns) == 0
        warm = history.index >= history.index.min() + pd.Timedelta(hours=max(config.windows_hours))
        index = history.index[aligned & warm]
        if index.empty:
            continue
        frame = pd.DataFrame(index=index)
        frame["machineID"] = machine
        frame["age"] = metadata.loc[machine, "age"]
        frame["model_code"] = int(metadata.loc[machine, "model"].removeprefix("model"))
        t = nanos(index)
        for w in config.windows_hours:
            window = history.rolling(f"{w}h", closed="left", min_periods=1)
            aggregates = {"mean": window.mean(), "std": window.std(ddof=0), "count": window.count()}
            for sensor in SENSORS:
                for stat, values in aggregates.items():
                    selected = values.loc[index, sensor]
                    if stat == "count":
                        selected = selected.fillna(0)
                    frame[f"{sensor}_{stat}_{w}h"] = selected.to_numpy()
            for error in ERRORS:
                records = tables["errors"]
                events = nanos(
                    records.loc[
                        (records.machineID == machine) & (records.errorID == error), "datetime"
                    ].sort_values()
                )
                frame[f"{error}_count_{w}h"] = np.searchsorted(
                    events, t, side="left"
                ) - np.searchsorted(events, t - w * hour_ns, side="left")
        for comp in COMPONENTS:
            records = tables["maint"]
            events = nanos(
                records.loc[
                    (records.machineID == machine) & (records.comp == comp), "datetime"
                ].sort_values()
            )
            positions = np.searchsorted(events, t, side="left") - 1
            recency = np.full(len(t), np.nan)
            valid = positions >= 0
            recency[valid] = (t[valid] - events[positions[valid]]) / hour_ns
            frame[f"{comp}_hours_since_maint"] = recency
        frames.append(frame.reset_index())
    if not frames:
        raise ValueError("No feature snapshots: history shorter than feature warm-up")
    return pd.concat(frames, ignore_index=True)[KEYS + feature_columns(config)]


def attach_labels(
    features: pd.DataFrame, tables: dict[str, pd.DataFrame], horizon_hours: int
) -> pd.DataFrame:
    """Binary any-component failure in (t,t+H]; censor incomplete follow-up.

    Exclude snapshots exactly at a failure (not a pre-failure prediction).
    Completeness of failure logging through each machine's last telemetry is assumed.
    """
    frames = []
    for machine, frame in features.groupby("machineID", sort=True):
        frame = frame.copy()
        failures = tables["failures"]
        events = nanos(failures.loc[failures.machineID == machine, "datetime"].sort_values())
        t = nanos(frame.datetime)
        positions = np.searchsorted(events, t, side="right")
        next_event = np.full(len(frame), np.iinfo(np.int64).max, dtype="int64")
        valid = positions < len(events)
        next_event[valid] = events[positions[valid]]
        frame["label_end"] = frame.datetime + pd.Timedelta(hours=horizon_hours)
        frame["label"] = (next_event <= nanos(frame.label_end)).astype("int8")
        frame["next_failure"] = pd.to_datetime(np.where(valid, next_event, pd.NaT.value), utc=True)
        last_observed = (
            tables["telemetry"].loc[tables["telemetry"].machineID == machine, "datetime"].max()
        )
        eligible = (frame.label_end <= last_observed) & ~np.isin(t, events)
        frames.append(frame.loc[eligible])
    return pd.concat(frames, ignore_index=True)


def chronological_split(frame: pd.DataFrame, config: SplitConfig) -> dict[str, pd.DataFrame]:
    """Purge every label interval reaching a later period, including equality."""
    boundaries = [pd.Timestamp(v) for v in config.model_dump().values()]
    splits = {}
    for name, start, end in zip(
        ["train", "calibration", "validation", "test"], boundaries, boundaries[1:], strict=False
    ):
        mask = (frame.datetime >= start) & (frame.datetime < end) & (frame.label_end < end)
        splits[name] = frame.loc[mask].sort_values(KEYS).reset_index(drop=True)
    return splits
