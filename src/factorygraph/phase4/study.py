"""Registered gates and independent source-table validation of genuine Cypher results."""

import json
import shutil
import time
from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd
import psutil

from factorygraph.io import sha256, write_json
from factorygraph.phase4.config import GraphConfig
from factorygraph.phase4.database import GraphDB, import_graph
from factorygraph.phase4.queries import EvidenceRequest, HistoricalQueries
from factorygraph.phase4.source import read_sources, verify_preservation

MACHINES = [1, 17, 42, 73, 100]
CUTOFFS = [f"2015-{v}T00:00:00Z" for v in ["02-01", "05-01", "08-01", "10-15", "12-31"]]


def resource_check():
    if psutil.virtual_memory().available < 3e9 or shutil.disk_usage(".").free < 2e9:
        raise RuntimeError("Registered resource floor reached")


def register(config: GraphConfig) -> dict:
    verify_preservation()
    resource_check()
    target = config.run_dir / "registration.json"
    if target.exists():
        raise ValueError("Registration exists; use a fresh run directory and namespace")
    _tables, hashes = read_sources(config)
    record = {
        "config": config.model_dump(mode="json"),
        "config_hash": config.digest(),
        "source_sha256": hashes,
        "protocol_sha256": sha256(Path("docs/PHASE4_EXPERIMENT.md")),
        "ontology_sha256": sha256(Path("docs/PHASE4_ONTOLOGY.md")),
        "registered_before_import_and_query_measurements": True,
    }
    config.run_dir.mkdir(parents=True, exist_ok=True)
    write_json(target, record)
    return record


def verify_registration(config: GraphConfig):
    verify_preservation()
    record = json.loads((config.run_dir / "registration.json").read_text())
    if record["config_hash"] != config.digest():
        raise ValueError("Registered configuration changed")
    if record["protocol_sha256"] != sha256(Path("docs/PHASE4_EXPERIMENT.md")) or record[
        "ontology_sha256"
    ] != sha256(Path("docs/PHASE4_ONTOLOGY.md")):
        raise ValueError("Registered protocol or ontology changed")
    return record


def reference_tables(config: GraphConfig):
    started = time.perf_counter()
    tables = {
        name: pd.read_parquet(config.processed_dir / f"{name}.parquet")
        for name in ["machines", "errors", "maint", "failures"]
    }
    for name, frame in tables.items():
        tables[name] = frame.loc[frame.machineID.isin(config.machine_ids)]
    return tables, time.perf_counter() - started


def tabular_counts(tables, machine, cutoff, start):
    records = []
    for name, field in [("errors", "errorID"), ("maint", "comp"), ("failures", "failure")]:
        frame = tables[name]
        selected = frame.loc[
            (frame.machineID == machine) & (frame.datetime < cutoff) & (frame.datetime >= start)
        ]
        records.extend(
            {"kind": name, "code": code, "count": int(n)}
            for code, n in selected.groupby(field).size().items()
        )
    return sorted(records, key=lambda r: (r["kind"], r["code"]))


def tabular_peers(tables, machine, cutoff, start):
    machines = tables["machines"]
    model = machines.loc[machines.machineID == machine, "model"].item()
    peers = machines.loc[(machines.model == model) & (machines.machineID != machine), "machineID"]
    result = {"model": model, "eligible_peer_machines": len(peers)}
    for name, label in [
        ("errors", "error_records"),
        ("maint", "maintenance_records"),
        ("failures", "failure_records"),
    ]:
        frame = tables[name]
        result[label] = int(
            (
                frame.machineID.isin(peers) & (frame.datetime < cutoff) & (frame.datetime >= start)
            ).sum()
        )
    return result if len(peers) else None


