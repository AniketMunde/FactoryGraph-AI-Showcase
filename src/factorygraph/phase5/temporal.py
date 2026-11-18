"""Genuine historical forecasts and threshold-independent matured features."""

import json
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

from factorygraph.io import sha256, write_json
from factorygraph.phase3.adapter import REVISION, ChronosAdapter
from factorygraph.phase3.config import Phase3Config
from factorygraph.phase3.sequences import classical_forecasts, context_window, sequence_map
from factorygraph.phase3.study import forecast_table, resources, windows_for
from factorygraph.phase5.common import (
    KEYS,
    POLICIES,
    splits,
    verify_prior,
    verify_registration,
)

LOGGER = logging.getLogger(__name__)


def adapter_config(config):
    return Phase3Config(
        run_dir=config.run_dir, seed=config.seed, batch_origins=config.batch_origins
    )


def sequences(config):
    return sequence_map(
        pd.read_csv("data/raw/azure/PdM_telemetry.csv"), adapter_config(config).channels
    )


def origins_for(sequences_, start, end, length=168):
    rows = []
    excluded = 0
    for machine, sequence in sequences_.items():
        for issue in pd.date_range(start.floor("D"), end.floor("D"), freq="D"):
            try:
                context_window(machine, sequence, issue, length)
            except ValueError:
                excluded += 1
                continue
            rows.append({"machineID": machine, "issue_time": issue})
    return pd.DataFrame(rows), excluded


def register(config):
    verify_prior()
    config.run_dir.mkdir(parents=True, exist_ok=True)
    if (config.run_dir / "registration.json").exists():
        raise ValueError("Registration already exists")
    frames = splits()
    keys = pd.concat([f[KEYS] for f in frames.values()], ignore_index=True)
    origins, missing = origins_for(sequences(config), keys.datetime.min(), keys.datetime.max())
    origins.to_parquet(config.run_dir / "origins.parquet", index=False)
    for name, frame in frames.items():
        frame[KEYS].to_parquet(config.run_dir / f"keys_{name}.parquet", index=False)
    record = {
        "config": config.model_dump(mode="json"),
        "policies_sha256": {p: sha256(Path(p)) for p in POLICIES},
        "membership_sha256": {p.name: sha256(p) for p in config.run_dir.glob("*.parquet")},
        "historical_origins": len(origins),
        "incomplete_context_origins": missing,
        "origin_eligibility": "Historical context only; no future targets or labels inspected",
        "checkpoint_revision": REVISION,
        "split_rows": {n: len(f) for n, f in frames.items()},
        "test_previously_observed": True,
    }
    write_json(config.run_dir / "registration.json", record)
    return record


def cheap_width(values):
    past = np.lib.stride_tricks.sliding_window_view(values, 24, axis=-1)[:, :-1, :].mean(axis=-1)
    errors = np.abs(values[:, 24:] - past)
    return 2 * np.quantile(errors, 0.8, axis=-1)


def predict_origins(adapter, origins, seq, config, destination):
    if destination.exists():
        raise ValueError("Forecast output exists; no overwrite")
    destination.mkdir(parents=True)
    timings = []
    start = time.perf_counter()
    for offset in range(0, len(origins), config.batch_origins):
        resources()
        if time.perf_counter() - start > config.max_forecast_seconds:
            raise RuntimeError("Forecast runtime budget exceeded; partial evidence retained")
        tick = time.perf_counter()
        windows = windows_for(
            origins.iloc[offset : offset + config.batch_origins], seq, adapter_config(config)
        )
        context_seconds = time.perf_counter() - tick
        q, timing = adapter.predict(windows)
        tick = time.perf_counter()
        baselines = [classical_forecasts(w.values, 24) for w in windows]
        widths = [cheap_width(w.values) for w in windows]
        cheap_seconds = time.perf_counter() - tick
        table = forecast_table(windows, q, 24, baselines)
        table["cheap_interval_width"] = np.concatenate([np.repeat(w, 24) for w in widths])
        table.to_parquet(destination / f"batch_{offset:06d}.parquet", index=False)
        timings.append(
            {**timing, "context_seconds": context_seconds, "cheap_seconds": cheap_seconds}
        )
        if offset % (config.batch_origins * 100) == 0:
            LOGGER.info(
                "Historical forecast origins %d/%d",
                min(offset + len(windows), len(origins)),
                len(origins),
            )
    write_json(
        destination / "manifest.json",
        {
            "frozen_before_residual_matching": True,
            "files": {p.name: sha256(p) for p in sorted(destination.glob("*.parquet"))},
        },
    )
    return {
        "origins": len(origins),
        "wall_seconds": time.perf_counter() - start,
        **{k: sum(t[k] for t in timings) for k in timings[0]},
        "sdk_batch_ms_p50": float(np.median([t["sdk_inference_seconds"] for t in timings]) * 1000),
        "sdk_batch_ms_p95": float(
            np.quantile([t["sdk_inference_seconds"] for t in timings], 0.95) * 1000
        ),
        "memory": adapter.memory(),
    }


