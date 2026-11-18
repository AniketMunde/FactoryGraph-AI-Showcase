"""Independent saved-artifact verification and reproducible Phase 3 result export."""

import json
from importlib.metadata import version
from pathlib import Path

import pandas as pd

from factorygraph.io import sha256, write_json
from factorygraph.phase3.config import load_config
from factorygraph.phase3.metrics import summarize
from factorygraph.phase3.study import (
    actual_table,
    load_forecasts,
    read_sequences,
    verify_study,
)


def finalize() -> dict:
    result = {"date": "2026-11-12", "azure": {}, "metropt": {}}
    for name, path in [
        ("azure", "configs/phase3/azure.yaml"),
        ("metropt", "configs/phase3/metropt.yaml"),
    ]:
        config = load_config(Path(path))
        registration = verify_study(config)
        results_path = config.run_dir / "forecast_results.json"
        if not results_path.exists():
            failure = config.run_dir / "run_failure.json"
            pilot = json.loads((config.run_dir / "admission.json").read_text())
            forecasts = load_forecasts(config.run_dir / "pilot_forecasts")
            paired = pd.read_parquet(config.run_dir / "pilot_evaluation.parquet")
            if (
                summarize(paired, pd.read_parquet(config.run_dir / "mase_scales.parquet"))
                != pilot["validation_pilot_metrics"]
            ):
                raise ValueError("Pilot metrics do not reproduce")
            if len(forecasts) != len(paired):
                raise ValueError("Pilot membership changed")
            partial = list((config.run_dir / "validation_forecasts").glob("*.parquet"))
            validation_path = config.run_dir / "validation_evaluation.parquet"
            completed_validation = None
            if validation_path.exists():
                frozen_validation = load_forecasts(config.run_dir / "validation_forecasts")
                validation = pd.read_parquet(validation_path)
                if len(frozen_validation) != len(validation):
                    raise ValueError("Partial study validation membership changed")
                for column in frozen_validation.columns:
                    if not frozen_validation[column].equals(validation[column]):
                        raise ValueError("Partial study predictions changed after freezing")
                observed = actual_table(read_sequences(config), frozen_validation)
                truth = validation.merge(
                    observed,
                    on=["machineID", "target_time", "channel"],
                    validate="many_to_one",
                    suffixes=("_saved", "_raw"),
                )
                if not (truth.actual_saved == truth.actual_raw).all():
                    raise ValueError("Partial study actuals differ from registered telemetry")
                completed_validation = summarize(
                    validation, pd.read_parquet(config.run_dir / "mase_scales.parquet")
                )
            test_attempted = (config.run_dir / "test_forecasts").exists()
            result[name] = {
                "status": "incomplete_real_forecasting" if name == "metropt" else "incomplete",
                "registration": registration,
                "failure": json.loads(failure.read_text()) if failure.exists() else None,
                "smoke": json.loads((config.run_dir / "smoke.json").read_text()),
                "admission_and_validation_pilot": pilot,
                "pilot_metrics_independently_recomputed": True,
                "saved_validation_forecast_rows": sum(len(pd.read_parquet(p)) for p in partial),
                "completed_validation_metrics": completed_validation,
                "test_inference_attempted": test_attempted,
                "valid_test_forecast_rows_saved": sum(
                    len(pd.read_parquet(p))
                    for p in (config.run_dir / "test_forecasts").glob("*.parquet")
                ),
                "failure_stage": "test" if test_attempted else "validation",
                "partial_files_sha256": {p.as_posix(): sha256(p) for p in partial},
            }
            continue
        stored = json.loads(results_path.read_text())
        scales = pd.read_parquet(config.run_dir / "mase_scales.parquet")
        sequences = read_sequences(config)
        for period in ["validation", "test"]:
            frozen = load_forecasts(config.run_dir / f"{period}_forecasts")
            evaluated = pd.read_parquet(config.run_dir / f"{period}_evaluation.parquet")
            keys = ["machineID", "issue_time", "target_time", "channel", "lead"]
            compared = frozen.merge(
                evaluated, on=keys, validate="one_to_one", suffixes=("_frozen", "_eval")
            )
            if len(compared) != len(frozen) or len(compared) != len(evaluated):
                raise ValueError("Forecast/evaluation membership changed")
            raw_actuals = actual_table(sequences, frozen)
            truth = evaluated.merge(
                raw_actuals,
                on=["machineID", "target_time", "channel"],
                how="left",
                validate="many_to_one",
                suffixes=("_saved", "_raw"),
            )
            if not (truth.actual_saved == truth.actual_raw).all():
                raise ValueError("Evaluation actuals differ from registered source observations")
            origins = pd.read_parquet(config.run_dir / f"{period}_origins.parquet")
            if len(frozen) != len(origins) * len(config.channels) * config.horizon:
                raise ValueError("Incomplete registered forecast population")
            for column in [
                "chronos",
                "q10",
                "q50",
                "q90",
                "persistence",
                "rolling_mean",
                "seasonal_naive",
            ]:
                if not (compared[f"{column}_frozen"] == compared[f"{column}_eval"]).all():
                    raise ValueError("Predictions changed after freezing")
            if summarize(evaluated, scales) != stored["periods"][period]["metrics"]:
                raise ValueError("Saved prediction metrics do not reproduce")
        stored["smoke"] = json.loads((config.run_dir / "smoke.json").read_text())
        stored["admission"] = json.loads((config.run_dir / "admission.json").read_text())
        stored["metrics_independently_recomputed"] = True
        stored["actuals_independently_matched_to_raw_telemetry"] = True
        result[name] = stored
    config = load_config(Path("configs/phase3/azure.yaml"))
    anomaly_path = config.run_dir / "anomaly_results.json"
    if anomaly_path.exists():
        result["anomalies_and_features"] = json.loads(anomaly_path.read_text())
        manifest = json.loads((config.run_dir / "feature_manifest.json").read_text())
        if sha256(config.run_dir / "features_test.parquet") != manifest["sha256"]:
            raise ValueError("Feature export integrity failure")
        features = pd.read_parquet(config.run_dir / "features_test.parquet")
        keys = ["machineID", "datetime"]
        expected = pd.read_parquet("artifacts/baseline/test_predictions.parquet")[keys]
        if not features[keys].equals(expected):
            raise ValueError("Export row membership/order differs from accepted snapshots")
        for field in [
            "latest_source_observation_timestamp",
            "latest_residual_observation_timestamp",
        ]:
            if (features[field] >= features.datetime).any():
                raise ValueError("Future source observation in exported features")
        if (features.forecast_issue_timestamp > features.datetime).any():
            raise ValueError("Future forecast issue in exported features")
        result["status"] = "phase3_completed_with_full_registered_azure_evaluation"
    else:
        result["status"] = "forecasting_complete_feature_export_incomplete"
    result["prior_phases_preserved"] = True
    result["protected_file_count"] = len(
        json.loads((config.run_dir / "protected.json").read_text())
    )
    result["hardware_preflight"] = json.loads(
        Path("artifacts/phase3/research/preflight.json").read_text()
    )
    result["metropt_preparation"] = json.loads(
        Path("data/phase3/metropt/preparation_manifest.json").read_text()
    )
    verification_path = Path("artifacts/phase3/verification.json")
    if verification_path.exists():
        result["software_verification"] = json.loads(verification_path.read_text())
    result["packages"] = {
        name: version(name)
        for name in [
            "torch",
            "chronos-forecasting",
            "transformers",
            "huggingface-hub",
            "pandas",
            "numpy",
        ]
    }
    result["checkpoint"] = json.loads((config.model_dir / "manifest.json").read_text())
    result["source_sha256"] = {
        p.as_posix(): sha256(p) for p in Path("src/factorygraph/phase3").glob("*.py")
    }
    result["limitations"] = [
        "Synthetic Azure results do not establish industrial failure-prediction benefit",
        "Daily forecast issuance differs from three-hour feature snapshots; age is explicit",
        "Validation thresholds restrict exported features to eligible test snapshots",
        "MAD/residual exceedances are not validated anomaly labels",
        "MetroPT results are conditional on complete resampled windows, not full-stream coverage",
        "MetroPT aborted on crossed quantiles in first test batch; no real test evaluation",
        "No fusion, graph, deployment or pointwise real-anomaly evaluation executed",
    ]
    for name in ["azure", "metropt"]:
        directory = Path("artifacts/phase3") / name
        write_json(
            directory / "artifact_manifest.json",
            {
                p.relative_to(directory).as_posix(): sha256(p)
                for p in directory.rglob("*")
                if p.is_file() and p.name != "artifact_manifest.json"
            },
        )
    write_json(Path("docs/results/phase3.json"), result)
    return result


if __name__ == "__main__":
    print(finalize()["status"])
