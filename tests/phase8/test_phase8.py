"""Exact metadata/report equivalence, authorization and fault boundaries."""

import gc
import os
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from factorygraph.phase6.common import read_json
from factorygraph.phase7.api import create_app
from factorygraph.phase7.config import Settings
from factorygraph.phase7.runtime import BUILD_QUERY, Runtime, project, utc
from factorygraph.phase8.candidate import CandidateRuntime

TOKEN = "phase8-test-only-operator-" + "o" * 40
VIEWER = "phase8-test-only-viewer-" + "v" * 40
HEADERS = {"Authorization": "Bearer " + TOKEN}
GENUINE = pytest.mark.skipif(
    os.environ.get("FACTORYGRAPH_PHASE8_INTEGRATION") != "1",
    reason="Genuine local Phase 8 opt-in required",
)


def release_test_runtime(runtime):
    """Release closed fixture tables, including native Arrow buffers, between tests."""
    runtime.close()
    runtime.builder = None
    if hasattr(runtime, "_snapshot_descriptors"):
        runtime._snapshot_descriptors.clear()
    gc.collect()
    import pyarrow

    pyarrow.default_memory_pool().release_unused()


def test_metadata_returns_copies_and_exact_machine_key():
    r = CandidateRuntime.__new__(CandidateRuntime)
    r.settings = Settings()
    r._machine_descriptors = ((1, "m1"), (17, "m3"))
    r._snapshot_descriptors = {
        1: (("2015-10-01T00:00:00+00:00", "primary"),),
        17: (("2015-10-01T00:00:00+00:00", "evidence_only"),),
    }
    r.snapshots(1)[0]["eligibility"] = "tampered"
    r.machines()[0]["model"] = "tampered"
    assert r.snapshots(1)[0]["eligibility"] == "primary"
    assert r.snapshots(17)[0]["eligibility"] == "evidence_only"
    assert r.snapshots(10001) == [] and r.machines()[0]["model"] == "m1"


@GENUINE
def test_all_registered_cases_metadata_and_fleet_order_match():
    gc.collect()
    baseline = Runtime(Settings())
    candidate = CandidateRuntime(Settings())
    try:
        assert baseline.machines() == candidate.machines()
        for machine in [*range(1, 101), 10001]:
            assert baseline.snapshots(machine) == candidate.snapshots(machine)
        records = read_json("artifacts/phase6/study/case_study.json")["records"]
        for record in records:
            accepted = read_json("artifacts/phase6/study/" + record["path"])
            req = accepted["request"]
            actual = candidate.builder.build(req["machine_id"], req["snapshot"])
            assert actual == accepted
            assert project(actual) == project(
                baseline.builder.build(req["machine_id"], req["snapshot"])
            )
        assert candidate.fleet(utc("2015-10-15T00:00Z"), [42, 1, 17]) == (
            baseline.fleet(utc("2015-10-15T00:00Z"), [17, 42, 1])
        )
        assert candidate.metadata_identity
    finally:
        release_test_runtime(candidate)
        release_test_runtime(baseline)
        del candidate, baseline
        gc.collect()


@pytest.fixture
def engine():
    gc.collect()
    r = CandidateRuntime(Settings())
    yield r
    release_test_runtime(r)
    del r
    gc.collect()


def app(engine, settings=None):
    return create_app(
        settings or Settings(),
        runtime_factory=lambda _: engine,
        token_loader=lambda role: TOKEN if role == "operator" else VIEWER,
    )


@GENUINE
def test_cached_metadata_never_bypasses_authorization_or_graph_readiness(engine, monkeypatch):
    with TestClient(app(engine)) as c:
        viewer = {"Authorization": "Bearer " + VIEWER}
        assert c.get("/api/v1/machines", headers=viewer).json()["items"] == [
            next(m for m in engine.machines() if m["machine_id"] == 17)
        ]
        assert c.get("/api/v1/snapshots?machine_id=1", headers=viewer).status_code == 403
        assert c.get("/api/v1/snapshots?machine_id=17", headers=viewer).status_code == 200
        original = engine.db.read
        monkeypatch.setattr(
            engine.db, "read", lambda q, **p: [] if q == BUILD_QUERY else original(q, **p)
        )
        assert c.get("/api/v1/health/ready", headers=HEADERS).status_code == 503
        assert (
            c.get(
                "/api/v1/cases/17", headers=HEADERS, params={"snapshot_time": "2015-10-15T00:00Z"}
            ).status_code
            == 503
        )