def pilot(config):
    record = verify_registration(config)
    if (config.run_dir / "admission.json").exists():
        raise ValueError("Pilot exists")
    origins = pd.read_parquet(config.run_dir / "origins.parquet")
    origins = origins.loc[origins.machineID.isin([1, 17, 42, 73, 100])].groupby("machineID").head(4)
    seq = sequences(config)
    adapter = ChronosAdapter(adapter_config(config))
    load = adapter.load()
    windows = windows_for(origins.head(2), seq, adapter_config(config))
    first, _ = adapter.predict(windows)
    repeat, _ = adapter.predict(windows)
    if not np.allclose(first, repeat, atol=1e-5, rtol=1e-5):
        raise ValueError("Genuine inference not repeatable")
    timing = predict_origins(adapter, origins, seq, config, config.run_dir / "pilot_forecasts")
    projected = timing["wall_seconds"] / len(origins) * record["historical_origins"] * 2 + 300
    output = {
        "status": "admitted" if projected <= config.max_forecast_seconds else "not_admitted",
        "projected_seconds_with_margin": projected,
        "load": load,
        "timing": timing,
        "repeat_max_difference": float(np.max(np.abs(first - repeat))),
        "selected_machines": [1, 17, 42, 73, 100],
        "selected_origins": len(origins),
    }
    write_json(config.run_dir / "admission.json", output)
    return output


def forecast(config):
    verify_registration(config)
    if json.loads((config.run_dir / "admission.json").read_text())["status"] != "admitted":
        raise ValueError("Resource pilot did not admit full inference")
    adapter = ChronosAdapter(adapter_config(config))
    load = adapter.load()
    timing = predict_origins(
        adapter,
        pd.read_parquet(config.run_dir / "origins.parquet"),
        sequences(config),
        config,
        config.run_dir / "forecasts",
    )
    output = {"status": "completed", "load": load, "timing": timing}
    write_json(config.run_dir / "forecast_runtime.json", output)
    return output


