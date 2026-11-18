"""Independent three-hour features; never joins labels or trains a fused model."""

import json

import numpy as np
import pandas as pd

from factorygraph.io import sha256, write_json
from factorygraph.phase3.adapter import REVISION
from factorygraph.phase3.config import Phase3Config


def historical_summary(
    scores: pd.DataFrame, snapshot: pd.Timestamp, threshold: float
) -> dict[str, float]:
    historical = scores.loc[
        (scores.observation_time < snapshot) & (scores.source_max < snapshot)
    ].sort_values("observation_time")
    completed = historical.loc[historical.observation_time >= snapshot - pd.Timedelta(hours=24)]
    values = completed.score.dropna().to_numpy()
    run = 0
    # Persistence breaks at missing hours and missing/normal observations.
    last_time = snapshot
    for row in historical.itertuples(index=False):
        if row.observation_time < snapshot - pd.Timedelta(hours=24):
            continue
        if row.observation_time - last_time != pd.Timedelta(hours=1):
            run = 0
        run = run + 1 if np.isfinite(row.score) and row.score > threshold else 0
        last_time = row.observation_time
    return {
        "latest": float(historical.score.iloc[-1]) if len(historical) else np.nan,
        "mean_24h": float(values.mean()) if len(values) else np.nan,
        "max_24h": float(values.max()) if len(values) else np.nan,
        "anomaly_count_24h": float((values > threshold).sum()) if len(values) else np.nan,
        "anomaly_fraction_24h": float((values > threshold).mean()) if len(values) else np.nan,
        "persistence_hours": float(run) if len(values) else np.nan,
        "valid_observations_24h": float(len(values)),
    }


