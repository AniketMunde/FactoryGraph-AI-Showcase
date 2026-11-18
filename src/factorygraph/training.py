"""Fixed classical baseline. No test-driven tuning or fitted preprocessing on future periods."""

import json
import logging
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
import psutil
from scipy.special import logit
from sklearn.linear_model import LogisticRegression

from factorygraph.config import ExperimentConfig
from factorygraph.data import load_tables
from factorygraph.evaluation import budget_threshold, evaluate_predictions
from factorygraph.features import (
    attach_labels,
    build_features,
    chronological_split,
    feature_columns,
)
from factorygraph.inference import Predictor, calibrate
from factorygraph.io import sha256, verify_artifacts, write_json

LOGGER = logging.getLogger(__name__)


def create_snapshots(config: ExperimentConfig, tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    snapshots = attach_labels(
        build_features(tables, config.features), tables, config.features.horizon_hours
    )
    path = config.processed_dir / "snapshots.parquet"
    snapshots.to_parquet(path, index=False)
    write_json(
        config.processed_dir / "snapshot_manifest.json",
        {
            "features": config.features.model_dump(),
            "rows": len(snapshots),
            "sha256": sha256(path),
            "normalized_sha256": {
                name: sha256(config.processed_dir / f"{name}.parquet") for name in tables
            },
            "data_manifest_sha256": sha256(config.processed_dir / "data_manifest.json"),
        },
    )
    return snapshots


def verified_snapshots(config: ExperimentConfig) -> pd.DataFrame:
    manifest = json.loads((config.processed_dir / "snapshot_manifest.json").read_text())
    if manifest["features"] != config.features.model_dump():
        raise ValueError("Feature configuration changed; rerun prepare")
    expected = {
        "snapshots.parquet": manifest["sha256"],
        "data_manifest.json": manifest["data_manifest_sha256"],
        **{f"{name}.parquet": digest for name, digest in manifest["normalized_sha256"].items()},
    }
    for filename, digest in expected.items():
        if sha256(config.processed_dir / filename) != digest:
            raise ValueError(f"Prepared artifact changed: {filename}; rerun prepare")
    return pd.read_parquet(config.processed_dir / "snapshots.parquet")


def evaluate_run(run_dir: Path) -> dict[str, Any]:
    verify_artifacts(run_dir)
    config = ExperimentConfig.model_validate_json((run_dir / "config.json").read_text())
    threshold = json.loads((run_dir / "policy.json").read_text())["threshold"]
    failures = pd.read_parquet(run_dir / "evaluation_failures.parquet")
    metrics = {}
    for split in ["calibration", "validation", "test"]:
        predictions = pd.read_parquet(run_dir / f"{split}_predictions.parquet")
        metrics[split] = evaluate_predictions(
            predictions,
            failures,
            threshold=threshold,
            budget_fraction=config.alert_budget_fraction,
            snapshot_hours=config.features.snapshot_hours,
            horizon_hours=config.features.horizon_hours,
            cooldown_hours=config.cooldown_hours,
        )
    write_json(run_dir / "metrics.json", metrics)
    return metrics


def train(config: ExperimentConfig) -> dict[str, Any]:
    if config.run_dir.exists() and any(config.run_dir.iterdir()):
        raise ValueError("Run directory is nonempty; choose a new run_dir to preserve experiments")
    snapshots = verified_snapshots(config)
    splits = chronological_split(snapshots, config.split)
    for name, frame in splits.items():
        if frame.empty or frame.label.nunique() < 2:
            raise ValueError(f"{name}: requires nonempty positive and negative examples")
    columns = feature_columns(config.features)
    run_dir = config.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "config.json", config.model_dump(mode="json"))
    write_json(
        run_dir / "feature_contract.json",
        {
            "columns": columns,
            "features": config.features.model_dump(),
            "n_jobs": config.model.n_jobs,
            "availability": "All dynamic feature source timestamps strictly precede snapshot time",
        },
    )
    write_json(
        run_dir / "split_summary.json",
        {
            name: {
                "rows": len(frame),
                "positive_rows": int(frame.label.sum()),
                "start": frame.datetime.min().isoformat(),
                "end": frame.datetime.max().isoformat(),
                "latest_label_end": frame.label_end.max().isoformat(),
            }
            for name, frame in splits.items()
        },
    )
    model = lgb.LGBMClassifier(
        **config.model.model_dump(),
        objective="binary",
        verbosity=-1,
        deterministic=True,
        force_col_wise=True,
    )
    LOGGER.info("training rows=%d features=%d", len(splits["train"]), len(columns))
    start = time.perf_counter()
    model.fit(splits["train"][columns], splits["train"].label, categorical_feature=["model_code"])
    training_seconds = time.perf_counter() - start
    model.booster_.save_model(str(run_dir / "model.txt"))
    calibration_frame = splits["calibration"]
    raw = model.predict_proba(calibration_frame[columns])[:, 1]
    calibrator = LogisticRegression(C=1.0, solver="lbfgs", random_state=config.model.random_state)
    calibrator.fit(logit(np.clip(raw, 1e-7, 1 - 1e-7)).reshape(-1, 1), calibration_frame.label)
    parameters = {
        "slope": float(calibrator.coef_[0, 0]),
        "intercept": float(calibrator.intercept_[0]),
    }
    write_json(run_dir / "calibration.json", parameters)
    pd.DataFrame(
        {
            "feature": columns,
            "importance_gain": model.booster_.feature_importance(importance_type="gain"),
        }
    ).sort_values("importance_gain", ascending=False).to_csv(
        run_dir / "feature_importance.csv", index=False
    )
    for name in ["calibration", "validation", "test"]:
        frame = splits[name]
        predictions = frame[["machineID", "datetime", "label", "label_end"]].copy()
        predictions["raw_probability"] = model.predict_proba(frame[columns])[:, 1]
        predictions["probability"] = calibrate(predictions.raw_probability.to_numpy(), parameters)
        predictions.to_parquet(run_dir / f"{name}_predictions.parquet", index=False)
    validation = pd.read_parquet(run_dir / "validation_predictions.parquet")
    threshold = budget_threshold(validation.probability.to_numpy(), config.alert_budget_fraction)
    write_json(
        run_dir / "policy.json",
        {
            "threshold": threshold,
            "selected_on": "validation",
            "budget_fraction": config.alert_budget_fraction,
            "cooldown_hours": config.cooldown_hours,
            "tie_policy": "Conservative; ties at the boundary excluded",
        },
    )
    load_tables(config.processed_dir)["failures"].to_parquet(
        run_dir / "evaluation_failures.parquet", index=False
    )
    metrics = evaluate_run(run_dir)
    start = time.perf_counter()
    predictor = Predictor(run_dir)
    load_seconds = time.perf_counter() - start
    sample = splits["test"].head(256)[columns]
    predictor.predict(sample)  # Warm-up is separate from timing.
    durations = []
    for _ in range(10):
        start = time.perf_counter()
        predictor.predict(sample)
        durations.append(time.perf_counter() - start)
    memory = psutil.Process().memory_info()
    write_json(
        run_dir / "runtime.json",
        {
            "training_seconds": training_seconds,
            "model_load_seconds": load_seconds,
            "inference_batch_rows": len(sample),
            "inference_repeats": len(durations),
            "inference_batch_latency_ms_p50": float(np.median(durations) * 1000),
            "inference_batch_latency_ms_p95": float(np.quantile(durations, 0.95) * 1000),
            "inference_rows_per_second": float(len(sample) / np.median(durations)),
            "process_rss_bytes_after_training": memory.rss,
            "process_peak_working_set_bytes": getattr(memory, "peak_wset", None),
            "cpu_threads_model": config.model.n_jobs,
            "gpu_used": False,
            "scope": "Warm precomputed feature batch + calibration; excludes data/feature pipeline",
        },
    )
    git = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, check=False
    )
    write_json(
        run_dir / "environment.json",
        {
            "created_at": datetime.now(UTC).isoformat(),
            "python": sys.version,
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logical_cpus": psutil.cpu_count(),
            "physical_memory_bytes": psutil.virtual_memory().total,
            "git_revision": git.stdout.strip() if git.returncode == 0 else None,
            "git_dirty": bool(dirty.stdout.strip()),
            "packages": {
                name: version(name)
                for name in [
                    "factorygraph-ai",
                    "numpy",
                    "pandas",
                    "pyarrow",
                    "scikit-learn",
                    "lightgbm",
                    "scipy",
                    "pydantic",
                    "PyYAML",
                    "psutil",
                ]
            },
            "source_sha256": {
                path.as_posix(): sha256(path)
                for path in sorted(Path("src/factorygraph").glob("*.py"))
            },
        },
    )
    for filename in ["data_manifest.json", "snapshot_manifest.json"]:
        write_json(run_dir / filename, json.loads((config.processed_dir / filename).read_text()))
    write_json(
        run_dir / "artifact_manifest.json",
        {path.name: sha256(path) for path in sorted(run_dir.iterdir()) if path.is_file()},
    )
    LOGGER.info("test average_precision=%.6f", metrics["test"]["pr_auc_average_precision"])
    return metrics
