"""Independent fixed LightGBM ablations, split-isolated calibration and frozen policies."""

import json
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import psutil
from scipy.special import logit
from sklearn.linear_model import LogisticRegression

from factorygraph.config import load_config as baseline_config
from factorygraph.evaluation import budget_threshold
from factorygraph.inference import calibrate
from factorygraph.io import sha256, write_json
from factorygraph.phase5.common import GROUPS, KEYS, exact_join, save_manifest, verify_registration


def fit_calibrator(probabilities, labels, timestamps):
    if (timestamps < pd.Timestamp("2015-08-01T00:00Z")).any() or (
        timestamps >= pd.Timestamp("2015-09-01T00:00Z")
    ).any():
        raise ValueError("Calibration must use original August split only")
    fitted = LogisticRegression(C=1.0, solver="lbfgs", random_state=42)
    fitted.fit(logit(np.clip(probabilities, 1e-7, 1 - 1e-7)).reshape(-1, 1), labels)
    return {"slope": float(fitted.coef_[0, 0]), "intercept": float(fitted.intercept_[0])}


def validation_policies(probabilities, timestamps, budgets, original):
    if (timestamps < pd.Timestamp("2015-09-01T00:00Z")).any() or (
        timestamps >= pd.Timestamp("2015-10-01T00:00Z")
    ).any():
        raise ValueError("Alert selection must use September validation only")
    return {
        **{f"budget_{b:g}": budget_threshold(probabilities, b) for b in budgets},
        "original_phase1_numeric_threshold": original,
    }


def columns_for(assembly, name):
    columns = [c for group in GROUPS[name] for c in assembly["groups"][group]]
    if len(columns) != len(set(columns)) or set(columns) & {
        "machineID",
        "datetime",
        "label",
        "label_end",
        "next_failure",
    }:
        raise ValueError("Invalid or label-bearing feature contract")
    return columns


def read_matched(config):
    assembly = json.loads((config.run_dir / "assembly.json").read_text())
    frames = {}
    for split, record in assembly["splits"].items():
        path = Path(record["path"])
        if sha256(path) != record["sha256"]:
            raise ValueError("Matched data changed")
        frames[split] = pd.read_parquet(path)
    return assembly, frames


def model_parameters():
    base = baseline_config(Path("configs/baseline.yaml"))
    return {
        **base.model.model_dump(),
        "objective": "binary",
        "verbosity": -1,
        "deterministic": True,
        "force_col_wise": True,
    }


def smoke(config):
    if (config.run_dir / "smoke.json").exists():
        raise ValueError("Smoke exists")
    assembly, frames = read_matched(config)
    columns = columns_for(assembly, "A6")
    model = lgb.LGBMClassifier(**{**model_parameters(), "n_estimators": 20})
    model.fit(
        frames["train"].head(20000)[columns],
        frames["train"].head(20000).label,
        categorical_feature=["model_code"],
    )
    cal = frames["calibration"]
    raw = model.predict_proba(cal[columns])[:, 1]
    parameters = fit_calibrator(raw, cal.label, cal.datetime)
    target = config.run_dir / "smoke_model.txt"
    model.booster_.save_model(str(target))
    reload = lgb.Booster(model_file=str(target))
    predicted = reload.predict(cal.head(100)[columns], num_threads=4)
    if not np.allclose(predicted, raw[:100], atol=1e-12):
        raise ValueError("Smoke model reload differs")
    if not np.isfinite(calibrate(raw, parameters)).all():
        raise ValueError("Invalid calibrated smoke")
    result = {
        "status": "passed",
        "training_rows": 20000,
        "trees": 20,
        "calibration": parameters,
        "model_sha256": sha256(target),
        "test_scored": False,
    }
    write_json(config.run_dir / "smoke.json", result)
    return result


def register_ablations(config):
    verify_registration(config)
    if json.loads((config.run_dir / "smoke.json").read_text())["status"] != "passed":
        raise ValueError("Fusion smoke must pass")
    target = config.run_dir / "ablation_registration.json"
    if target.exists():
        raise ValueError("Ablations already registered")
    assembly = json.loads((config.run_dir / "assembly.json").read_text())
    record = {
        "status": "registered_before_full_fits_and_test_metrics",
        "primary": "A6",
        "parameters": model_parameters(),
        "ablations": {n: columns_for(assembly, n) for n in GROUPS},
        "assembly_sha256": sha256(config.run_dir / "assembly.json"),
        "feature_sha256": {n: r["sha256"] for n, r in assembly["splits"].items()},
        "relational_manifest_sha256": sha256(config.run_dir / "relational_manifest.json"),
        "calibration": "August sigmoid C=1",
        "alert_selection": "September budgets only",
        "seed": config.seed,
        "test_already_observed": True,
    }
    write_json(target, record)
    return record


