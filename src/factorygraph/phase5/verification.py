"""Independent frozen-prediction checks, original labels and model reload verification."""

import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss

from factorygraph.inference import calibrate
from factorygraph.io import sha256, verify_artifacts, write_json
from factorygraph.phase5.analysis import metrics
from factorygraph.phase5.common import GROUPS, KEYS, splits, verify_prior, verify_registration


def verify(config):
    verify_registration(config)
    protected = verify_prior()
    frozen = json.loads((config.run_dir / "frozen_models.json").read_text())
    results = json.loads((config.run_dir / "results.json").read_text())
    assembly = json.loads((config.run_dir / "assembly.json").read_text())
    original = splits(labels=True)
    failures = pd.read_parquet("artifacts/baseline/evaluation_failures.parquet")
    checks = {}
    for name in GROUPS:
        directory = config.run_dir / "models" / name
        verify_artifacts(directory)
        if sha256(directory / "artifact_manifest.json") != frozen["prediction_manifests"][name]:
            raise ValueError("Model/prediction manifest changed after freezing")
        columns = json.loads((directory / "feature_contract.json").read_text())["columns"]
        parameters = json.loads((directory / "calibration.json").read_text())
        policy = json.loads((directory / "policy.json").read_text())
        model = lgb.Booster(model_file=str(directory / "model.txt"))
        maximum = 0.0
        for split in ["calibration", "validation", "test"]:
            p = pd.read_parquet(directory / f"{split}_predictions.parquet")
            if not p[[*KEYS, "label", "label_end"]].equals(
                original[split][[*KEYS, "label", "label_end"]]
            ):
                raise ValueError("Original labels/populations changed")
            calculated = metrics(p, failures, policy["threshold"])
            if calculated != results["models"][name][split]:
                raise ValueError("Saved operational metrics do not reproduce")
            if split == "test":
                if (
                    abs(
                        average_precision_score(p.label, p.probability)
                        - calculated["pr_auc_average_precision"]
                    )
                    > 1e-14
                ):
                    raise ValueError("Independent AP mismatch")
                if abs(brier_score_loss(p.label, p.probability) - calculated["brier"]) > 1e-14:
                    raise ValueError("Independent Brier mismatch")
            matched = pd.read_parquet(config.run_dir / f"matched_{split}.parquet", columns=columns)
            raw = model.predict(matched, num_threads=4)
            maximum = max(
                maximum,
                float(np.max(np.abs(calibrate(raw, parameters) - p.probability.to_numpy()))),
            )
        if maximum > 1e-12:
            raise ValueError("Reloaded model predictions differ")
        checks[name] = {
            "original_keys_labels_equal": True,
            "saved_metrics_reproduced": True,
            "maximum_model_reload_probability_difference": maximum,
        }
    for record in assembly["splits"].values():
        if sha256(Path(record["path"])) != record["sha256"]:
            raise ValueError("Matched feature artifact changed")
    temporal = json.loads((config.run_dir / "temporal_manifest.json").read_text())
    for group in temporal["groups"].values():
        for record in group["splits"].values():
            path = Path(record["path"])
            if sha256(path) != record["sha256"]:
                raise ValueError("Temporal feature artifact changed")
            f = pd.read_parquet(path)
            if (
                (f.latest_source_observation_timestamp >= f.datetime).any()
                or (f.latest_residual_observation_timestamp >= f.datetime).any()
                or (f.forecast_issue_timestamp > f.datetime).any()
            ):
                raise ValueError("Invalid temporal feature clocks")
    output = {
        "status": "passed",
        "protected_historical_files_unchanged": protected,
        "models": checks,
        "all_temporal_clocks_valid": True,
        "no_population_exclusions": True,
        "A3_A4_control_equal": results["A3_A4_max_probability_difference"] == 0,
    }
    write_json(config.run_dir / "verification.json", output)
    return output
