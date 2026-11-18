"""Separate executable stages; interrupted evidence is retained without invented results."""

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

from factorygraph.io import sha256, write_json
from factorygraph.phase3.anomaly import fit_thresholds, residual_scores, robust_observation_scores
from factorygraph.phase3.config import load_config
from factorygraph.phase3.export import build_export, save_export
from factorygraph.phase3.sources import acquire, prepare_metro
from factorygraph.phase3.study import pilot, read_sequences, register, run, smoke, verify_study


def anomalies_and_export(config) -> dict:
    verify_study(config)
    if (config.run_dir / "features_test.parquet").exists():
        raise ValueError("Export exists; refusing overwrite")
    validation = pd.read_parquet(config.run_dir / "validation_evaluation.parquet")
    test = pd.read_parquet(config.run_dir / "test_evaluation.parquet")
    statistical = robust_observation_scores(
        read_sequences(config),
        pd.Timestamp(config.validation_start),
        pd.Timestamp(config.test_end),
        config.context_length,
    )
    residuals = pd.concat(
        [
            residual_scores(
                validation, pd.Timestamp(config.test_start) - pd.Timedelta(nanoseconds=1)
            ),
            residual_scores(test, pd.Timestamp(config.test_end) - pd.Timedelta(nanoseconds=1)),
        ],
        ignore_index=True,
    )
    scores = pd.concat([statistical, residuals], ignore_index=True)
    eligible = scores.loc[scores.observation_time < pd.Timestamp(config.test_start)]
    thresholds = fit_thresholds(
        eligible, pd.Timestamp(config.validation_start), pd.Timestamp(config.test_start)
    )
    # Persist thresholds before summarizing test scores or building test features.
    write_json(config.run_dir / "anomaly_thresholds.json", thresholds)
    scores.to_parquet(config.run_dir / "anomaly_scores.parquet", index=False)
    snapshots = pd.read_parquet("artifacts/baseline/test_predictions.parquet")[
        ["machineID", "datetime"]
    ]
    export = build_export(
        snapshots, pd.concat([validation, test], ignore_index=True), scores, thresholds, config
    )
    manifest = save_export(export, config)
    output = {
        "status": "causal_features_completed",
        "score_rows": len(scores),
        "features": manifest,
        "thresholds": thresholds,
        "test_score_exceedance": {
            f"{method}:{channel}": float(
                (group.score > thresholds["thresholds"][f"{method}:{channel}"]).mean()
            )
            for (method, channel), group in scores.loc[
                scores.observation_time >= pd.Timestamp(config.test_start)
            ].groupby(["method", "channel"])
        },
        "limits": "Score exceedances are not pointwise anomaly or failure detection accuracy",
    }
    write_json(config.run_dir / "anomaly_results.json", output)
    write_json(
        config.run_dir / "anomaly_manifest.json",
        {
            p.name: sha256(p)
            for p in [
                config.run_dir / "anomaly_scores.parquet",
                config.run_dir / "anomaly_thresholds.json",
            ]
        },
    )
    verify_study(config)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="FactoryGraph Phase 3 forecasting study")
    parser.add_argument(
        "stage", choices=["acquire", "prepare-metro", "register", "smoke", "pilot", "run", "export"]
    )
    parser.add_argument("--config", type=Path, default=Path("configs/phase3/azure.yaml"))
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args()
    config = load_config(args.config)
    if args.run_dir:
        config.run_dir = args.run_dir
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        if args.stage == "acquire":
            acquire(config.model_dir)
            return
        if args.stage == "prepare-metro":
            print(json.dumps(prepare_metro(), indent=2))
            return
        functions = {
            "register": register,
            "smoke": smoke,
            "pilot": pilot,
            "run": run,
            "export": anomalies_and_export,
        }
        result = functions[args.stage](config)
        print(
            json.dumps(
                {"stage": args.stage, "status": result.get("status", "registered")}, indent=2
            )
        )
    except Exception as exc:
        config.run_dir.mkdir(parents=True, exist_ok=True)
        write_json(
            config.run_dir / f"{args.stage}_failure.json",
            {"status": "incomplete", "type": type(exc).__name__, "message": str(exc)},
        )
        raise


if __name__ == "__main__":
    main()