def validate_queries(db: GraphDB, config: GraphConfig) -> dict:
    tables, source_load = reference_tables(config)
    query = HistoricalQueries(db)
    checks = []
    for machine in MACHINES:
        if machine not in config.machine_ids:
            continue
        for value in CUTOFFS:
            cutoff = pd.Timestamp(value)
            start = cutoff - pd.Timedelta(hours=config.window_hours)
            actual = query.counts(machine, cutoff, start)
            expected = tabular_counts(tables, machine, cutoff, start)
            if actual != expected:
                raise ValueError("Cypher/source historical counts differ")
            actual_peers = query.peer_counts(machine, cutoff, start)
            expected_peers = tabular_peers(tables, machine, cutoff, start)
            if actual_peers != ([expected_peers] if expected_peers else []):
                raise ValueError("Cypher/source model-peer counts differ")
            events = query.history(machine, cutoff)
            if any(r["event_ms"] >= cutoff.value // 1000000 for r in events):
                raise ValueError("Historical query exposed future events")
            if any(
                not all(
                    k in r
                    for k in [
                        "source_record_id",
                        "source_sha256",
                        "source_payload_sha256",
                        "ingested_at",
                    ]
                )
                for r in events
            ):
                raise ValueError("Historical evidence lacks provenance")
            expected_total = sum(
                int(((f.machineID == machine) & (f.datetime < cutoff)).sum())
                for n, f in tables.items()
                if n != "machines"
            )
            if len(events) != expected_total:
                raise ValueError("Historical event membership differs from source")
            checks.append(
                {
                    "machine": machine,
                    "cutoff": value,
                    "counts_equal": True,
                    "peers_equal": True,
                    "historical_event_rows": len(events),
                }
            )
    # Validate directed relationship endpoints/cardinalities rather than counts alone.
    defects = db.read(
        "MATCH (e:RecordedEvent {namespace:$namespace}) "
        "OPTIONAL MATCH (m:Machine {namespace:$namespace})-"
        "[:RECORDED_ERROR|HAS_MAINTENANCE_EVENT|HAS_FAILURE_EVENT]->(e) "
        "WITH e,collect(m.machine_id) AS owners "
        "WHERE size(owners)<>1 OR owners[0]<>e.machine_id "
        "RETURN count(e) AS count"
    )[0]["count"]
    if defects:
        raise ValueError("Event ownership/cardinality mismatch")
    write_json(
        config.run_dir / "temporal_validation.json",
        {
            "status": "passed",
            "source_parquet_load_seconds": source_load,
            "checks": checks,
            "event_ownership_defects": defects,
        },
    )
    return {"status": "passed", "cases": len(checks)}


def build(config: GraphConfig, pilot: bool = False) -> dict:
    verify_registration(config)
    resource_check()
    if not pilot:
        admission = json.loads(Path("artifacts/phase4/pilot/admission.json").read_text())
        if admission["status"] != "admitted":
            raise ValueError("Pilot gate did not admit full construction")
    db = GraphDB(config)
    try:
        first = import_graph(db, config)
        second = import_graph(db, config)
        if first["signature"] != second["signature"] or first["counts"] != second["counts"]:
            raise ValueError("Repeated import changed logical content")
        record = {
            **first,
            "repeat_import_seconds": second["seconds"],
            "idempotency_passed": True,
            "server": db.read(
                "CALL dbms.components() YIELD name,versions,edition RETURN name,versions,edition"
            ),
        }
        write_json(config.run_dir / "build.json", record)
        validation = validate_queries(db, config)
        evidence = HistoricalQueries(db).neighborhood(
            EvidenceRequest(
                machine_id=17, cutoff=pd.Timestamp("2015-10-15T00:00Z").to_pydatetime(), limit=100
            )
        )
        write_json(config.run_dir / "evidence_machine17.json", evidence)
        if pilot:
            projected = first["seconds"] * 100 / len(config.machine_ids) * 2 + 120
            resource_check()
            write_json(
                config.run_dir / "admission.json",
                {
                    "status": "admitted" if projected <= 1800 else "not_admitted",
                    "projected_full_seconds": projected,
                    "maximum_seconds": 1800,
                    "validation": validation,
                    "pilot_machines": config.machine_ids,
                    "free_ram_bytes": psutil.virtual_memory().available,
                    "free_disk_bytes": shutil.disk_usage(".").free,
                    "registered_before_full_import": True,
                },
            )
        return record
    finally:
        db.close()


def benchmark(db: GraphDB, config: GraphConfig) -> dict:
    verify_registration(config)
    queries = HistoricalQueries(db)
    tables, load_seconds = reference_tables(config)
    samples = []
    for repeat in range(config.query_repeats):
        for machine in MACHINES:
            for value in CUTOFFS:
                cutoff = pd.Timestamp(value)
                start = cutoff - pd.Timedelta(hours=config.window_hours)
                for name, graph, tabular in [
                    (
                        "own_counts",
                        partial(queries.counts, machine, cutoff, start),
                        partial(tabular_counts, tables, machine, cutoff, start),
                    ),
                    (
                        "peer_counts",
                        partial(queries.peer_counts, machine, cutoff, start),
                        partial(tabular_peers, tables, machine, cutoff, start),
                    ),
                ]:
                    begin = time.perf_counter()
                    actual = graph()
                    graph_ms = (time.perf_counter() - begin) * 1000
                    begin = time.perf_counter()
                    expected = tabular()
                    if name == "peer_counts":
                        expected = [expected] if expected else []
                    pandas_ms = (time.perf_counter() - begin) * 1000
                    if actual != expected:
                        raise ValueError("Benchmark equivalent tasks differ")
                    samples.append(
                        {
                            "repeat": repeat,
                            "machine": machine,
                            "cutoff": value,
                            "task": name,
                            "graph_ms": graph_ms,
                            "pandas_ms": pandas_ms,
                        }
                    )
                begin = time.perf_counter()
                queries.history(machine, cutoff, limit=100)
                samples.append(
                    {
                        "repeat": repeat,
                        "machine": machine,
                        "cutoff": value,
                        "task": "bounded_evidence",
                        "graph_ms": (time.perf_counter() - begin) * 1000,
                    }
                )
        for value in CUTOFFS:
            begin = time.perf_counter()
            facts = queries.fleet_facts(pd.Timestamp(value))
            samples.append(
                {
                    "repeat": repeat,
                    "cutoff": value,
                    "task": "full_fleet_facts",
                    "graph_ms": (time.perf_counter() - begin) * 1000,
                    "rows": len(facts),
                }
            )
    metrics = {}
    for task in sorted({r["task"] for r in samples}):
        metrics[task] = {}
        for field in ["graph_ms", "pandas_ms"]:
            values = [r[field] for r in samples if r["task"] == task and field in r]
            if values:
                metrics[task][field] = {
                    "count": len(values),
                    "mean": float(np.mean(values)),
                    "p50": float(np.median(values)),
                    "p95": float(np.quantile(values, 0.95)),
                }
    result = {
        "status": "completed",
        "source_parquet_load_seconds": load_seconds,
        "samples": samples,
        "latency": metrics,
        "scope": "Local serial driver roundtrips vs in-memory Pandas; not production scalability",
    }
    write_json(config.run_dir / "benchmark.json", result)
    return result
