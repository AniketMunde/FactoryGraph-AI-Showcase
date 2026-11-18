"""Bounded genuine-model smoke and paired evaluation against the frozen baseline."""

import json
import logging
import math
import os
import platform
import shutil
import subprocess
import sys
import time
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psutil

from factorygraph.evaluation import budget_threshold, evaluate_predictions
from factorygraph.io import sha256, write_json
from factorygraph.phase2.adapter import KumoAdapter
from factorygraph.phase2.config import Phase2Config
from factorygraph.phase2.context import KEYS, pair_frozen_predictions
from factorygraph.phase2.inputs import (
    load_inputs,
    registered_context,
    registered_queries,
    verify_registration,
)
from factorygraph.phase2.metrics import score, summarize_timings

LOGGER = logging.getLogger(__name__)


def memory_state(torch: Any = None) -> dict[str, Any]:
    info = psutil.Process().memory_info()
    gpu = torch is not None and torch.cuda.is_available()
    return {
        "rss_bytes": info.rss,
        "peak_process_working_set_bytes": getattr(info, "peak_wset", None),
        "system_available_bytes": psutil.virtual_memory().available,
        "gpu_peak_allocated_bytes": torch.cuda.max_memory_allocated() if gpu else None,
        "gpu_peak_reserved_bytes": torch.cuda.max_memory_reserved() if gpu else None,
    }


def resource_guard(config: Phase2Config) -> None:
    if psutil.virtual_memory().available < config.minimum_free_ram_gb * 1e9:
        raise RuntimeError("Available RAM fell below the registered safety floor; stop this run")


def smoke(config: Phase2Config) -> dict[str, Any]:
    registration = verify_registration(config)
    output = config.run_dir / "smoke.json"
    if output.exists():
        raise ValueError("Smoke evidence exists; use a new registered run to repeat")
    resource_guard(config)
    _, columns, splits, _ = load_inputs(config)
    query = registered_queries(config, splits["validation"], "validation").head(config.batch_size)
    adapter = KumoAdapter(config, columns)
    load = adapter.load()
    torch = adapter.torch
    if config.device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    context_results = {}
    for size in config.context_sizes:
        resource_guard(config)
        context = registered_context(config, splits["train"], size)
        context_time = adapter.set_context(context)
        # Untimed warm-up, then repeat the identical feature batch to audit repeatability.
        first, _ = adapter.predict(query[KEYS + columns])
        timings = []
        for _ in range(3):
            probabilities, timing = adapter.predict(query[KEYS + columns])
            if not np.allclose(first, probabilities, atol=1e-5, rtol=1e-5):
                raise RuntimeError("Smoke predictions differ across identical repeated queries")
            timings.append({**timing, "rows": len(query)})
        context_results[str(size)] = {
            "context_timing": context_time,
            "timing": summarize_timings(timings),
            "memory": memory_state(torch),
            "repeat_max_absolute_difference": float(np.max(np.abs(first - probabilities))),
        }
        LOGGER.info(
            "smoke context=%d batch_ms=%.2f",
            size,
            context_results[str(size)]["timing"]["batch_total_ms_p50"],
        )

    def projected(counts: dict[str, int]) -> float:
        seconds = sum(
            math.ceil(counts["validation"] / config.batch_size)
            * context_results[str(size)]["timing"]["batch_total_ms_p95"]
            / 1000
            for size in config.context_sizes
        )
        seconds += math.ceil(counts["test"] / config.batch_size) * max(
            item["timing"]["batch_total_ms_p95"] / 1000 for item in context_results.values()
        )
        seconds += (
            sum(sum(item["context_timing"].values()) for item in context_results.values()) * 2
        )
        return seconds * 1.5

    estimate = projected(registration["query_rows"])
    # CPU behavior is a genuine pretrained-model check, not a unit-test substitute.
    cpu_config = config.model_copy(update={"device": "cpu"})
    cpu = KumoAdapter(cpu_config, columns)
    cpu_load = cpu.load()
    cpu_context = cpu.set_context(
        registered_context(config, splits["train"], config.context_sizes[0])
    )
    _, cpu_time = cpu.predict(query[KEYS + columns].head(2))
    result = {
        "status": "passed" if estimate <= config.max_projected_seconds else "resource_limited",
        "model_load": load,
        "device": config.device,
        "contexts": context_results,
        "query_rows_per_batch": len(query),
        "projected_pilot_seconds_with_margin": estimate,
        "projected_full_fleet_seconds_with_margin": projected(registration["full_fleet_rows"]),
        "cpu_genuine_inference": {
            "rows": 2,
            "load": cpu_load,
            "context_timing": cpu_context,
            "prediction_timing": cpu_time,
        },
        "hardware": {
            "platform": platform.platform(),
            "logical_cpus": psutil.cpu_count(),
            "ram_total_bytes": psutil.virtual_memory().total,
            "disk_free_bytes": shutil.disk_usage(".").free,
            "gpu_name": torch.cuda.get_device_name() if torch.cuda.is_available() else None,
            "gpu_total_bytes": torch.cuda.get_device_properties(0).total_memory
            if (torch.cuda.is_available())
            else None,
            "torch": torch.__version__,
            "torch_cuda": torch.version.cuda,
        },
        "checkpoint": json.loads((config.model_dir / "checkpoint_manifest.json").read_text()),
    }
    write_json(output, result)
    verify_registration(config)
    return result


