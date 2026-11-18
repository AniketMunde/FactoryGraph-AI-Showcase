import json

import numpy as np
import pandas as pd
import pytest

from factorygraph.config import ExperimentConfig, FeatureConfig, ModelConfig, SplitConfig
from factorygraph.data import prepare
from factorygraph.inference import Predictor
from factorygraph.io import verify_artifacts
from factorygraph.training import create_snapshots, evaluate_run, train, verified_snapshots


def test_full_pipeline_artifacts_and_independent_inference(tables, tmp_path):
    config = ExperimentConfig(
        raw_dir=tmp_path / "raw",
        processed_dir=tmp_path / "processed",
        run_dir=tmp_path / "run",
        features=FeatureConfig(windows_hours=[3, 24], snapshot_hours=3),
        split=SplitConfig(
            start="2015-01-02T00:00Z",
            train_end="2015-01-06T00:00Z",
            calibration_end="2015-01-09T00:00Z",
            validation_end="2015-01-12T00:00Z",
            test_end="2015-01-17T00:00Z",
        ),
        model=ModelConfig(n_estimators=5, min_child_samples=2, n_jobs=1),
        alert_budget_fraction=0.2,
    )
    config.raw_dir.mkdir()
    for name, frame in tables.items():
        frame.to_csv(config.raw_dir / f"PdM_{name}.csv", index=False)
    clean = prepare(config.raw_dir, config.processed_dir)
    features = create_snapshots(config, clean)
    metrics = train(config)
    assert metrics == evaluate_run(config.run_dir)
    assert (config.run_dir / "artifact_manifest.json").exists()
    contract = json.loads((config.run_dir / "feature_contract.json").read_text())
    test_predictions = pd.read_parquet(config.run_dir / "test_predictions.parquet")
    joined = test_predictions.merge(features, on=["machineID", "datetime"], suffixes=("", "_f"))
    result = Predictor(config.run_dir).predict(joined[contract["columns"]])
    np.testing.assert_allclose(result, joined.probability.to_numpy(), atol=1e-12)
    with pytest.raises(ValueError, match="nonempty"):
        train(config)
    # Prepared feature artifacts cannot silently change between preparation and training.
    features.loc[0, "age"] = 999
    features.to_parquet(config.processed_dir / "snapshots.parquet", index=False)
    with pytest.raises(ValueError, match="changed"):
        verified_snapshots(config)
    (config.run_dir / "calibration.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="artifact changed"):
        verify_artifacts(config.run_dir)
