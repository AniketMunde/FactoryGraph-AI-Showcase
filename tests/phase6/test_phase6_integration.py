"""Genuine Neo4j acceptance: separate fixture namespace plus accepted read-only service."""

import json
import os
import uuid

import pandas as pd
import pytest

from factorygraph.data import SOURCE_REVISION
from factorygraph.io import sha256
from factorygraph.phase4.config import GraphConfig, milliseconds
from factorygraph.phase4.database import GraphDB, import_graph
from factorygraph.phase4.queries import EvidenceRequest, HistoricalQueries
from factorygraph.phase4.source import event_facts, read_sources
from factorygraph.phase6.common import digest
from factorygraph.phase6.common import load_config as phase6_config
from factorygraph.phase6.evidence import EvidenceValidator, SourceCatalog
from factorygraph.phase6.schema import CaseReport
from factorygraph.phase6.service import CaseReportBuilder

pytestmark = pytest.mark.skipif(
    os.environ.get("FACTORYGRAPH_NEO4J_INTEGRATION") != "1",
    reason="Explicit genuine local Neo4j integration opt-in required",
)


def load_config():
    return phase6_config(run_dir=os.environ.get("FACTORYGRAPH_PHASE6_RUN_DIR"))


def test_genuine_fixture_boundary_overlap_peer_provenance(tmp_path, tables):
    pytest.importorskip("neo4j")
    raw, processed = tmp_path / "raw", tmp_path / "processed"
    raw.mkdir()
    processed.mkdir()
    tables["machines"]["model"] = "model1"
    # A separate maintenance fact sharing an existing failure key.
    failure = tables["failures"].iloc[0]
    tables["maint"] = pd.concat(
        [
            tables["maint"],
            pd.DataFrame(
                {
                    "machineID": [failure.machineID],
                    "datetime": [failure.datetime],
                    "comp": [failure.failure],
                }
            ),
        ],
        ignore_index=True,
    )
    hashes = {}
    for name, frame in tables.items():
        p = raw / f"PdM_{name}.csv"
        frame.to_csv(p, index=False)
        hashes[p.name] = {"sha256": sha256(p)}
    (raw / "source_manifest.json").write_text(
        json.dumps({"revision": SOURCE_REVISION, "files": hashes})
    )
    tables["telemetry"].to_parquet(processed / "telemetry.parquet", index=False)
    config = GraphConfig(
        namespace="fg_phase4_test_p6_" + uuid.uuid4().hex,
        raw_dir=raw,
        processed_dir=processed,
        run_dir=tmp_path,
        machine_ids=[1, 2],
    )
    db = GraphDB(config)
    try:
        import_graph(db, config)
        cat = SourceCatalog.__new__(SourceCatalog)
        cat.tables, cat.hashes = read_sources(config)
        cat.facts = event_facts(cat.tables, cat.hashes, [1, 2])
        cat.by_id = {r["id"]: r for r in cat.facts}
        cat.machines = cat.tables["machines"].set_index("machineID")
        q = HistoricalQueries(db)
        cutoff = pd.Timestamp("2015-01-02T03:00Z")
        start = cutoff - pd.Timedelta(days=30)

        def bundle():
            n = q.neighborhood(EvidenceRequest(machine_id=1, cutoff=cutoff.to_pydatetime()))
            retrieved = {
                "machine": n["machine"],
                "facts": q.history(1, cutoff, start=start),
                "lifetime_counts": q.counts(1, cutoff, pd.Timestamp("1900-01-01T00:00Z")),
                "window_counts": q.counts(1, cutoff, start),
                "peers": q.peers(1),
                "peer_counts": q.peer_counts(1, cutoff, start),
            }
            return EvidenceValidator(cat).bundle(1, cutoff, start, 1000, retrieved)

        before = bundle()
        overlap = [r for r in before["facts"] if r["event_ms"] == milliseconds(failure.datetime)]
        assert {r["kind"] for r in overlap} == {"failures", "maint"}
        assert len({r["id"] for r in overlap}) == 2
        db.write(
            (
                "MATCH (m:Machine {namespace:$namespace,id:'2'}) CREATE "
                "(e:RecordedEvent:FailureEvent {namespace:$namespace,id:'cutoff-"
                "peer',machine_id:2,kind:'failures',code:'comp1',event_ms:$time}) "
                "CREATE (m)-[:HAS_FAILURE_EVENT]->(e)"
            ),
            time=milliseconds(cutoff),
        )
        assert bundle() == before  # Exact-cutoff peer event is hidden, including aggregates.
        assert all(r["event_ms"] < milliseconds(cutoff) for r in before["facts"])
    finally:
        # The explicitly generated disposable test namespace only; never accepted graph.
        db.write("MATCH(n {namespace:$namespace}) DETACH DELETE n")
        db.close()


def test_genuine_accepted_service_determinism_parity_and_faults(monkeypatch):
    pytest.importorskip("neo4j")
    with CaseReportBuilder(load_config()) as service:
        assert service.predictions.error is None and service.evidence.error is None
        first = service.build(17, "2015-10-15T00:00Z")
        assert first["status"] == "complete"
        assert digest(first) == digest(service.build(17, "2015-10-15T00:00Z"))
        assert CaseReport.model_validate_json(json.dumps(first)).model_dump(mode="json") == first
        assert (
            first["prediction"]["probability"]
            == service.predictions.index.loc[(17, pd.Timestamp("2015-10-15T00:00Z")), "probability"]
        )
        unknown = service.build(10001, "2015-10-15T00:00Z")
        assert unknown["status"] == "abstained"
        early = service.build(1, "2015-01-08T00:00Z")
        assert early["status"] == "evidence_only"
        assert early["temporal_context"]["status"] == "incomplete"
        with pytest.raises(ValueError):
            service.build(17, "2015-10-15")
        with pytest.raises(ValueError):
            service.fleet("2015-10-15T00:01Z")

        def unavailable(*_args, **_kwargs):
            raise ConnectionError("injected offline database fault")

        monkeypatch.setattr(service.evidence.db, "read", unavailable)
        failed = service.build(17, "2015-10-15T00:00Z")
        assert failed["status"] == "degraded"
        assert failed["historical_evidence"]["status"] == "unavailable"
        assert "facts" not in failed["historical_evidence"]
        assert not ({"R003", "R004", "R005"} & set(failed["provenance"]["recommendation_rule_ids"]))
        assert "R007" in failed["provenance"]["recommendation_rule_ids"]
