"""Independent saved-record recomputation and accepted case-report equivalence."""

import gc
import hashlib
import json
import math
import statistics
from pathlib import Path

import numpy as np

from factorygraph.io import sha256
from factorygraph.phase6.common import digest, read_json, save_new
from factorygraph.phase6.evaluation import IndependentOracle
from factorygraph.phase7.config import Settings
from factorygraph.phase7.runtime import project
from factorygraph.phase8.candidate import CandidateRuntime
from factorygraph.phase8.common import ROOT, config


def semantics():
    rows = []
    runtime = CandidateRuntime(Settings())
    oracle = IndependentOracle()
    try:
        for record in read_json("artifacts/phase6/study/case_study.json")["records"]:
            path = Path("artifacts/phase6/study") / record["path"]
            assert sha256(path) == record["sha256"]
            expected = read_json(path)
            req = expected["request"]
            actual = runtime.builder.build(req["machine_id"], req["snapshot"])
            assert actual == expected
            oracle.verify(actual, runtime.builder.config)
            rows.append(
                {
                    "case_id": actual["case_id"],
                    "category": record["category"],
                    "status": actual["status"],
                    "accepted_file_sha256": record["sha256"],
                    "canonical_report_sha256": digest(actual),
                    "canonical_projection_sha256": digest(project(actual)),
                    "all_fields_equal": True,
                    "independent_source_oracle_passed": True,
                }
            )
        save_new(
            ROOT / "semantic_equivalence.json",
            {
                "cases": rows,
                "failures": [],
                "complete_fields_compared": True,
                "independent_oracle": True,
            },
        )
    finally:
        runtime.close()
        del runtime, oracle
        gc.collect()
    return {"exact_cases": len(rows), "independent_source_oracle": True}


def summary(values):
    result = {"n": len(values), "median": statistics.median(values), "max": max(values)}
    if len(values) >= 20:
        ordered = sorted(values)
        pos = (len(ordered) - 1) * 0.95
        lo = int(pos)
        result["p95_descriptive"] = ordered[lo] + (
            ordered[min(lo + 1, len(ordered) - 1)] - ordered[lo]
        ) * (pos - lo)
    assert math.isclose(result["median"], float(np.median(values)), abs_tol=1e-12)
    if "p95_descriptive" in result:
        assert math.isclose(
            result["p95_descriptive"], float(np.quantile(values, 0.95)), abs_tol=1e-12
        )
    return result


