"""Real Neo4j tests; opt in explicitly, with a fresh scoped fixture namespace."""

import json
import os
import uuid

import pandas as pd
import pytest

from factorygraph.data import SOURCE_REVISION
from factorygraph.io import sha256
from factorygraph.phase4.config import GraphConfig, milliseconds
from factorygraph.phase4.database import GraphDB, import_graph
from factorygraph.phase4.maintenance import backup, reset, restore
from factorygraph.phase4.queries import EvidenceRequest, HistoricalQueries

pytestmark = pytest.mark.skipif(
    os.environ.get("FACTORYGRAPH_NEO4J_INTEGRATION") != "1",
    reason="Explicit genuine local Neo4j integration opt-in required",
)


@pytest.fixture(scope="function")
def graph(tmp_path, tables):
    pytest.importorskip("neo4j")
    raw = tmp_path / "raw"
    raw.mkdir()
    processed = tmp_path / "processed"
    processed.mkdir()
    tables["machines"]["model"] = "model1"
    first_failure = tables["failures"].iloc[0]
    tables["maint"] = pd.concat(
        [
            tables["maint"],
            pd.DataFrame(
                {
                    "datetime": [first_failure.datetime],
                    "machineID": [first_failure.machineID],
                    "comp": [first_failure.failure],
                }
            ),
        ],
        ignore_index=True,
    )
    files = {}
    for name, frame in tables.items():
        path = raw / f"PdM_{name}.csv"
        frame.to_csv(path, index=False)
        files[path.name] = {"sha256": sha256(path)}
    (raw / "source_manifest.json").write_text(
        json.dumps({"revision": SOURCE_REVISION, "files": files})
    )
    tables["telemetry"].to_parquet(processed / "telemetry.parquet", index=False)
    config = GraphConfig(
        namespace="fg_phase4_test_" + uuid.uuid4().hex,
        raw_dir=raw,
        processed_dir=processed,
        run_dir=tmp_path,
        machine_ids=[1, 2],
    )
    db = GraphDB(config)
    try:
        result = import_graph(db, config)
        yield db, config, result
    finally:
        # Only this generated fixture namespace; never clear another graph/database.
        db.write("MATCH (n {namespace:$namespace}) DETACH DELETE n")
        db.close()


def test_genuine_import_idempotency_and_source_reconciliation(graph):
    db, config, first = graph
    second = import_graph(db, config)
    assert first["signature"] == second["signature"]
    assert first["counts"] == second["counts"]
    assert first["source_rows_reconciled"]
    assert (
        db.read("CALL dbms.components() YIELD edition RETURN edition")[0]["edition"] == "community"
    )


def test_genuine_cutoff_boundary_future_events_and_peer_context(graph):
    db, _config, _result = graph
    queries = HistoricalQueries(db)
    cutoff = pd.Timestamp("2015-01-01T03:00Z")
    events = queries.history(1, cutoff)
    assert all(r["event_ms"] < milliseconds(cutoff) for r in events)
    assert len(events) == 2  # maintenance at00, error at01; both03 events excluded
    assert queries.history(1, cutoff, kinds=["maint"], component="comp1")[0]["code"] == "comp1"
    before = queries.counts(1, cutoff, cutoff - pd.Timedelta(days=1))
    db.write(
        "MATCH (m:Machine {namespace:$namespace,id:'1'}) "
        "CREATE (e:RecordedEvent:FailureEvent {namespace:$namespace,id:'future-injected',"
        "machine_id:1,kind:'failures',code:'comp1',event_ms:$future}) "
        "CREATE (m)-[:HAS_FAILURE_EVENT]->(e)",
        future=milliseconds(cutoff) + 1,
    )
    assert queries.counts(1, cutoff, cutoff - pd.Timedelta(days=1)) == before
    assert queries.history(1, cutoff) == events
    assert queries.peers(1) == [{"machine_id": 2, "model": "model1"}]
    peer = queries.peer_counts(1, cutoff, cutoff - pd.Timedelta(days=1))[0]
    assert peer["failure_records"] == 0
    db.write(
        "MATCH (m:Machine {namespace:$namespace,id:'2'}) "
        "CREATE (e:RecordedEvent:FailureEvent {namespace:$namespace,id:'peer-future',"
        "machine_id:2,kind:'failures',code:'comp1',event_ms:$future}) "
        "CREATE (m)-[:HAS_FAILURE_EVENT]->(e)",
        future=milliseconds(cutoff),
    )
    assert queries.peer_counts(1, cutoff, cutoff - pd.Timedelta(days=1))[0] == peer
    evidence = queries.neighborhood(
        EvidenceRequest(machine_id=1, cutoff=cutoff.to_pydatetime(), limit=1)
    )
    assert len(evidence["observed_source_records"]) == 1
    assert not evidence["catalog_artifacts_in_historical_context"]
    assert queries.history(1, cutoff, limit=1, offset=1) == events[1:2]


def test_genuine_overlap_provenance_and_changed_build_rejection(graph):
    db, config, _result = graph
    own = HistoricalQueries(db).history(1, pd.Timestamp("2015-01-20T00:00Z"))
    assert all("source_record_id" in r and "ingested_at" in r for r in own)
    overlap = db.read(
        "MATCH (f:FailureEvent {namespace:$namespace})-[:MATCHES_RECORDED_KEY]->"
        "(m:MaintenanceEvent {namespace:$namespace}) "
        "RETURN f.id AS failure,m.id AS maintenance,f.event_ms=m.event_ms AS equal_time"
    )
    assert len(overlap) == 1
    assert overlap[0]["failure"] != overlap[0]["maintenance"]
    assert overlap[0]["equal_time"]
    bad = config.model_copy(update={"batch_size": 1})
    with pytest.raises(ValueError, match="different registered build"):
        import_graph(db, bad)
    assert (
        db.read("MATCH (n {namespace:$namespace}) WHERE n:ComponentType RETURN count(n) AS n")[0][
            "n"
        ]
        == 4
    )


def test_genuine_scoped_backup_restore_and_reset(graph, tmp_path):
    db, config, first = graph
    path = tmp_path / "backup.json"
    saved = backup(db, path)
    copy_config = config.model_copy(update={"namespace": "fg_phase4_test_" + uuid.uuid4().hex})
    copy = GraphDB(copy_config)
    try:
        with pytest.raises(ValueError, match="checksum"):
            restore(copy, path, "0" * 64)
        restored = restore(copy, path, saved["sha256"])
        assert restored["counts"] == first["counts"]
        with pytest.raises(ValueError, match="exact owned"):
            reset(copy, "wrong")
        reset(copy, first["build_hash"])
        assert copy.counts()["total_nodes"] == 0
        assert db.signature() == first["signature"]
    finally:
        copy.write("MATCH(n {namespace:$namespace}) DETACH DELETE n")
        copy.close()