def read_forecasts(directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    for name, digest in manifest["files"].items():
        path = directory / name
        if sha256(path) != digest:
            raise ValueError("Frozen forecast changed")
        yield pd.read_parquet(path)


def machine_features(snapshots, forecasts, sequence, prefix, config):
    """One machine only; actual observations are matched only when matured before last snapshot."""
    if snapshots.duplicated(KEYS).any():
        raise ValueError("Duplicate snapshot keys")
    if forecasts.duplicated(["issue_time", "channel", "lead"]).any():
        raise ValueError("Duplicate forecasts")
    if not (forecasts.source_observation_time < forecasts.issue_time).all():
        raise ValueError("Future context")
    if not (forecasts.target_time >= forecasts.issue_time).all():
        raise ValueError("Target precedes issue")
    result = snapshots[KEYS].copy().set_index("datetime")
    features = {}
    channels = adapter_config(config).channels
    by_issue = []
    point = "chronos" if prefix == "c" else "rolling_mean"
    for issue, group in forecasts.groupby("issue_time", sort=True):
        row = {"issue": issue, "source": group.source_observation_time.max()}
        for channel, g in group.groupby("channel", sort=False):
            g = g.sort_values("lead")
            p = g[point].to_numpy()
            values = {
                "forecast_mean": p.mean(),
                "forecast_trend": (p[-1] - p[0]) / 23,
                "forecast_std": p.std(),
                "forecast_interval_width": (g.q90 - g.q10).mean()
                if prefix == "c"
                else g.cheap_interval_width.mean(),
                "forecast_relative_change": (p[-1] - p[0]) / max(abs(p[0]), 1e-6),
            }
            row.update({f"p5_{prefix}_{channel}_{k}": float(v) for k, v in values.items()})
        by_issue.append(row)
    issued = (
        pd.DataFrame(by_issue).set_index("issue")
        if by_issue
        else pd.DataFrame(columns=["source"], index=pd.DatetimeIndex([], tz="UTC", name="issue"))
    )
    if len(issued):
        position = issued.index.searchsorted(result.index, side="right") - 1
        valid = position >= 0
        chosen = issued.iloc[np.maximum(position, 0)].copy()
        chosen.index = result.index
        for c in chosen:
            chosen.loc[~valid, c] = pd.NaT if c == "source" else np.nan
        for c in chosen:
            if c.startswith("p5_"):
                features[c] = chosen[c]
        issue_times = pd.Series(pd.NaT, index=result.index, dtype="datetime64[ns, UTC]")
        issue_times.loc[valid] = issued.index[position[valid]]
        source_times = pd.to_datetime(chosen.source, utc=True)
    else:
        issue_times = pd.Series(pd.NaT, index=result.index, dtype="datetime64[ns, UTC]")
        source_times = issue_times.copy()
        for channel in channels:
            for suffix in [
                "forecast_mean",
                "forecast_trend",
                "forecast_std",
                "forecast_interval_width",
                "forecast_relative_change",
            ]:
                features[f"p5_{prefix}_{channel}_{suffix}"] = np.full(len(result), np.nan)
    max_snapshot = result.index.max()
    residual_sources = []
    for channel in channels:
        f = forecasts.loc[
            (forecasts.channel == channel) & (forecasts.target_time < max_snapshot)
        ].copy()
        f = f.sort_values("issue_time").drop_duplicates("target_time", keep="last")
        realized = sequence[channel].reindex(pd.DatetimeIndex(f.target_time)).to_numpy()
        score = np.abs(realized - f[point].to_numpy()) / f.context_robust_scale.to_numpy()
        index = pd.date_range(
            result.index.min().floor("D") - pd.Timedelta(days=1), max_snapshot, freq="h"
        )
        values = pd.Series(score, index=pd.DatetimeIndex(f.target_time)).reindex(index)
        shifted = values.shift(1)
        stats = {
            "residual_latest": shifted,
            "residual_mean_24h": shifted.rolling(24, min_periods=1).mean(),
            "residual_max_24h": shifted.rolling(24, min_periods=1).max(),
            "residual_valid_count_24h": shifted.rolling(24, min_periods=0).count(),
        }
        for suffix, s in stats.items():
            features[f"p5_{prefix}_{channel}_{suffix}"] = s.reindex(result.index)
        source = (
            pd.Series(index, index=index)
            .where(values.notna())
            .ffill()
            .shift(1)
            .reindex(result.index)
        )
        residual_sources.append(source)
    for name, values in features.items():
        result[name] = values
    latest = result[[f"p5_{prefix}_{c}_residual_latest" for c in channels]]
    result[f"p5_{prefix}_residual_multivariate_mean_latest"] = latest.mean(axis=1)
    result[f"p5_{prefix}_residual_multivariate_max_latest"] = latest.max(axis=1)
    result[f"p5_{prefix}_forecast_age_hours"] = (
        result.index.to_series() - issue_times
    ).dt.total_seconds() / 3600
    result[f"p5_{prefix}_forecast_available"] = issue_times.notna().astype("int8")
    result["forecast_issue_timestamp"] = issue_times
    result["latest_residual_observation_timestamp"] = pd.concat(residual_sources, axis=1).max(
        axis=1
    )
    result["latest_source_observation_timestamp"] = pd.concat(
        [source_times, result.latest_residual_observation_timestamp], axis=1
    ).max(axis=1)
    if (result.latest_source_observation_timestamp >= result.index.to_series()).any():
        raise ValueError("Future feature source")
    if (result.forecast_issue_timestamp > result.index.to_series()).any():
        raise ValueError("Future forecast issue")
    result["temporal_policy_sha256"] = sha256(Path(POLICIES[1]))
    result["model_id"] = (
        "amazon/chronos-2" if prefix == "c" else "last24h-mean-causal-empirical-width"
    )
    result["checkpoint_revision"] = REVISION if prefix == "c" else "not_applicable"
    return result.reset_index()


def export(config):
    verify_registration(config)
    if (config.run_dir / "temporal_manifest.json").exists():
        raise ValueError("Temporal export exists")
    snapshot_frames = splits()
    snapshots = pd.concat([f[KEYS] for f in snapshot_frames.values()], ignore_index=True)
    seq = sequences(config)
    parts = {"b": [], "c": []}
    pending = []
    current = None
    timings = {"b": 0.0, "c": 0.0}
    start = time.perf_counter()

    def finish(machine, frames):
        if machine is None:
            return
        f = pd.concat(frames, ignore_index=True)
        keys = snapshots.loc[snapshots.machineID == machine]
        for prefix in parts:
            tick = time.perf_counter()
            parts[prefix].append(machine_features(keys, f, seq[machine], prefix, config))
            timings[prefix] += time.perf_counter() - tick

    for batch in read_forecasts(config.run_dir / "forecasts"):
        for machine, frame in batch.groupby("machineID", sort=False):
            if current is not None and machine != current:
                finish(current, pending)
                pending = []
            current = machine
            pending.append(frame)
    finish(current, pending)
    output = {
        "status": "completed",
        "groups": {},
        "seconds": None,
        "group_compute_seconds": timings,
        "policy_sha256": sha256(Path(POLICIES[1])),
        "thresholds": "none",
    }
    for prefix, frames in parts.items():
        all_features = pd.concat(frames, ignore_index=True)
        columns = [c for c in all_features if c.startswith(f"p5_{prefix}_")]
        if len(columns) != 40:
            raise ValueError("Registered temporal feature schema mismatch")
        records = {}
        for split, keys in snapshot_frames.items():
            selected = keys[KEYS].merge(all_features, on=KEYS, how="left", validate="one_to_one")
            path = config.run_dir / f"temporal_{prefix}_{split}.parquet"
            selected.to_parquet(path, index=False)
            records[split] = {
                "rows": len(selected),
                "path": str(path),
                "sha256": sha256(path),
                "unavailable_forecasts": int(
                    (selected[f"p5_{prefix}_forecast_available"] == 0).sum()
                ),
                "missing_numeric": {c: int(selected[c].isna().sum()) for c in columns},
            }
        output["groups"][prefix] = {"columns": columns, "splits": records}
    output["seconds"] = time.perf_counter() - start
    write_json(config.run_dir / "temporal_manifest.json", output)
    return output
