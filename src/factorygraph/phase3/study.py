"""Registered rolling-origin study and staged resource admission."""

import json
import logging
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psutil

from factorygraph.io import sha256, write_json
from factorygraph.phase2.context import choose_machines
from factorygraph.phase3.adapter import ChronosAdapter
from factorygraph.phase3.config import Phase3Config
from factorygraph.phase3.integrity import freeze, verify
from factorygraph.phase3.metrics import attach_actuals, summarize
from factorygraph.phase3.sequences import (
    Window,
    classical_forecasts,
    context_window,
    eligible_origins,
    robust_scale,
    sequence_map,
    training_scales,
)

LOGGER = logging.getLogger(__name__)


def protocol(config: Phase3Config) -> Path:
    return (
        Path("docs/PHASE3_METROPT_EXPERIMENT.md")
        if "metropt" in str(config.telemetry_path)
        else (Path("docs/PHASE3_EXPERIMENT.md"))
    )


def resources() -> None:
    import shutil

    if psutil.virtual_memory().available < 3e9 or shutil.disk_usage(".").free < 2e9:
        raise RuntimeError(
            "Registered RAM/disk safety floor reached; population cannot be shortened"
        )


def read_sequences(config: Phase3Config) -> dict[int, pd.DataFrame]:
    return sequence_map(pd.read_csv(config.telemetry_path), config.channels)


def register(config: Phase3Config) -> dict[str, Any]:
    config.run_dir.mkdir(parents=True, exist_ok=True)
    path = config.run_dir / "registration.json"
    if path.exists():
        raise ValueError("Registration exists; choose a fresh Phase 3 run directory")
    freeze(config.run_dir / "protected.json")
    resources()
    sequences = read_sequences(config)
    counts = {}
    for period, start, end in [
        ("validation", config.validation_start, config.test_start),
        ("test", config.test_start, config.test_end),
    ]:
        origins, exclusions = eligible_origins(
            sequences,
            pd.Timestamp(start),
            pd.Timestamp(end),
            config.context_length,
            config.horizon,
            config.origin_stride_hours,
        )
        origins.to_parquet(config.run_dir / f"{period}_origins.parquet", index=False)
        counts[period] = {"origins": len(origins), "exclusions": exclusions}
    scales = training_scales(sequences, pd.Timestamp(config.scale_end))
    scales.to_parquet(config.run_dir / "mase_scales.parquet", index=False)
    membership = {p.name: sha256(p) for p in config.run_dir.glob("*.parquet")}
    record = {
        "config": config.model_dump(mode="json"),
        "populations": counts,
        "telemetry_sha256": sha256(config.telemetry_path),
        "membership_sha256": membership,
        "protocol_sha256": sha256(protocol(config)),
        "registered_before_forecasts": True,
    }
    write_json(path, record)
    return record


def verify_study(config: Phase3Config) -> dict[str, Any]:
    record = json.loads((config.run_dir / "registration.json").read_text())
    verify(config.run_dir / "protected.json")
    if record["config"] != config.model_dump(mode="json"):
        raise ValueError("Configuration differs from preregistration")
    if record["telemetry_sha256"] != sha256(config.telemetry_path):
        raise ValueError("Telemetry changed after registration")
    if record["protocol_sha256"] != sha256(protocol(config)):
        raise ValueError("Registered scientific protocol changed")
    for filename, digest in record["membership_sha256"].items():
        if sha256(config.run_dir / filename) != digest:
            raise ValueError("Origin membership or training scale changed")
    return record


def windows_for(
    origins: pd.DataFrame, sequences: dict[int, pd.DataFrame], config: Phase3Config
) -> list[Window]:
    return [
        context_window(
            int(row.machineID), sequences[int(row.machineID)], row.issue_time, config.context_length
        )
        for row in origins.itertuples(index=False)
    ]