def build_export(
    snapshots: pd.DataFrame,
    forecasts: pd.DataFrame,
    scores: pd.DataFrame,
    thresholds: dict,
    config: Phase3Config,
) -> pd.DataFrame:
    if snapshots.duplicated(["machineID", "datetime"]).any():
        raise ValueError("Duplicate Phase 1 snapshot keys")
    cutoff = pd.Timestamp(thresholds["fit_end_exclusive"])
    if (snapshots.datetime < cutoff).any() or pd.Timestamp(thresholds["source_max"]) >= cutoff:
        raise ValueError("Validation-derived thresholds are not eligible for these snapshots")
    # Compute hourly historical summaries once; reuse at exactly matching 3-hour snapshots.
    summary = {}
    for (machine, method, channel), group in scores.groupby(["machineID", "method", "channel"]):
        group = group.sort_values("observation_time").set_index("observation_time")
        threshold = thresholds["thresholds"][f"{method}:{channel}"]
        index = pd.date_range(
            group.index.min(), group.index.max() + pd.Timedelta(hours=1), freq="h"
        )
        regular = group.reindex(index)
        values = regular.score
        shifted = values.shift(1)
        flags = (values > threshold).where(values.notna())
        runs = []
        run = 0
        for value in flags:
            run = run + 1 if pd.notna(value) and value else 0
            runs.append(run)
        table = pd.DataFrame(
            {
                "latest": shifted,
                "mean_24h": shifted.rolling(24, min_periods=1).mean(),
                "max_24h": shifted.rolling(24, min_periods=1).max(),
                "anomaly_count_24h": flags.shift(1).rolling(24, min_periods=1).sum(),
                "anomaly_fraction_24h": flags.shift(1).rolling(24, min_periods=1).mean(),
                "valid_observations_24h": shifted.rolling(24, min_periods=1).count(),
                "persistence_hours": pd.Series(runs, index=index).shift(1),
            }
        )
        table["source_max"] = pd.Series(index, index=index).where(values.notna()).ffill().shift(1)
        summary[(machine, method, channel)] = table
    rows = []
    forecast_features = {}
    for (machine, issue), issued in forecasts.groupby(["machineID", "issue_time"], sort=False):
        values = {
            "forecast_issue_timestamp": issue,
            "latest_source_observation_timestamp": issued.source_observation_time.max(),
        }
        for channel, group in issued.groupby("channel", sort=False):
            group = group.sort_values("lead")
            point = group.chronos.to_numpy()
            values[f"p3_{channel}_forecast_trend"] = float(
                (point[-1] - point[0]) / max(1, len(point) - 1)
            )
            values[f"p3_{channel}_forecast_std"] = float(point.std())
            values[f"p3_{channel}_forecast_interval_width"] = float((group.q90 - group.q10).mean())
            values[f"p3_{channel}_forecast_relative_change"] = float(
                (point[-1] - point[0]) / max(abs(point[0]), 1e-6)
            )
        forecast_features[(machine, issue)] = values
    for machine, machine_snapshots in snapshots.groupby("machineID", sort=True):
        f = forecasts.loc[forecasts.machineID == machine]
        issues = pd.DatetimeIndex(f.issue_time.unique()).sort_values()
        for snapshot in machine_snapshots.datetime:
            record = {
                "machineID": machine,
                "datetime": snapshot,
                "latest_source_observation_timestamp": pd.NaT,
                "latest_residual_observation_timestamp": pd.NaT,
                "forecast_issue_timestamp": pd.NaT,
            }
            eligible = issues[issues <= snapshot]
            if len(eligible):
                issue = eligible[-1]
                values = forecast_features[(machine, issue)]
                if values["latest_source_observation_timestamp"] >= snapshot:
                    raise ValueError("Export attempted to use unavailable forecast context")
                record.update(values)
                record["forecast_age_hours"] = (snapshot - issue).total_seconds() / 3600
            source_times = []
            residual_times = []
            for method in ["robust_mad", "forecast_residual"]:
                for channel in config.channels:
                    table = summary.get((machine, method, channel))
                    if table is None or snapshot not in table.index:
                        continue
                    row = table.loc[snapshot]
                    for name in [
                        "latest",
                        "mean_24h",
                        "max_24h",
                        "anomaly_count_24h",
                        "anomaly_fraction_24h",
                        "valid_observations_24h",
                        "persistence_hours",
                    ]:
                        record[f"p3_{channel}_{method}_{name}"] = float(row[name])
                    if pd.notna(row.source_max):
                        source_times.append(row.source_max)
                        if method == "forecast_residual":
                            residual_times.append(row.source_max)
            if source_times:
                source_times += [record["latest_source_observation_timestamp"]]
                record["latest_source_observation_timestamp"] = max(
                    t for t in source_times if pd.notna(t)
                )
            if residual_times:
                record["latest_residual_observation_timestamp"] = max(residual_times)
            for method in ["robust_mad", "forecast_residual"]:
                latest = np.array(
                    [
                        record.get(f"p3_{channel}_{method}_latest", np.nan)
                        for channel in config.channels
                    ],
                    dtype=float,
                )
                valid = latest[np.isfinite(latest)]
                record[f"p3_{method}_multivariate_mean_latest"] = (
                    float(valid.mean()) if len(valid) else np.nan
                )
                record[f"p3_{method}_multivariate_max_latest"] = (
                    float(valid.max()) if len(valid) else np.nan
                )
            rows.append(record)
    result = pd.DataFrame(rows)
    for column in ["latest_source_observation_timestamp", "latest_residual_observation_timestamp"]:
        result[column] = pd.to_datetime(result[column], utc=True)
        if (result[column].notna() & (result[column] >= result.datetime)).any():
            raise ValueError("Export source availability violated")
    result["model_id"] = "amazon/chronos-2"
    result["checkpoint_revision"] = REVISION
    import hashlib

    result["feature_config_sha256"] = hashlib.sha256(
        json.dumps(config.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()
    return result


def save_export(frame: pd.DataFrame, config: Phase3Config) -> dict:
    path = config.run_dir / "features_test.parquet"
    frame.to_parquet(path, index=False)
    metadata = [
        "machineID",
        "datetime",
        "latest_source_observation_timestamp",
        "latest_residual_observation_timestamp",
        "forecast_issue_timestamp",
        "model_id",
        "checkpoint_revision",
        "feature_config_sha256",
    ]
    feature_names = [name for name in frame if name not in metadata]
    manifest = {
        "rows": len(frame),
        "sha256": sha256(path),
        "keys": ["machineID", "datetime"],
        "feature_columns": feature_names,
        "metadata_columns": metadata,
        "config": config.model_dump(mode="json"),
        "availability": "Sources strictly before snapshot; forecast issue at or before snapshot",
        "eligible_period": "Test only; validation thresholds available by test start",
        "cadence_note": "Three-hour snapshots; daily forecasts; explicit forecast age",
        "integration": "Keyed numeric columns for future adapters; no fusion trained",
    }
    write_json(config.run_dir / "feature_manifest.json", manifest)
    return manifest
