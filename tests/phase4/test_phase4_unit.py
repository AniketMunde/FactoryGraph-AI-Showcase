"""Controlled source/temporal fixtures; these are not benchmark graph evidence."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factorygraph.data import SOURCE_REVISION
from factorygraph.io import sha256
from factorygraph.phase4.config import GraphConfig, connection, milliseconds
from factorygraph.phase4.features import compute_features, prefix_count
from factorygraph.phase4.queries import HISTORY, EvidenceRequest, HistoricalQueries, machine_id
from factorygraph.phase4.source import (
    EVENTS,
    event_facts,
    identity,
    read_sources,
    verify_preservation,
)
from factorygraph.phase4.study import resource_check


def test_source_ids_deterministic_and_same_timestamp_distinct(tables):
    hashes = {name: identity(name) for name in tables}
    records = event_facts(tables, hashes, [1, 2])
    assert records == event_facts(tables, hashes, [1, 2])
    assert len({r["id"] for r in records}) == len(records)
    modified = {
        **tables,
        "errors": pd.concat(
            [tables["errors"], tables["errors"].iloc[:1].assign(errorID="error2")],
            ignore_index=True,
        ),
    }
    added = event_facts(modified, hashes, [1, 2])
    assert len(added) == len(records) + 1
    assert len({r["id"] for r in added}) == len(added)
    assert all(
        r["source_row"] > 0 and r["source_record_id"] and r["source_payload_sha256"]
        for r in records
    )
    assert all("available_at" not in r and "recorded_at" not in r for r in records)


@pytest.mark.parametrize(
    "table,field", [("maint", "comp"), ("failures", "failure"), ("errors", "errorID")]
)
def test_unknown_component_or_error_rejected(tables, table, field):
    tables[table].loc[0, field] = "unknown"
    with pytest.raises(ValueError, match="Unknown"):
        event_facts(tables, {n: identity(n) for n in tables}, [1, 2])


@pytest.mark.parametrize("value", [0, -1, True, "1 OR 1=1", 1.5])
def test_machine_identity_input_not_query_text(value):
    with pytest.raises(ValueError):
        machine_id(value)


def test_cutoff_timezone_and_strict_prefix():
    with pytest.raises(ValueError):
        milliseconds("2015-01-01")
    assert prefix_count(np.array([1, 2, 3]), np.array([2, 3])).tolist() == [1, 2]
    assert prefix_count(np.array([1, 2, 3]), np.array([3]), 2).item() == 2


def test_features_exclude_future_own_and_peer_events(tables):
    machines = tables["machines"].assign(model="model1")
    facts = pd.DataFrame(event_facts(tables, {n: identity(n) for n in tables}, [1, 2]))
    cutoff = pd.Timestamp("2015-01-04T00:00Z")
    snapshots = pd.DataFrame({"machineID": [2, 1], "datetime": [cutoff, cutoff]})
    config = GraphConfig(machine_ids=[1, 2])
    first = compute_features(snapshots, machines, facts, config, "build")
    changed = facts.copy()
    changed.loc[changed.event_ms >= milliseconds(cutoff), "code"] = "comp4"
    future = changed.iloc[:1].assign(id="future", machine_id=2, event_ms=milliseconds(cutoff) + 1)
    second = compute_features(snapshots, machines, pd.concat([changed, future]), config, "build")
    pd.testing.assert_frame_equal(first, second)
    assert first.machineID.tolist() == [2, 1]
    assert (first.latest_contributing_event_timestamp < first.datetime).all()
    for row in first.itertuples():
        own = tables["failures"]
        expected = ((own.machineID == row.machineID) & (own.datetime < cutoff)).sum()
        assert row.g4_failures_records_total == expected
    with pytest.raises(ValueError, match="alignment"):
        compute_features(snapshots.assign(machineID=999), machines, facts, config, "b")


def test_no_peer_or_failure_missing_semantics(tables):
    config = GraphConfig(machine_ids=[1, 2])
    facts = pd.DataFrame(event_facts(tables, {n: identity(n) for n in tables}, [1, 2]))
    cutoff = pd.Timestamp("2015-01-01T00:00Z")
    frame = compute_features(
        pd.DataFrame({"machineID": [1], "datetime": [cutoff]}),
        tables["machines"],
        facts,
        config,
        "b",
    )
    assert pd.isna(frame.g4_hours_since_last_failure.item())
    assert pd.isna(frame.g4_model_peer_failures_records_per_machine_30d.item())
    assert frame.g4_error1_fraction_30d.item() == 0
    assert frame.g4_maint_records_total.item() == 0  # simultaneous maintenance excluded


def test_cypher_values_are_parameters():
    class Recorder:
        def read(self, query, **params):
            assert query == HISTORY
            assert "$cutoff" in query and "$machine" in query
            assert "2015-" not in query
            assert params["machine"] == 17
            return []

    q = HistoricalQueries(Recorder())
    assert q.history(17, "2015-10-15T00:00Z", component="comp2") == []
    with pytest.raises(ValueError):
        q.history(17, "2015-10-15T00:00Z", component="comp2'}) MATCH(n)")
    with pytest.raises(ValueError):
        q.history(17, "2015-10-15T00:00Z", limit=10001)


def test_connection_requires_secret_and_localhost(monkeypatch):
    monkeypatch.delenv("FACTORYGRAPH_NEO4J_PASSWORD", raising=False)
    monkeypatch.setenv("FACTORYGRAPH_NEO4J_URI", "bolt://127.0.0.1:17687")
    with pytest.raises(ValueError, match="environment"):
        connection()


def test_driver_connectivity_failure_closes_driver(monkeypatch):
    import sys
    from types import SimpleNamespace

    from factorygraph.phase4.database import GraphDB

    closed = []

    class FailedDriver:
        def verify_connectivity(self):
            raise ConnectionError("controlled unavailable local service")

        def close(self):
            closed.append(True)

    monkeypatch.setenv("FACTORYGRAPH_NEO4J_USER", "fixture-user")
    monkeypatch.setenv("FACTORYGRAPH_NEO4J_PASSWORD", "fixture-token")
    monkeypatch.setenv("FACTORYGRAPH_NEO4J_URI", "bolt://127.0.0.1:17687")
    monkeypatch.setitem(
        sys.modules,
        "neo4j",
        SimpleNamespace(
            GraphDatabase=SimpleNamespace(driver=lambda *args, **kwargs: FailedDriver())
        ),
    )
    with pytest.raises(ConnectionError):
        GraphDB(GraphConfig())
    assert closed == [True]
    monkeypatch.setenv("FACTORYGRAPH_NEO4J_URI", "bolt://public.example:7687")
    with pytest.raises(ValueError, match="localhost"):
        connection()


def test_resource_floor_failure(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        "factorygraph.phase4.study.psutil.virtual_memory", lambda: SimpleNamespace(available=1)
    )
    with pytest.raises(RuntimeError, match="resource"):
        resource_check()


def test_preservation_rejects_modified_historical_file(tmp_path):
    historical = tmp_path / "accepted.txt"
    historical.write_text("accepted")
    manifest = tmp_path / "protected.json"
    manifest.write_text(json.dumps({str(historical): sha256(historical)}))
    assert verify_preservation(manifest) == 1
    historical.write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        verify_preservation(manifest)


def test_ontology_event_mapping_and_evidence_schema():
    assert {v[0] for v in EVENTS.values()} == {"ErrorEvent", "MaintenanceEvent", "FailureEvent"}
    assert EVENTS["maint"][2] == "ComponentType"
    assert "ComponentInstance" not in Path("src/factorygraph/phase4/database.py").read_text()
    with pytest.raises(ValueError):
        EvidenceRequest(machine_id=0, cutoff="2015-01-01T00:00Z")
    with pytest.raises(ValueError):
        GraphConfig(namespace="other_user")


def test_raw_duplicate_protection(tmp_path, tables):
    raw = tmp_path / "raw"
    raw.mkdir()
    tables["errors"] = pd.concat([tables["errors"], tables["errors"].iloc[:1]])
    files = {}
    for name, frame in tables.items():
        target = raw / f"PdM_{name}.csv"
        frame.to_csv(target, index=False)
        files[target.name] = {"sha256": sha256(target)}
    (raw / "source_manifest.json").write_text(
        json.dumps({"revision": SOURCE_REVISION, "files": files})
    )
    with pytest.raises(ValueError, match="duplicate"):
        read_sources(GraphConfig(raw_dir=raw, machine_ids=[1, 2]))
