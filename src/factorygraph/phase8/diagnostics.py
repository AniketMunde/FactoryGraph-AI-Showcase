"""Bounded read-only Cypher plans and separately scoped allocation diagnostics."""

import time
import tracemalloc

import psutil
from neo4j import unit_of_work

from factorygraph.phase4.config import milliseconds
from factorygraph.phase4.queries import COUNTS, HISTORY, PEER_COUNTS, PEERS
from factorygraph.phase6.common import save_new
from factorygraph.phase7.config import Settings
from factorygraph.phase7.runtime import MACHINE_QUERY, ReadOnlyGraph, Runtime, utc
from factorygraph.phase8.common import ROOT, budget


def plans():
    db = ReadOnlyGraph()
    queries = {
        "history": HISTORY,
        "counts": COUNTS,
        "peers": PEERS,
        "peer_counts": PEER_COUNTS,
        "machine": MACHINE_QUERY,
    }
    parameters = {
        "namespace": db.config.namespace,
        "machine": 17,
        "cutoff": milliseconds(utc("2015-10-15T00:00Z")),
        "start": milliseconds(utc("2015-09-15T00:00Z")),
        "kinds": ["errors", "maint", "failures"],
        "component": None,
        "limit": 100,
        "offset": 0,
    }
    records = []
    try:
        for name, query in queries.items():
            for mechanism in [
                "EXPLAIN",
                *(["PROFILE"] if name in {"history", "peer_counts"} else []),
            ]:
                started = time.perf_counter()
                with db.driver.session(database="neo4j", default_access_mode="READ") as session:

                    @unit_of_work(timeout=5)
                    def run(tx, statement=mechanism + " " + query):
                        result = tx.run(statement, **parameters)
                        rows = list(result)
                        summary = result.consume()
                        return len(rows), summary

                    rows, summary = session.execute_read(run)
                records.append(
                    {
                        "query": name,
                        "mechanism": mechanism,
                        "seconds": time.perf_counter() - started,
                        "rows": rows,
                        "query_type": summary.query_type,
                        "plan": summary.profile or summary.plan,
                        "result_available_after_ms": summary.result_available_after,
                        "result_consumed_after_ms": summary.result_consumed_after,
                    }
                )
        save_new(ROOT / "cypher_plans.json", records)
    finally:
        db.close()
    return {"read_only_plans": len(records), "indexes_modified": False}


def allocations():
    budget()
    before = psutil.Process().memory_info().rss
    runtime = Runtime(Settings())
    loaded = psutil.Process().memory_info().rss
    try:
        b = runtime.builder
        tables = {
            **{
                "source_" + name: int(frame.memory_usage(index=True, deep=True).sum())
                for name, frame in b.catalog.tables.items()
            },
            "predictor_inputs": int(b.temporal.inputs.memory_usage(index=True, deep=True).sum()),
            "temporal_context": int(b.temporal.context.memory_usage(index=True, deep=True).sum()),
            "prediction_frame": int(b.predictions.frame.memory_usage(index=True, deep=True).sum()),
        }
        tracemalloc.start(8)
        started = time.perf_counter()
        report = runtime.case(17, utc("2015-10-15T00:00Z"))
        seconds = time.perf_counter() - started
        current, peak = tracemalloc.get_traced_memory()
        top = [
            {"trace": str(r.traceback), "bytes": r.size, "count": r.count}
            for r in tracemalloc.take_snapshot().statistics("lineno")[:20]
        ]
        tracemalloc.stop()
        import json

        save_new(
            ROOT / "allocation_diagnostic.json",
            {
                "rss_before_runtime": before,
                "rss_after_runtime": loaded,
                "table_logical_deep_bytes": tables,
                "source_event_fact_count": len(b.catalog.facts),
                "single_case_traced_seconds": seconds,
                "traced_current_bytes": current,
                "traced_peak_bytes": peak,
                "traced_top": top,
                "single_case_json_bytes": len(json.dumps(report).encode()),
                "scope": (
                    "Separate traced Python allocation pass, not latency comparison; "
                    "table sums may overlap"
                ),
            },
        )
    finally:
        runtime.close()
    return {"allocation_pass": "saved_separately"}


if __name__ == "__main__":
    import sys

    print(plans() if sys.argv[1] == "plans" else allocations())
