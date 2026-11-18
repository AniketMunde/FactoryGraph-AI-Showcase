"""Read-only graph retrieval, independently checked source facts and strict cutoffs."""

import time
from pathlib import Path

import pandas as pd

from factorygraph.phase4.config import load_config, milliseconds
from factorygraph.phase4.database import GraphDB
from factorygraph.phase4.queries import EvidenceRequest, HistoricalQueries
from factorygraph.phase4.source import EventFact, event_facts, read_sources
from factorygraph.phase6.common import digest, iso, read_json


class SourceCatalog:
    def __init__(self, registry):
        self.error = None
        try:
            registry.require("configs/phase4/full.yaml")
            self.config = load_config(Path("configs/phase4/full.yaml"))
            for name in ["machines", "telemetry", "errors", "maint", "failures"]:
                registry.require(self.config.raw_dir / f"PdM_{name}.csv")
            registry.require(self.config.raw_dir / "source_manifest.json")
            self.tables, self.hashes = read_sources(self.config)
            self.facts = event_facts(self.tables, self.hashes, self.config.machine_ids)
            self.by_id = {r["id"]: r for r in self.facts}
            self.machines = self.tables["machines"].set_index("machineID")
        except (OSError, ValueError, KeyError, TypeError):
            self.error = "source_integrity_unavailable"

    def visible(self, machine, cutoff, start=None, peer=False):
        model = self.machines.loc[machine, "model"]
        members = (
            set(self.machines.index[self.machines.model == model]) - {machine}
            if peer
            else {machine}
        )
        return [
            r
            for r in self.facts
            if r["machine_id"] in members
            and r["event_ms"] < milliseconds(cutoff)
            and (start is None or r["event_ms"] >= milliseconds(start))
        ]


def counts(facts):
    result = {}
    for r in facts:
        key = (r["kind"], r["code"])
        result[key] = result.get(key, 0) + 1
    return [{"kind": k[0], "code": k[1], "count": n} for k, n in sorted(result.items())]


class EvidenceValidator:
    def __init__(self, catalog):
        self.catalog = catalog

    def facts(self, facts, cutoff, expected=None):
        seen = set()
        clean = []
        for raw in facts:
            fact = EventFact.model_validate(raw).model_dump()
            if fact["id"] in seen or fact["event_ms"] >= milliseconds(cutoff):
                raise ValueError("Duplicate or future evidence")
            if milliseconds(fact["event_timestamp"]) != fact["event_ms"]:
                raise ValueError("Conflicting event clocks")
            if self.catalog.by_id.get(fact["id"]) != fact:
                raise ValueError("Conflicting source identity or missing provenance")
            seen.add(fact["id"])
            clean.append(fact)
        if expected is not None and clean != expected:
            raise ValueError("Graph/source evidence parity failed")
        return clean

    def bundle(self, machine, cutoff, start, limit, retrieved):
        cat = self.catalog
        own = cat.visible(machine, cutoff)
        window = cat.visible(machine, cutoff, start)
        peer = cat.visible(machine, cutoff, start, peer=True)
        visible = self.facts(retrieved["facts"], cutoff, window[:limit])
        metadata = retrieved["machine"]["machine"]
        original = cat.machines.loc[machine]
        ordinal = (
            int(cat.tables["machines"].index[cat.tables["machines"].machineID == machine][0]) + 1
        )
        expected_machine = {
            "id": str(machine),
            "machine_id": machine,
            "age": float(original.age),
            "model": original.model,
            "source_table": "PdM_machines.csv",
            "source_row": ordinal,
            "source_sha256": cat.hashes["machines"],
        }
        if (
            any(metadata.get(k) != v for k, v in expected_machine.items())
            or retrieved["machine"]["model"] != original.model
        ):
            raise ValueError("Graph machine/source metadata conflict")
        peers = [
            {"machine_id": int(m), "model": original.model}
            for m in sorted(cat.machines.index[cat.machines.model == original.model])
            if m != machine
        ]
        peer_counts = (
            []
            if not peers
            else [
                {
                    "model": original.model,
                    "eligible_peer_machines": len(peers),
                    "failure_records": sum(r["kind"] == "failures" for r in peer),
                    "maintenance_records": sum(r["kind"] == "maint" for r in peer),
                    "error_records": sum(r["kind"] == "errors" for r in peer),
                }
            ]
        )
        if (
            retrieved["lifetime_counts"] != counts(own)
            or retrieved["window_counts"] != counts(window)
            or retrieved["peers"] != peers
            or retrieved["peer_counts"] != peer_counts
        ):
            raise ValueError("Historical graph/source aggregate parity failed")
        contributing = sorted({r["id"] for r in [*own, *peer]})
        aggregate_id = "aggregate:" + digest([machine, iso(cutoff), iso(start), contributing])
        metadata_id = "machine:" + digest(expected_machine)
        return {
            "status": "verified",
            "source": "genuine_neo4j",
            "cutoff_exclusive": iso(cutoff),
            "window_start_inclusive": iso(start),
            "machine": {**expected_machine, "record_id": metadata_id},
            "facts": visible,
            "pagination": {
                "limit": limit,
                "returned": len(visible),
                "eligible_window_records": len(window),
                "truncated": len(window) > limit,
            },
            "derived_aggregates": {
                "record_id": aggregate_id,
                "lifetime_counts": retrieved["lifetime_counts"],
                "window_counts": retrieved["window_counts"],
                "model_peers": peers,
                "peer_window_counts": retrieved["peer_counts"],
                "supporting_source_fact_ids": contributing,
                "definition": (
                    "Recorded source rows; overlap retained; model peers are category associations"
                ),
            },
            "visibility_assumption": (
                "Immediate source event availability assumed; all dynamic facts "
                "strictly before cutoff"
            ),
            "catalog_artifacts_in_historical_evidence": False,
        }