@GENUINE
def test_source_validation_and_future_fact_faults_remain_active(engine):
    before = engine.case(17, utc("2015-10-15T00:00Z"))
    fact = before["historical_evidence"]["facts"][0]
    source = engine.builder.catalog.by_id[fact["id"]]
    old = source["source_row"]
    source["source_row"] = -1
    try:
        damaged = engine.case(17, utc("2015-10-15T00:00Z"))
        assert damaged["status"] == "degraded"
        assert damaged["historical_evidence"]["status"] == "unavailable"
    finally:
        source["source_row"] = old
    assert engine.case(17, utc("2015-10-15T00:00Z")) == before
    from factorygraph.phase6.evidence import EvidenceValidator

    with pytest.raises(ValueError, match="future"):
        EvidenceValidator(engine.builder.catalog).facts([fact], utc(fact["event_timestamp"]))
    with pytest.raises(PermissionError):
        engine.db.write("CREATE ()")
    with pytest.raises(ValueError):
        engine.db.read("MATCH (n) DETACH DELETE n")


@GENUINE
def test_temporal_fault_not_hidden_by_metadata_index(engine):
    t = utc("2015-10-15T00:00Z")
    context = engine.builder.temporal.context
    original = context.loc[(17, t), "forecast_issue_timestamp"]
    context.loc[(17, t), "forecast_issue_timestamp"] = t + __import__("pandas").Timedelta(hours=1)
    try:
        report = engine.case(17, t)
        assert report["status"] == "degraded"
        assert report["temporal_context"]["status"] == "unavailable"
    finally:
        context.loc[(17, t), "forecast_issue_timestamp"] = original


@GENUINE
def test_timeout_keeps_slot_and_lifespan_closes(engine, monkeypatch):
    closed = []
    original_close = engine.close

    def close():
        closed.append(True)
        original_close()

    monkeypatch.setattr(engine, "close", close)
    original = engine.case

    def slow(*args):
        time.sleep(0.15)
        return original(*args)

    monkeypatch.setattr(engine, "case", slow)
    with TestClient(app(engine, Settings(case_deadline_seconds=0.02))) as c:
        params = {"snapshot_time": "2015-10-15T00:00Z"}
        assert c.get("/api/v1/cases/17", params=params, headers=HEADERS).status_code == 504
        assert c.get("/api/v1/cases/17", params=params, headers=HEADERS).status_code == 503
    assert closed == [True]


@GENUINE
def test_gallery_remains_distinct_and_uses_no_metadata_indexes():
    baseline = Runtime(Settings(mode="gallery"))
    candidate = CandidateRuntime(Settings(mode="gallery"))
    try:
        assert candidate.machines() == baseline.machines()
        assert not hasattr(candidate, "_snapshot_descriptors")
        for m in [1, 17, 10001]:
            assert candidate.snapshots(m) == baseline.snapshots(m)
        assert candidate.case(10001, utc("2015-10-15T00:00Z")) == baseline.case(
            10001, utc("2015-10-15T00:00Z")
        )
    finally:
        baseline.close()
        candidate.close()


@GENUINE
def test_concurrent_work_remains_bounded(engine, monkeypatch):
    import threading

    barrier = threading.Barrier(3)
    original = engine.case

    def slow(*args):
        time.sleep(0.1)
        return original(*args)

    monkeypatch.setattr(engine, "case", slow)
    with TestClient(app(engine)) as c:

        def request(_):
            barrier.wait()
            return c.get(
                "/api/v1/cases/17", params={"snapshot_time": "2015-10-15T00:00Z"}, headers=HEADERS
            ).status_code

        with ThreadPoolExecutor(max_workers=3) as pool:
            assert sorted(pool.map(request, range(3))) == [200, 503, 503]


@GENUINE
def test_resource_admission_failure_closes_graph(monkeypatch):
    from factorygraph.phase7.runtime import ReadOnlyGraph
    from factorygraph.phase8 import candidate

    closed = []
    original = ReadOnlyGraph.close

    def close(self):
        closed.append(True)
        return original(self)

    def exhausted(*args):
        raise MemoryError("injected memory budget")

    monkeypatch.setattr(ReadOnlyGraph, "close", close)
    monkeypatch.setattr(candidate, "budget", exhausted)
    with pytest.raises(MemoryError):
        CandidateRuntime(Settings())
    assert closed