def predict_period(
    adapter: KumoAdapter,
    query: pd.DataFrame,
    columns: list[str],
    config: Phase2Config,
    deadline: float,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    batches = []
    frames = []
    period_start = time.perf_counter()
    for offset in range(0, len(query), config.batch_size):
        resource_guard(config)
        if time.perf_counter() > deadline:
            raise RuntimeError("Registered wall-time limit exceeded; no cohort truncation allowed")
        batch = query.iloc[offset : offset + config.batch_size]
        probability, timing = adapter.predict(batch[KEYS + columns])
        output = batch[KEYS + ["label", "label_end"]].copy()
        output["probability"] = probability[:, 1]
        frames.append(output)
        batches.append({**timing, "rows": len(batch)})
        if offset % (config.batch_size * 25) == 0:
            LOGGER.info(
                "predicted rows=%d/%d", min(offset + config.batch_size, len(query)), len(query)
            )
    result = pd.concat(frames, ignore_index=True)
    timings = summarize_timings(batches)
    timings["period_wall_seconds"] = time.perf_counter() - period_start
    timings["memory"] = memory_state(adapter.torch)
    return result, timings


def run(config: Phase2Config) -> dict[str, Any]:
    registration = verify_registration(config)
    if (config.run_dir / "results.json").exists() or (
        config.run_dir / "selected_policy.json"
    ).exists():
        raise ValueError("Evaluation state already exists; use a new registered run directory")
    evidence = json.loads((config.run_dir / "smoke.json").read_text())
    if evidence["status"] != "passed":
        raise RuntimeError("Genuine-model smoke/resource gate has not passed")
    baseline, columns, splits, failures = load_inputs(config)
    validation = registered_queries(config, splits["validation"], "validation")
    adapter = KumoAdapter(config, columns)
    model_load = adapter.load()
    if config.device == "cuda":
        adapter.torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    deadline = started + config.max_projected_seconds
    results: dict[str, Any] = {
        "study_scope": "10-machine pilot"
        if config.cohort_machines == 10
        else "registered machine cohort",
        "context_sensitivity_validation": {},
    }
    for size in config.context_sizes:
        context_start = time.perf_counter()
        context = registered_context(config, splits["train"], size)
        construction = adapter.set_context(context)
        construction["selection_and_cache_wall_seconds"] = time.perf_counter() - context_start
        predictions, timing = predict_period(adapter, validation, columns, config, deadline)
        threshold = budget_threshold(
            predictions.probability.to_numpy(), baseline.alert_budget_fraction
        )
        metrics = score(predictions, failures, threshold, baseline)
        predictions.to_parquet(config.run_dir / f"validation_context_{size}.parquet", index=False)
        results["context_sensitivity_validation"][str(size)] = {
            "metrics": metrics,
            "timing": timing,
            "context_construction": construction,
            "context_positive_rows": int(context.label.sum()),
        }
    selected = max(
        config.context_sizes,
        key=lambda size: (
            results["context_sensitivity_validation"][str(size)]["metrics"][
                "pr_auc_average_precision"
            ],
            -size,
        ),
    )
    threshold = results["context_sensitivity_validation"][str(selected)]["metrics"]["threshold"]
    policy = {
        "context_size": selected,
        "threshold": threshold,
        "selection_period": "September validation only",
        "calibration": "none",
        "selection_metric": "average precision; ties choose smaller context",
    }
    write_json(config.run_dir / "selected_policy.json", policy)
    # Test labels are first used for evaluation after the policy has been persisted.
    test = registered_queries(config, splits["test"], "test")
    construction = adapter.set_context(registered_context(config, splits["train"], selected))
    test_predictions, timing = predict_period(adapter, test, columns, config, deadline)
    test_predictions.to_parquet(config.run_dir / "test_kumo_predictions.parquet", index=False)
    frozen_threshold = json.loads((config.baseline_dir / "policy.json").read_text())["threshold"]
    frozen_test = pd.read_parquet(config.baseline_dir / "test_predictions.parquet")
    paired = pair_frozen_predictions(test, frozen_test)
    paired.to_parquet(config.run_dir / "test_lightgbm_predictions.parquet", index=False)
    results["selected_policy"] = policy
    results["test"] = {
        "kumo": score(test_predictions, failures, threshold, baseline),
        "lightgbm_frozen": score(paired, failures, frozen_threshold, baseline),
    }
    if config.cohort_machines == 100:
        results["test_phase1_opportunity_event_definition"] = {
            name: evaluate_predictions(
                predictions,
                failures,
                threshold=value,
                budget_fraction=baseline.alert_budget_fraction,
                snapshot_hours=baseline.features.snapshot_hours,
                horizon_hours=baseline.features.horizon_hours,
                cooldown_hours=baseline.cooldown_hours,
            )
            for name, predictions, value in [
                ("kumo", test_predictions, threshold),
                ("lightgbm_frozen", paired, frozen_threshold),
            ]
        }
    results["monthly_test"] = {}
    for month in sorted(test_predictions.datetime.dt.strftime("%Y-%m").unique()):
        mask = test_predictions.datetime.dt.strftime("%Y-%m") == month
        baseline_mask = paired.datetime.dt.strftime("%Y-%m") == month
        results["monthly_test"][month] = {
            "kumo": score(test_predictions.loc[mask], failures, threshold, baseline),
            "lightgbm_frozen": score(
                paired.loc[baseline_mask], failures, frozen_threshold, baseline
            ),
        }
    # Fresh-process memory avoids attributing a resident Kumo runtime to LightGBM.
    write_json(config.run_dir / "resolved_config.json", config.model_dump(mode="json"))
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "factorygraph.phase2.baseline_benchmark",
            str(config.run_dir / "resolved_config.json"),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    baseline_benchmark = json.loads(process.stdout)
    results["efficiency"] = {
        "kumo_model_load": model_load,
        "kumo_test_context_construction": construction,
        "kumo_test_prediction": timing,
        "lightgbm_fresh_process": baseline_benchmark,
        "study_wall_seconds_excluding_model_load": time.perf_counter() - started,
        "baseline_memory_timing_note": (
            "Fresh baseline process; both measurements include input tables and libraries"
        ),
    }
    results["registration"] = registration
    results["environment"] = {
        "packages": {
            name: version(name)
            for name in [
                "structured-data-models",
                "torch",
                "numpy",
                "pandas",
                "scikit-learn",
                "lightgbm",
            ]
        },
        "source_sha256": {
            path.as_posix(): sha256(path)
            for path in sorted(Path("src/factorygraph/phase2").glob("*.py"))
        },
        "pid": os.getpid(),
    }
    results["status"] = (
        "completed_registered_pilot" if config.cohort_machines < 100 else ("completed_full_fleet")
    )
    results["limitations"] = [
        "Synthetic dataset and previously observed Phase 1 test benchmark",
        "Raw pretrained-context probabilities versus calibrated task-specific LightGBM",
        "Uniform bounded training context versus all historical training rows for LightGBM",
        "Single seed and fixed context budgets; no population-level confidence claim",
        "SDK cached predict timing includes preprocessing/postprocessing, not pure kernel timing",
    ]
    verify_registration(config)
    write_json(config.run_dir / "results.json", results)
    write_json(
        config.run_dir / "artifact_manifest.json",
        {path.name: sha256(path) for path in sorted(config.run_dir.iterdir()) if path.is_file()},
    )
    return results