class HistoricalEvidenceRetriever:
    def __init__(self, registry, catalog, database=None):
        self.config = registry.config
        self.catalog = catalog
        self.error = catalog.error
        self.db = None
        self.identity = {}
        self.owned = database is None
        self.last_timing = {}
        if self.error:
            return
        try:
            registry.require("artifacts/phase4/full/build.json")
            registry.require("artifacts/phase4/full/registration.json")
            build = read_json("artifacts/phase4/full/build.json")
            self.db = database or GraphDB(catalog.config)
            actual = self.db.read(
                "MATCH (b:GraphBuild {namespace:$namespace,id:'build'}) RETURN "
                "b.build_hash AS build_hash,b.schema_version AS "
                "schema_version,b.status AS status"
            )
            if actual != [
                {
                    "build_hash": build["build_hash"],
                    "schema_version": "factorygraph-phase4-v1",
                    "status": "complete",
                }
            ]:
                raise ValueError("Unverified graph build/schema")
            self.identity = {
                "namespace": catalog.config.namespace,
                "schema_version": actual[0]["schema_version"],
                "build_hash": build["build_hash"],
            }
            self.queries = HistoricalQueries(self.db)
        except Exception:
            self.error = "neo4j_connection_or_build_unavailable"

    def get(self, machine, cutoff):
        self.last_timing = {}
        if self.error:
            return {"status": "unavailable", "reason": self.error, "fallback": "disabled"}
        start = cutoff - pd.Timedelta(hours=self.config.window_hours)
        try:
            started = time.perf_counter()
            neighborhood = self.queries.neighborhood(
                EvidenceRequest(
                    machine_id=machine,
                    cutoff=cutoff.to_pydatetime(),
                    limit=self.config.evidence_limit,
                )
            )
            retrieved = {
                "machine": neighborhood["machine"],
                "facts": self.queries.history(
                    machine, cutoff, start=start, limit=self.config.evidence_limit
                ),
                "lifetime_counts": self.queries.counts(
                    machine, cutoff, pd.Timestamp("1900-01-01T00:00Z")
                ),
                "window_counts": self.queries.counts(machine, cutoff, start),
                "peers": self.queries.peers(machine),
                "peer_counts": self.queries.peer_counts(machine, cutoff, start),
            }
            self.last_timing["neo4j_queries_seconds"] = time.perf_counter() - started
            started = time.perf_counter()
            result = EvidenceValidator(self.catalog).bundle(
                machine, cutoff, start, self.config.evidence_limit, retrieved
            )
            self.last_timing["source_validation_seconds"] = time.perf_counter() - started
            return result
        except Exception:
            # Never reinterpret an exception, timeout, bad fact or empty endpoint as no history.
            return {
                "status": "unavailable",
                "reason": "graph_retrieval_or_evidence_validation_failed",
                "fallback": "disabled",
            }

    def close(self):
        if self.db is not None and self.owned:
            self.db.close()