def forecast_table(
    windows: list[Window],
    quantiles: np.ndarray,
    horizon: int,
    comparators: list[dict[str, np.ndarray]] | None = None,
) -> pd.DataFrame:
    frames = []
    for index, (window, q) in enumerate(zip(windows, quantiles, strict=True)):
        channel_count = len(window.channels)
        baseline = (
            comparators[index]
            if comparators is not None
            else classical_forecasts(window.values, horizon)
        )
        _, scale = robust_scale(window.values)
        frame = pd.DataFrame(
            {
                "machineID": window.machine,
                "issue_time": window.issue,
                "source_observation_time": window.source_max,
                "target_time": list(pd.date_range(window.issue, periods=horizon, freq="h"))
                * channel_count,
                "channel": np.repeat(window.channels, horizon),
                "lead": np.tile(np.arange(1, horizon + 1), channel_count),
                "q10": q[:, :, 0].ravel(),
                "q50": q[:, :, 1].ravel(),
                "q90": q[:, :, 2].ravel(),
                "chronos": q[:, :, 1].ravel(),
                "context_robust_scale": np.repeat(scale, horizon),
                **{name: values.ravel() for name, values in baseline.items()},
            }
        )
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def actual_table(sequences: dict[int, pd.DataFrame], forecasts: pd.DataFrame) -> pd.DataFrame:
    start, end = forecasts.target_time.min(), forecasts.target_time.max()
    parts = []
    for machine, sequence in sequences.items():
        part = sequence.loc[(sequence.index >= start) & (sequence.index <= end)].reset_index()
        part["machineID"] = machine
        part = part.melt(id_vars=["machineID", "datetime"], var_name="channel", value_name="actual")
        parts.append(part.rename(columns={"datetime": "target_time"}))
    return pd.concat(parts, ignore_index=True)


def predict_origins(
    adapter: ChronosAdapter,
    origins: pd.DataFrame,
    sequences: dict[int, pd.DataFrame],
    config: Phase3Config,
    destination: Path,
) -> dict[str, Any]:
    if destination.exists():
        raise ValueError("Forecast output exists; refusing to overwrite frozen predictions")
    destination.mkdir(parents=True)
    timings = []
    started = time.perf_counter()
    for offset in range(0, len(origins), config.batch_origins):
        resources()
        if time.perf_counter() - started > config.max_seconds:
            raise RuntimeError("Forecast time budget exceeded; partial batches preserved")
        begin = time.perf_counter()
        windows = windows_for(
            origins.iloc[offset : offset + config.batch_origins], sequences, config
        )
        context_seconds = time.perf_counter() - begin
        q, timing = adapter.predict(windows)
        baseline_start = time.perf_counter()
        comparators = [classical_forecasts(window.values, config.horizon) for window in windows]
        baseline_seconds = time.perf_counter() - baseline_start
        table = forecast_table(windows, q, config.horizon, comparators)
        table.to_parquet(destination / f"batch_{offset:06d}.parquet", index=False)
        timings.append(
            {
                **timing,
                "context_construction_seconds": context_seconds,
                "classical_prediction_seconds": baseline_seconds,
                "batch_pipeline_seconds": time.perf_counter() - begin,
                "origins": len(windows),
            }
        )
        if offset % (config.batch_origins * 50) == 0:
            LOGGER.info(
                "forecast origins=%d/%d", min(offset + len(windows), len(origins)), len(origins)
            )
    write_json(
        destination / "manifest.json",
        {
            "frozen_before_actual_join": True,
            "files": {p.name: sha256(p) for p in sorted(destination.glob("*.parquet"))},
        },
    )
    columns = [
        "preprocessing_seconds",
        "sdk_inference_seconds",
        "neural_forward_seconds",
        "postprocessing_seconds",
        "context_construction_seconds",
        "classical_prediction_seconds",
        "batch_pipeline_seconds",
    ]
    total = {name: sum(row[name] for row in timings) for name in columns}
    total.update(
        origins=len(origins),
        wall_seconds=time.perf_counter() - started,
        batch_pipeline_ms_p50=float(
            np.median([r["batch_pipeline_seconds"] for r in timings]) * 1000
        ),
        batch_pipeline_ms_p95=float(
            np.quantile([r["batch_pipeline_seconds"] for r in timings], 0.95) * 1000
        ),
        memory=adapter.memory(),
    )
    return total


def load_forecasts(path: Path) -> pd.DataFrame:
    manifest = json.loads((path / "manifest.json").read_text())
    frames = []
    for filename, digest in manifest["files"].items():
        if sha256(path / filename) != digest:
            raise ValueError("Frozen forecast changed before evaluation")
        frames.append(pd.read_parquet(path / filename))
    return pd.concat(frames, ignore_index=True)


