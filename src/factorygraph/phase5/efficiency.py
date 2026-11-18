"""Explicit offline feature costs and warm cached prediction, without serving claims."""

import json
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import psutil

from factorygraph.config import load_config as baseline_config
from factorygraph.data import load_tables
from factorygraph.features import build_features
from factorygraph.inference import calibrate
from factorygraph.io import sha256, write_json
from factorygraph.phase5.common import KEYS, exact_join, splits


def measure(config):
    if (config.run_dir / "efficiency.json").exists():
        raise ValueError("Efficiency evidence exists")
    base = baseline_config(Path("configs/baseline.yaml"))
    tick = time.perf_counter()
    tables = load_tables(base.processed_dir)
    tabular_input_seconds = time.perf_counter() - tick
    tick = time.perf_counter()
    rebuilt = build_features(tables, base.features)
    tabular_compute_seconds = time.perf_counter() - tick
    columns = json.loads(Path("artifacts/baseline/feature_contract.json").read_text())["columns"]
    keys = pd.concat([f[KEYS] for f in splits().values()], ignore_index=True)
    joined = exact_join(
        keys, rebuilt.loc[rebuilt.set_index(KEYS).index.isin(keys.set_index(KEYS).index)], columns
    )
    expected = pd.concat([f[columns] for f in splits(labels=True).values()], ignore_index=True)
    if not np.allclose(
        joined[columns].to_numpy(), expected.to_numpy(), atol=1e-10, rtol=1e-10, equal_nan=True
    ):
        raise ValueError("Read-only tabular preparation differs from accepted values")
    del tables, rebuilt, joined, expected
    tick = time.perf_counter()
    assembly = json.loads((config.run_dir / "assembly.json").read_text())
    frame = pd.read_parquet(config.run_dir / "matched_test.parquet")
    feature_cache_load_seconds = time.perf_counter() - tick
    directory = config.run_dir / "models/A6"
    contract = json.loads((directory / "feature_contract.json").read_text())
    tick = time.perf_counter()
    model = lgb.Booster(model_file=str(directory / "model.txt"))
    calibration = json.loads((directory / "calibration.json").read_text())
    load_seconds = time.perf_counter() - tick
    tick = time.perf_counter()
    p = calibrate(model.predict(frame[contract["columns"]], num_threads=4), calibration)
    inference_seconds = time.perf_counter() - tick
    saved = pd.read_parquet(directory / "test_predictions.parquet")
    if not np.allclose(p, saved.probability, atol=1e-12):
        raise ValueError("Complete cached path differs")
    runtime = json.loads((config.run_dir / "forecast_runtime.json").read_text())
    temporal = json.loads((config.run_dir / "temporal_manifest.json").read_text())
    relation = json.loads((config.run_dir / "relational_manifest.json").read_text())
    model_runtime = json.loads((config.run_dir / "frozen_models.json").read_text())
    memory = psutil.Process().memory_info()
    result = {
        "status": "completed",
        "tabular_source_load_seconds": tabular_input_seconds,
        "tabular_feature_rebuild_seconds": tabular_compute_seconds,
        "tabular_values_match_original": True,
        "cheap_forecast_seconds": runtime["timing"]["cheap_seconds"],
        "forecast_runtime": runtime,
        "temporal_export_seconds": temporal["seconds"],
        "temporal_group_compute_seconds": temporal["group_compute_seconds"],
        "graph_cache_load_join_seconds": assembly["graph_cache_load_join_seconds"],
        "accepted_phase4_graph_export_seconds_reference": json.loads(
            Path("artifacts/phase4/full/feature_manifest.json").read_text()
        )["export_seconds"],
        "relational_control_seconds": relation["seconds"],
        "model_runtimes": model_runtime["models"],
        "A6_complete_cached_path": {
            "rows": len(frame),
            "feature_cache_load_seconds": feature_cache_load_seconds,
            "model_load_seconds": load_seconds,
            "predict_calibrate_seconds": inference_seconds,
            "total_seconds": feature_cache_load_seconds + load_seconds + inference_seconds,
            "scope": (
                "Persisted common feature cache+model+calibration, "
                "excludes upstream feature computation"
            ),
        },
        "storage_bytes": {
            kind: sum(p.stat().st_size for p in config.run_dir.rglob(pattern))
            for kind, pattern in [
                ("forecast_cache", "forecasts/*.parquet"),
                ("temporal_feature_cache", "temporal_*.parquet"),
                ("matched_feature_cache", "matched_*.parquet"),
                ("relational_cache", "relational_*.parquet"),
                ("models", "models/*/model.txt"),
            ]
        },
        "rss_bytes": memory.rss,
        "peak_working_set_bytes": getattr(memory, "peak_wset", None),
        "no_production_latency_claim": True,
    }
    write_json(config.run_dir / "efficiency.json", result)
    return result


def graph_export_benchmark(config):
    """Run in the unchanged Phase4 environment; read graph, write only new Phase5 paths."""
    import shutil

    from factorygraph.phase4.config import load_config as graph_config
    from factorygraph.phase4.database import GraphDB
    from factorygraph.phase4.features import export_features

    destination = config.run_dir / "graph_export_benchmark"
    if destination.exists():
        raise ValueError("Graph cost benchmark exists")
    destination.mkdir()
    shutil.copyfile("artifacts/phase4/full/build.json", destination / "build.json")
    settings = graph_config(Path("configs/phase4/full.yaml")).model_copy(
        update={"run_dir": destination}
    )
    db = GraphDB(settings)
    try:
        manifest = export_features(db, settings)
    finally:
        db.close()
    for split, record in manifest["split_artifacts"].items():
        actual = pd.read_parquet(record["path"])[manifest["feature_columns"]]
        expected = pd.read_parquet(f"artifacts/phase4/full/features_{split}.parquet")[
            manifest["feature_columns"]
        ]
        if not np.array_equal(actual.to_numpy(), expected.to_numpy(), equal_nan=True):
            raise ValueError("Fresh graph export differs from accepted numeric values")
    result = {
        "status": "completed",
        "seconds": manifest["export_seconds"],
        "numeric_values_equal": True,
        "feature_manifest_sha256": sha256(destination / "feature_manifest.json"),
    }
    write_json(config.run_dir / "graph_export_runtime.json", result)
    return result