def analyze():
    complete = read_json(ROOT / "comparison_complete.json")
    assert complete["blocks"] == 6
    references = {r["name"] for r in read_json(ROOT / "registration.json")["references"]}
    canonical, groups, blocks, comparisons = {}, {"baseline": [], "candidate": []}, [], []
    for number, variant in enumerate(config()["block_order"]):
        directory = ROOT / f"block-{number}-{variant}"
        records = read_json(directory / "requests.json")
        for r in records:
            assert "failure" not in r
            path = directory / r["response_file"]
            body = path.read_bytes()
            assert hashlib.sha256(body).hexdigest() == r["body_sha256"]
            assert len(body) == r["response_bytes"]
            value = json.loads(body)
            if r["scenario"] == "metrics":
                continue  # Explicitly nonsemantic evolving service timing/resource metadata.
            if "request_id" in value:
                value.pop("request_id")  # Only allowed per-request identity differs.
            code = digest(value)
            canonical.setdefault(r["scenario"], code)
            assert code == canonical[r["scenario"]], r["scenario"]
            comparisons.append(
                {
                    "block": number,
                    "scenario": r["scenario"],
                    "canonical_sha256": code,
                    "exact_semantic_equality": True,
                }
            )
        groups[variant].extend(records)
        resources = read_json(directory / "resources.json")
        assert resources["graceful_closed"] and resources["budget_violation"] is None
        samples = resources["rss_samples"]
        serial = read_json(directory / "serial_window.json")
        measured = [r for r in records if r["scenario"] not in {"metrics", "warmup"}]
        fleet = next(r for r in measured if r["scenario"] == "fleet_100")
        concurrency = read_json(directory / "concurrency.json")
        assert sorted(r["status"] for r in concurrency["requests"]) == [200, 503, 503]
        accepted = next(r for r in concurrency["requests"] if r["status"] == 200)
        nonalert = next(r for r in records if r["scenario"] == "warmup")
        assert accepted["body_sha256"] == nonalert["body_sha256"]
        blocks.append(
            {
                "block": number,
                "variant": variant,
                "fleet_http_seconds": fleet["http_seconds"],
                "fleet_response_bytes": fleet["response_bytes"],
                "fleet_body_complete_seconds": fleet["body_complete_seconds"],
                "fleet_headers_seconds": fleet["headers_seconds"],
                "fleet_decode_seconds": fleet["decode_seconds"],
                "startup_to_ready_seconds": resources["startup_to_ready_seconds"],
                "engine_startup_seconds": read_json(directory / "engine.json")["startup_seconds"],
                "shutdown_seconds": resources["shutdown_seconds"],
                "peak_sampled_warm_rss_bytes": max(s["rss_bytes"] for s in samples),
                "minimum_sampled_available_ram": min(s["available_ram_bytes"] for s in samples),
                "serial_window": serial,
                "serial_completed_requests_per_second": len(measured) / serial["wall_seconds"],
                "serial_http_200_per_second": sum(r["status"] == 200 for r in measured)
                / serial["wall_seconds"],
                "concurrent_accepted_per_second": 1 / concurrency["wall_seconds"],
            }
        )
    output = {}
    for variant, rows in groups.items():
        reference = [r["http_seconds"] for r in rows if r["scenario"] in references]
        output[variant] = {
            "reference_http_seconds": summary(reference),
            "small_fleet_http_seconds": summary(
                [r["http_seconds"] for r in rows if r["scenario"] == "fleet_3"]
            ),
            "full_fleet_http_seconds": summary(
                [r["http_seconds"] for r in rows if r["scenario"] == "fleet_100"]
            ),
            "statuses": {
                str(s): sum(r["status"] == s for r in rows)
                for s in sorted({r["status"] for r in rows})
            },
            "requests_including_warmups_and_metrics": len(rows),
            "unexpected_failures": 0,
        }
    pairs = []
    for offset in range(0, 6, 2):
        pair = blocks[offset : offset + 2]
        b = next(r for r in pair if r["variant"] == "baseline")
        c = next(r for r in pair if r["variant"] == "candidate")
        pairs.append(
            {
                "pair": offset // 2,
                "baseline_seconds": b["fleet_http_seconds"],
                "candidate_seconds": c["fleet_http_seconds"],
                "reduction_fraction": 1 - c["fleet_http_seconds"] / b["fleet_http_seconds"],
            }
        )
    reductions = [p["reduction_fraction"] for p in pairs]
    reference_ratio = (
        output["candidate"]["reference_http_seconds"]["median"]
        / output["baseline"]["reference_http_seconds"]["median"]
    )
    rule = config()["retention"]
    passed = (
        all(x > 0 for x in reductions)
        and statistics.median(reductions) >= rule["minimum_paired_fleet_reduction_fraction"]
        and reference_ratio <= 1 + rule["maximum_reference_median_regression_fraction"]
    )
    result = {
        "status": "analyzed",
        "variants": output,
        "pairs": pairs,
        "blocks": blocks,
        "median_paired_fleet_reduction_fraction": statistics.median(reductions),
        "reference_http_median_ratio": reference_ratio,
        "performance_gate_passed": passed,
        "independent_metric_recomputation": (
            "Python sorted interpolation/statistics agree with NumPy"
        ),
        "semantic_response_comparisons": len(comparisons),
        "all_saved_responses_verified": True,
        "scope": "Matched native HTTP; no container/browser/SLA claim",
    }
    save_new(ROOT / "http_equivalence.json", comparisons)
    save_new(ROOT / "analysis.json", result)
    return result


if __name__ == "__main__":
    import sys

    print(semantics() if sys.argv[1] == "semantics" else analyze())
