"""Independent software fixtures; no mock value is a reported model benchmark."""

from copy import deepcopy
from types import SimpleNamespace

import pandas as pd
import pytest
from pydantic import ValidationError

from factorygraph.io import sha256, write_json
from factorygraph.phase4.source import event_facts
from factorygraph.phase6.common import Config, digest
from factorygraph.phase6.evidence import (
    EvidenceValidator,
    HistoricalEvidenceRetriever,
    SourceCatalog,
)
from factorygraph.phase6.integrity import ArtifactRegistry
from factorygraph.phase6.prediction import PolicyEvaluator, PredictionReader
from factorygraph.phase6.rules import DecisionRuleEngine, RecommendationFormatter
from factorygraph.phase6.schema import AlertPolicy, CaseReport, Prediction
from factorygraph.phase6.temporal import CLOCKS, POLICY_HASH, REVISION, validate_temporal


@pytest.fixture
def catalog(tables):
    tables["machines"]["model"] = "model1"
    cat = SourceCatalog.__new__(SourceCatalog)
    cat.tables = tables
    cat.hashes = {name: digest(name) for name in tables}
    cat.facts = event_facts(tables, cat.hashes, [1, 2])
    cat.by_id = {f["id"]: f for f in cat.facts}
    cat.machines = tables["machines"].set_index("machineID")
    cat.error = None
    return cat


def test_cooldown_exact_boundary_and_distinct_row_status():
    times = pd.date_range("2015-10-01T00:00Z", periods=10, freq="3h")
    frame = pd.DataFrame({"machineID": 1, "datetime": times, "probability": 0.9})
    rows = PolicyEvaluator.evaluate_rows(frame, 0.9)
    assert rows[1, times[0]]["new_alert"]
    assert rows[1, times[7]]["cooldown_suppressed"]
    assert rows[1, times[8]]["new_alert"]
    assert not rows[1, times[8]]["cooldown_suppressed"]


def test_policy_future_perturbation_and_machine_isolation():
    times = pd.date_range("2015-10-01T00:00Z", periods=20, freq="3h")
    frame = pd.DataFrame({"machineID": 1, "datetime": times, "probability": 0.9})
    a = PolicyEvaluator.evaluate_rows(frame, 0.5)
    changed = frame.copy()
    changed.loc[changed.datetime > times[8], "probability"] = 0
    b = PolicyEvaluator.evaluate_rows(changed, 0.5)
    assert all(a[k] == b[k] for k in a if k[1] <= times[8])
    both = pd.concat([frame, frame.assign(machineID=2)], ignore_index=True)
    c = PolicyEvaluator.evaluate_rows(both, 0.5)
    assert c[1, times[0]] == c[2, times[0]]


def test_boundary_and_future_peer_exclusion(catalog):
    cutoff = pd.Timestamp("2015-01-01T03:00Z")
    own = catalog.visible(1, cutoff)
    assert len(own) == 2
    assert catalog.visible(1, cutoff, peer=True) == []
    after = catalog.visible(1, cutoff + pd.Timedelta(hours=2), peer=True)
    assert len(after) == 1 and after[0]["machine_id"] == 2


@pytest.mark.parametrize(
    "fault", ["future", "clock", "hash", "provenance", "identity", "duplicate"]
)
def test_invalid_evidence_rejected(catalog, fault):
    cutoff = pd.Timestamp("2015-01-01T03:00Z")
    fact = deepcopy(catalog.visible(1, cutoff)[0])
    values = [fact]
    if fault == "future":
        cutoff = pd.Timestamp(fact["event_timestamp"])
    elif fault == "clock":
        fact["event_timestamp"] = "2014-01-01T00:00Z"
    elif fault == "hash":
        fact["source_sha256"] = "0" * 64
    elif fault == "provenance":
        del fact["source_record_id"]
    elif fault == "identity":
        fact["machine_id"] = 2
    else:
        values.append(fact)
    with pytest.raises((ValueError, ValidationError)):
        EvidenceValidator(catalog).facts(values, cutoff)


def test_database_failure_is_not_empty_history():
    retriever = HistoricalEvidenceRetriever.__new__(HistoricalEvidenceRetriever)
    retriever.error = "neo4j_connection_or_build_unavailable"
    out = retriever.get(1, pd.Timestamp("2015-10-01T00:00Z"))
    assert out["status"] == "unavailable" and "facts" not in out
    assert out["fallback"] == "disabled"


def test_artifact_hash_and_missing_provenance_fail_closed(tmp_path):
    c = Config(run_dir=tmp_path)
    p = tmp_path / "input.txt"
    p.write_text("original")
    record = {
        "config": c.model_dump(mode="json"),
        "policies_sha256": {},
        "inputs_sha256": {p.as_posix(): sha256(p)},
    }
    write_json(tmp_path / "registration.json", record)
    r = ArtifactRegistry(c)
    assert r.require(p) == sha256(p)
    p.write_text("corrupt")
    with pytest.raises(ValueError, match="hash mismatch"):
        ArtifactRegistry(c).require(p)
    with pytest.raises(ValueError, match="provenance"):
        r.require(tmp_path / "unknown")


def test_corrupt_prediction_abstains():
    class BrokenRegistry:
        def require(self, _path):
            raise ValueError("corrupt manifest")

    reader = PredictionReader(BrokenRegistry())
    p = reader.get(17, pd.Timestamp("2015-10-01T00:00Z"))
    assert p.status == "unavailable" and p.probability is None
    assert PolicyEvaluator(reader).get(p).status == "unavailable"