def train(config):
    verify_registration(config)
    registration = json.loads((config.run_dir / "ablation_registration.json").read_text())
    if sha256(config.run_dir / "assembly.json") != registration["assembly_sha256"]:
        raise ValueError("Ablation inputs changed")
    if (
        sha256(config.run_dir / "relational_manifest.json")
        != registration["relational_manifest_sha256"]
    ):
        raise ValueError("Independent relational inputs changed")
    assembly, frames = read_matched(config)
    models = config.run_dir / "models"
    if models.exists():
        raise ValueError("Model outputs exist; no outcome-driven reruns")
    models.mkdir()
    start = time.perf_counter()
    runtimes = {}
    old_threshold = json.loads(Path("artifacts/baseline/policy.json").read_text())["threshold"]
    for name in GROUPS:
        directory = models / name
        directory.mkdir()
        columns = registration["ablations"][name]
        current_frames = frames
        if name == "A4":
            relational = json.loads((config.run_dir / "relational_manifest.json").read_text())
            current_frames = {}
            for split, frame in frames.items():
                record = relational["splits"][split]
                path = Path(record["path"])
                if sha256(path) != record["sha256"]:
                    raise ValueError("Independent relational feature file changed")
                equivalent = exact_join(frame, pd.read_parquet(path), assembly["groups"]["E"])
                original = frame[[*KEYS, "label", "label_end", *assembly["groups"]["A"]]].copy()
                current_frames[split] = original.merge(equivalent, on=KEYS, validate="one_to_one")
        model = lgb.LGBMClassifier(**registration["parameters"])
        tick = time.perf_counter()
        model.fit(
            current_frames["train"][columns],
            current_frames["train"].label,
            categorical_feature=["model_code"],
        )
        fitting = time.perf_counter() - tick
        model.booster_.save_model(str(directory / "model.txt"))
        tick = time.perf_counter()
        cal = current_frames["calibration"]
        parameters = fit_calibrator(
            model.predict_proba(cal[columns])[:, 1], cal.label, cal.datetime
        )
        calibration_seconds = time.perf_counter() - tick
        write_json(directory / "calibration.json", parameters)
        write_json(
            directory / "feature_contract.json",
            {
                "columns": columns,
                "n_jobs": 4,
                "groups": GROUPS[name],
                "missing": "Native NaN; no fitted imputation",
            },
        )
        pd.DataFrame(
            {"feature": columns, "gain": model.booster_.feature_importance("gain")}
        ).to_csv(directory / "feature_importance.csv", index=False)
        predictions = {}
        prediction_timing = {}
        for split in ["calibration", "validation", "test"]:
            frame = current_frames[split]
            tick = time.perf_counter()
            p = model.booster_.predict(frame[columns], num_threads=4)
            probability = calibrate(p, parameters)
            prediction_timing[split] = time.perf_counter() - tick
            result = frame[[*KEYS, "label", "label_end"]].copy()
            result["raw_probability"] = p
            result["probability"] = probability
            result.to_parquet(directory / f"{split}_predictions.parquet", index=False)
            predictions[split] = result
        policies = validation_policies(
            predictions["validation"].probability.to_numpy(),
            predictions["validation"].datetime,
            config.alert_budgets,
            old_threshold,
        )
        write_json(
            directory / "policy.json",
            {
                "threshold": policies["budget_0.01"],
                "selected_on": "September validation only",
                "budgets": policies,
                "cooldown_hours": 24,
            },
        )
        tick = time.perf_counter()
        loaded = lgb.Booster(model_file=str(directory / "model.txt"))
        load_seconds = time.perf_counter() - tick
        sample = current_frames["test"].head(256)[columns]
        loaded.predict(sample, num_threads=4)
        samples = []
        for _ in range(5):
            tick = time.perf_counter()
            calibrate(loaded.predict(sample, num_threads=4), parameters)
            samples.append(time.perf_counter() - tick)
        memory = psutil.Process().memory_info()
        runtime = {
            "training_seconds": fitting,
            "calibration_seconds": calibration_seconds,
            "prediction_seconds": prediction_timing,
            "model_load_seconds": load_seconds,
            "warm_batch_rows": len(sample),
            "warm_batch_ms_p50": float(np.median(samples) * 1000),
            "warm_batch_ms_p95": float(np.quantile(samples, 0.95) * 1000),
            "warm_rows_per_second": float(len(sample) / np.median(samples)),
            "rss_bytes": memory.rss,
            "peak_working_set_bytes": getattr(memory, "peak_wset", None),
            "scope": (
                "CPU process includes shared matched tables/libraries; "
                "warm cached feature prediction+calibration"
            ),
        }
        write_json(directory / "runtime.json", runtime)
        save_manifest(directory)
        runtimes[name] = runtime
        print(f"Frozen model and predictions: {name}", flush=True)
    result = {
        "status": "all_models_and_test_predictions_frozen_before_analysis",
        "seconds": time.perf_counter() - start,
        "models": runtimes,
        "prediction_manifests": {n: sha256(models / n / "artifact_manifest.json") for n in GROUPS},
    }
    write_json(config.run_dir / "frozen_models.json", result)
    return result
