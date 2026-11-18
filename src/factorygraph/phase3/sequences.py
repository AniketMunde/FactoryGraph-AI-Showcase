"""Machine-specific regular sequences; no implicit interpolation or future context."""

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Window:
    machine: int
    issue: pd.Timestamp
    source_max: pd.Timestamp
    channels: list[str]
    values: np.ndarray  # [channel, context]; no actual future observations


def validate_telemetry(frame: pd.DataFrame, channels: list[str]) -> pd.DataFrame:
    required = ["machineID", "datetime", *channels]
    if not set(required).issubset(frame.columns):
        raise ValueError("Missing telemetry columns")
    data = frame[required].copy()
    ids = pd.to_numeric(data.machineID, errors="raise")
    if not np.isfinite(ids).all() or (ids <= 0).any() or (ids % 1 != 0).any():
        raise ValueError("Machine IDs must be positive integers without aliasing")
    data["machineID"] = ids.astype("int64")
    if pd.api.types.is_numeric_dtype(data.datetime):
        raise ValueError("Numeric timestamps are not supported")
    data["datetime"] = pd.to_datetime(data.datetime, utc=True, format="mixed", errors="raise")
    if data[["machineID", "datetime"]].isna().any().any():
        raise ValueError("Missing temporal identity")
    if data.duplicated(["machineID", "datetime"]).any():
        raise ValueError("Duplicate machine timestamps")
    if np.isinf(data[channels].to_numpy(dtype=float)).any():
        raise ValueError("Infinite sensor values")
    return data.sort_values(["machineID", "datetime"]).reset_index(drop=True)


def sequence_map(frame: pd.DataFrame, channels: list[str]) -> dict[int, pd.DataFrame]:
    data = validate_telemetry(frame, channels)
    return {
        int(machine): group.set_index("datetime")[channels]
        for machine, group in data.groupby("machineID")
    }


def context_window(
    machine: int, sequence: pd.DataFrame, issue: pd.Timestamp, length: int
) -> Window:
    if issue.tzinfo is None:
        raise ValueError("Forecast issue requires a timezone")
    expected = pd.date_range(issue - pd.Timedelta(hours=length), periods=length, freq="h")
    historical = sequence.reindex(expected)
    if not np.isfinite(historical.to_numpy(dtype=float)).all():
        raise ValueError("Incomplete, irregular or missing historical context")
    return Window(
        machine,
        issue,
        expected[-1],
        list(sequence.columns),
        historical.to_numpy(dtype=np.float32).T.copy(),
    )


def eligible_origins(
    sequences: dict[int, pd.DataFrame],
    start: pd.Timestamp,
    end: pd.Timestamp,
    context: int,
    horizon: int,
    stride: int,
) -> tuple[pd.DataFrame, dict[str, int]]:
    rows = []
    skipped = {"context": 0, "target": 0}
    for machine, sequence in sequences.items():
        for issue in pd.date_range(start, end, freq=f"{stride}h", inclusive="left"):
            targets = pd.date_range(issue, periods=horizon, freq="h")
            if targets[-1] >= end:
                continue
            try:
                context_window(machine, sequence, issue, context)
            except ValueError:
                skipped["context"] += 1
                continue
            if not np.isfinite(sequence.reindex(targets).to_numpy(dtype=float)).all():
                skipped["target"] += 1
                continue
            rows.append({"machineID": machine, "issue_time": issue})
    return pd.DataFrame(rows, columns=["machineID", "issue_time"]), skipped


def robust_scale(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    median = np.median(values, axis=-1)
    mad = np.median(np.abs(values - median[..., None]), axis=-1) * 1.4826
    return median, np.maximum(mad, np.maximum(np.abs(median) * 1e-6, 1e-6))


def classical_forecasts(values: np.ndarray, horizon: int) -> dict[str, np.ndarray]:
    if horizon > 24 or values.shape[-1] < 24:
        raise ValueError("Seasonal comparator requires 24h history and horizon <=24")
    return {
        "persistence": np.repeat(values[..., -1:], horizon, axis=-1),
        "rolling_mean": np.repeat(values[..., -24:].mean(axis=-1, keepdims=True), horizon, axis=-1),
        "seasonal_naive": values[..., -24:][..., :horizon],
    }


def training_scales(sequences: dict[int, pd.DataFrame], end: pd.Timestamp) -> pd.DataFrame:
    rows = []
    for machine, sequence in sequences.items():
        history = sequence.loc[sequence.index < end]
        # Timestamp join, not a 24-row shift across potential gaps.
        previous = history.reindex(history.index - pd.Timedelta(hours=24)).to_numpy()
        scales = np.nanmean(np.abs(history.to_numpy() - previous), axis=0)
        for channel, scale in zip(history.columns, scales, strict=True):
            rows.append(
                {
                    "machineID": machine,
                    "channel": channel,
                    "mase_scale": float(scale) if np.isfinite(scale) and scale > 0 else np.nan,
                }
            )
    return pd.DataFrame(rows)