def smoke(config: Phase3Config) -> dict[str, Any]:
    verify_study(config)
    if (config.run_dir / "smoke.json").exists():
        raise ValueError("Smoke evidence exists")
    sequences = read_sequences(config)
    origins = pd.read_parquet(config.run_dir / "validation_origins.parquet").head(
        config.batch_origins
    )
    windows = windows_for(origins, sequences, config)
    adapter = ChronosAdapter(config)
    load = adapter.load()
    first, _ = adapter.predict(windows)
    repeat, timing = adapter.predict(windows)
    if not np.allclose(first, repeat, atol=1e-5, rtol=1e-5):
        raise RuntimeError("Repeated genuine forecasts are not reproducible within tolerance")
    cpu = ChronosAdapter(config.model_copy(update={"device": "cpu"}))
    cpu_load = cpu.load()
    _, cpu_timing = cpu.predict(windows[:1])
    output = {
        "status": "passed",
        "load": load,
        "timing": timing,
        "memory": adapter.memory(),
        "cpu": {"load": cpu_load, "timing": cpu_timing, "memory": cpu.memory()},
        "repeat_max_absolute_difference": float(np.max(np.abs(first - repeat))),
    }
    write_json(config.run_dir / "smoke.json", output)
    return output


def pilot(config: Phase3Config) -> dict[str, Any]:
    registration = verify_study(config)
    if json.loads((config.run_dir / "smoke.json").read_text())["status"] != "passed":
        raise RuntimeError("Genuine model smoke must pass")
    sequences = read_sequences(config)
    machines = choose_machines(sorted(sequences), min(5, len(sequences)), config.seed)
    origins = pd.read_parquet(config.run_dir / "validation_origins.parquet")
    origins = origins.loc[origins.machineID.isin(machines)].groupby("machineID").head(4)
    origins.to_parquet(config.run_dir / "pilot_origins.parquet", index=False)
    adapter = ChronosAdapter(config)
    load = adapter.load()
    timing = predict_origins(
        adapter, origins, sequences, config, config.run_dir / "pilot_forecasts"
    )
    forecasts = load_forecasts(config.run_dir / "pilot_forecasts")
    paired = attach_actuals(forecasts, actual_table(sequences, forecasts))
    paired.to_parquet(config.run_dir / "pilot_evaluation.parquet", index=False)
    metrics = summarize(paired, pd.read_parquet(config.run_dir / "mase_scales.parquet"))
    count = sum(info["origins"] for info in registration["populations"].values())
    projected = timing["wall_seconds"] / len(origins) * count * 2 + 300
    admission = {
        "status": "admitted" if projected <= config.max_seconds else "not_admitted",
        "projected_full_seconds_including_300s_analysis_margin": projected,
        "full_origins": count,
        "pilot_origins": len(origins),
        "pilot_machines": machines,
        "load": load,
        "timing": timing,
        "validation_pilot_metrics": metrics,
        "registered_before_test_inference": True,
    }
    write_json(config.run_dir / "admission.json", admission)
    return admission


def run(config: Phase3Config) -> dict[str, Any]:
    registration = verify_study(config)
    admission = json.loads((config.run_dir / "admission.json").read_text())
    if admission["status"] != "admitted":
        raise RuntimeError("Full-evaluation resource gate did not admit this population")
    sequences = read_sequences(config)
    adapter = ChronosAdapter(config)
    load = adapter.load()
    result = {
        "status": "full_forecasting_completed",
        "registration": registration,
        "load": load,
        "periods": {},
    }
    for period in ["validation", "test"]:
        origins = pd.read_parquet(config.run_dir / f"{period}_origins.parquet")
        timing = predict_origins(
            adapter, origins, sequences, config, config.run_dir / f"{period}_forecasts"
        )
        forecasts = load_forecasts(config.run_dir / f"{period}_forecasts")
        paired = attach_actuals(forecasts, actual_table(sequences, forecasts))
        paired.to_parquet(config.run_dir / f"{period}_evaluation.parquet", index=False)
        result["periods"][period] = {
            "timing": timing,
            "metrics": summarize(paired, pd.read_parquet(config.run_dir / "mase_scales.parquet")),
        }
    verify_study(config)
    write_json(config.run_dir / "forecast_results.json", result)
    return result