def test_unknown_rules_and_fallback_rejected():
    for values in [{"rule_version": "2"}, {"rule_ids": ["diagnose"]}, {"fallback": "invented"}]:
        with pytest.raises(ValueError, match="Unrecognized"):
            Config(**values).check()


def temporal_row():
    return {
        "forecast_issue_timestamp": pd.Timestamp("2015-10-01T00:00Z"),
        "latest_source_observation_timestamp": pd.Timestamp("2015-10-01T02:00Z"),
        "latest_residual_observation_timestamp": pd.Timestamp("2015-10-01T02:00Z"),
        "p5_c_forecast_available": 1,
        "model_id": "amazon/chronos-2",
        "checkpoint_revision": REVISION,
        "temporal_policy_sha256": POLICY_HASH,
    }


@pytest.mark.parametrize("clock", CLOCKS)
def test_forecast_and_residual_future_access(clock):
    row = temporal_row()
    cutoff = pd.Timestamp("2015-10-01T03:00Z")
    validate_temporal(row, cutoff)
    row[clock] = cutoff + pd.Timedelta(hours=24) if clock == "forecast_issue_timestamp" else cutoff
    with pytest.raises(ValueError, match="Future"):
        validate_temporal(row, cutoff)


def test_missing_temporal_history_remains_explicit():
    row = temporal_row()
    row.update({c: pd.NaT for c in CLOCKS})
    row["p5_c_forecast_available"] = 0
    validate_temporal(row, pd.Timestamp("2015-01-08T00:00Z"))
    row["p5_c_forecast_available"] = 1
    with pytest.raises(ValueError, match="availability"):
        validate_temporal(row, pd.Timestamp("2015-01-08T00:00Z"))


def test_rule_abstention_and_no_unsupported_diagnosis():
    engine = DecisionRuleEngine(Config())
    p = Prediction(status="unavailable", reason="unsupported")
    policy = AlertPolicy(status="unavailable")
    recs = engine.apply(
        p,
        policy,
        {"status": "unavailable"},
        {"status": "unavailable"},
        "availability:1",
        "2015-10-01T00:00Z",
    )
    assert [r.rule_id for r in recs] == ["R007"]
    assert all(r.human_review_required for r in recs)
    forbidden = [
        "definitely failing",
        "caused this failure",
        "replace this component",
        "exactly 21 hours",
        "proves the root cause",
    ]
    assert not any(s in r.text.lower() for s in forbidden for r in recs)
    recs[0].text = "Replace this component immediately."
    with pytest.raises(ValueError, match="grounding"):
        engine.validate(
            recs,
            p,
            policy,
            {"status": "unavailable"},
            {"status": "unavailable"},
            "availability:1",
            "2015-10-01T00:00Z",
        )


def test_rule_trigger_grounding_and_human_review():
    p = SimpleNamespace(status="verified", record_id="prediction:1")
    policy = SimpleNamespace(
        status="verified", record_id="policy:1", new_alert=True, cooldown_suppressed=False
    )
    e = {"status": "verified", "facts": [{"kind": "errors", "id": "source:1"}]}
    t = {"status": "verified", "approved_predictor_inputs": {"record_id": "feature:1"}}
    out = DecisionRuleEngine(Config()).apply(p, policy, e, t, "availability:1", "2015-10-01T00:00Z")
    assert [r.rule_id for r in out] == ["R001", "R003", "R006"]
    assert out[1].supporting_evidence_ids == ["source:1"]
    with pytest.raises(ValidationError):
        out[0].model_validate({**out[0].model_dump(), "human_review_required": False})


def minimal_case():
    return {
        "case_id": "case:1",
        "request": {"machine_id": 1, "snapshot": "2015-10-01T00:00Z"},
        "status": "abstained",
        "prediction": {"status": "unavailable"},
        "alert_policy": {"status": "unavailable"},
        "historical_evidence": {"status": "unavailable"},
        "temporal_context": {"status": "unavailable"},
        "recommendations": [],
        "human_review_priority": "data_verification",
        "explanation": [],
        "data_availability": {},
        "provenance": {},
        "limitations": [],
    }


def test_schema_serialization_determinism_and_no_future_labels():
    out = CaseReport.model_validate(minimal_case())
    assert CaseReport.model_validate_json(out.model_dump_json()) == out
    assert digest(out.model_dump()) == digest(out.model_dump())
    changed = minimal_case()
    changed["temporal_context"]["values"] = {"next_failure": "future"}
    with pytest.raises(ValidationError, match="Future evaluator"):
        CaseReport.model_validate(changed)


def test_verified_prediction_requires_full_identity():
    with pytest.raises(ValidationError, match="full identity"):
        Prediction(status="verified", probability=0.8)
    with pytest.raises(ValidationError, match="Unverified"):
        Prediction(status="unavailable", probability=0.8)


def test_formatter_fixed_template_reproducibility():
    a = RecommendationFormatter.make("R004", ["source:maintenance"], "2015-10-01T00:00Z")
    b = RecommendationFormatter.make("R004", ["source:maintenance"], "2015-10-01T00:00Z")
    assert a == b and a.basis == "source_backed" and a.action_type == "human_review"
