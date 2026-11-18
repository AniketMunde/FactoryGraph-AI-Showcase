"""Verified local accepted artifacts; skipped explicitly when data are not installed."""

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factorygraph.phase6.common import load_config as phase6_config
from factorygraph.phase6.integrity import ArtifactRegistry
from factorygraph.phase6.prediction import PolicyEvaluator, PredictionReader
from factorygraph.phase6.temporal import TemporalContextReader

RUN_DIR = Path(os.environ.get("FACTORYGRAPH_PHASE6_RUN_DIR", "artifacts/phase6/study"))


def load_config():
    return phase6_config(run_dir=RUN_DIR)


pytestmark = pytest.mark.skipif(
    not (RUN_DIR / "registration.json").exists(),
    reason="Accepted local artifacts and registered Phase 6 run required",
)


@pytest.fixture(scope="module")
def readers():
    registry = ArtifactRegistry(load_config())
    prediction = PredictionReader(registry)
    return prediction, PolicyEvaluator(prediction), TemporalContextReader(registry)


def test_exact_A0_identity_and_all_policy_rows(readers):
    prediction, policy, _context = readers
    assert prediction.error is None
    accepted = pd.read_parquet(
        "artifacts/baseline/test_predictions.parquet",
        columns=["machineID", "datetime", "probability"],
    )
    assert accepted.equals(prediction.frame)
    last = {}
    expected = {}
    for r in accepted.sort_values(["machineID", "datetime"]).itertuples():
        high = r.probability >= prediction.policy["threshold"]
        previous = last.get(r.machineID)
        new = high and (previous is None or r.datetime - previous >= pd.Timedelta(hours=24))
        if new:
            last[r.machineID] = r.datetime
        expected[r.machineID, r.datetime] = (bool(high), bool(new), bool(high and not new))
    assert len(expected) == 72633
    assert sum(v[1] for v in expected.values()) == 141
    assert all(
        (v["above_threshold"], v["new_alert"], v["cooldown_suppressed"]) == expected[k]
        for k, v in policy.rows.items()
    )


def test_unsupported_timestamp_does_not_choose_future_prediction(readers):
    prediction, policy, _ = readers
    out = prediction.get(17, pd.Timestamp("2015-10-15T00:01Z"))
    assert out.status == "unavailable" and out.probability is None
    assert policy.get(out).status == "unavailable"


def test_exact_context_values_and_historical_missingness(readers):
    _, _, context = readers
    assert context.error is None
    early = context.get(1, pd.Timestamp("2015-01-08T00:00Z"))
    assert early["status"] == "incomplete"
    vals = early["supplementary_chronos_context"]["values"]
    assert vals["p5_c_forecast_available"] == 0 and vals["p5_c_volt_forecast_mean"] is None
    assert vals["p5_c_volt_residual_valid_count_24h"] == 0
    out = context.get(17, pd.Timestamp("2015-10-15T00:00Z"))
    assert out["status"] == "verified"
    saved = context.context.loc[(17, pd.Timestamp("2015-10-15T00:00Z"))]
    assert np.array_equal(
        list(out["supplementary_chronos_context"]["values"].values()),
        saved[context.temporal_columns].to_numpy(dtype=float),
    )
    assert context.get(17, pd.Timestamp("2015-10-15T00:01Z"))["status"] == "unavailable"


@pytest.mark.parametrize("component", ["calibration.json", "policy.json", "artifact_manifest.json"])
def test_invalid_accepted_identity_never_exposes_risk(monkeypatch, component):
    import factorygraph.phase6.prediction as module

    original = module.read_json

    def conflicting(path):
        value = original(path)
        if Path(path).as_posix() == f"artifacts/baseline/{component}":
            value = dict(value)
            if component == "calibration.json":
                value["slope"] += 1
            elif component == "policy.json":
                value["cooldown_hours"] = 1
            else:
                value["model.txt"] = "0" * 64
        return value

    monkeypatch.setattr(module, "read_json", conflicting)
    reader = PredictionReader(ArtifactRegistry(load_config()))
    out = reader.get(17, pd.Timestamp("2015-10-15T00:00Z"))
    assert reader.error and out.status == "unavailable" and out.probability is None


def test_corrupt_temporal_artifact_and_source_hash_are_explicit(monkeypatch):
    from factorygraph.phase6.evidence import SourceCatalog

    registry = ArtifactRegistry(load_config())
    original = registry.require

    def corrupt(path):
        if str(path).endswith("temporal_c_train.parquet") or str(path).endswith("PdM_errors.csv"):
            raise ValueError("injected registered file hash mismatch")
        return original(path)

    monkeypatch.setattr(registry, "require", corrupt)
    context = TemporalContextReader(registry)
    assert context.error
    assert context.get(17, pd.Timestamp("2015-10-15T00:00Z"))["status"] == "unavailable"
    catalog = SourceCatalog(registry)
    assert catalog.error == "source_integrity_unavailable"
