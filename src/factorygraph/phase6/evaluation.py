"""Registered bounded case study, independent source masks and performance evidence."""

import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import psutil

from factorygraph.io import sha256
from factorygraph.phase4.config import load_config as graph_config
from factorygraph.phase4.database import GraphDB
from factorygraph.phase4.source import identity
from factorygraph.phase6.common import KEYS, digest, iso, read_json, save_new
from factorygraph.phase6.integrity import BASELINE, P5, ArtifactRegistry, verify_protected
from factorygraph.phase6.rules import TEMPLATES, TRIGGERS
from factorygraph.phase6.schema import CaseReport
from factorygraph.phase6.service import CaseReportBuilder


def graph_integrity():
    expected = read_json("artifacts/phase4/full/build.json")
    db = GraphDB(graph_config(Path("configs/phase4/full.yaml")))
    try:
        signature, actual = db.signature(), db.counts()
        if signature != expected["signature"] or actual != expected["counts"]:
            raise ValueError("Accepted graph signature/counts changed")
        return {
            "signature": signature,
            "total_nodes": actual["total_nodes"],
            "relationships": sum(r["count"] for r in actual["relationships"]),
            "accepted_graph_unchanged": True,
        }
    finally:
        db.close()


def test_gate(config, stage):
    if stage not in {"c", "d"}:
        raise ValueError("Only fixture/integration gates are test stages")
    registry = ArtifactRegistry(config)
    paths = (
        ["tests/phase6/test_phase6_unit.py"]
        if stage == "c"
        else ["tests/phase6/test_phase6_saved.py", "tests/phase6/test_phase6_integration.py"]
    )
    if stage == "d":
        import os

        if os.environ.get("FACTORYGRAPH_NEO4J_INTEGRATION") != "1":
            raise ValueError("Gate D requires genuine Neo4j opt-in")
        if not read_json(config.run_dir / "gate_c.json")["passed"]:
            raise ValueError("Gate C must pass")
    started = time.perf_counter()
    process = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *paths], capture_output=True, text=True
    )
    save_new(
        config.run_dir / f"gate_{stage}.json",
        {
            "passed": process.returncode == 0 and " skipped" not in process.stdout,
            "returncode": process.returncode,
            "seconds": time.perf_counter() - started,
            "command": [sys.executable, "-m", "pytest", "-q", *paths],
            "output": process.stdout + process.stderr,
            "registration_sha256": digest(registry.record),
        },
    )
    if process.returncode or " skipped" in process.stdout:
        raise ValueError("Required gate tests failed or skipped; retain evidence")
    return {"status": "passed", "stage": stage}


def study(config):
    registry = ArtifactRegistry(config)
    for gate in ["c", "d"]:
        if not read_json(config.run_dir / f"gate_{gate}.json")["passed"]:
            raise ValueError("Fixture and genuine integration gates must pass")
    if (config.run_dir / "cases").exists():
        raise ValueError("Case study exists; do not overwrite frozen reports")
    graph_before = graph_integrity()
    implementation = {
        p.as_posix(): sha256(p) for p in sorted(Path("src/factorygraph/phase6").glob("*.py"))
    }
    save_new(config.run_dir / "implementation_freeze.json", implementation)
    records, timings = [], []
    start = time.perf_counter()
    with CaseReportBuilder(config) as service:
        cold = service.initialization_seconds
        if service.predictions.error or service.evidence.error or service.temporal.error:
            raise ValueError("Verified prediction, genuine graph and temporal integration required")
        for index, request in enumerate(registry.record["cases"]):
            report = service.build(request["machine_id"], request["snapshot"])
            path = config.run_dir / "cases" / f"{index:03}.json"
            save_new(path, report)
            records.append(
                {
                    "path": path.relative_to(config.run_dir).as_posix(),
                    "sha256": sha256(path),
                    "case_id": report["case_id"],
                    "category": request["category"],
                    "status": report["status"],
                }
            )
            timings.append({"case_id": report["case_id"], **service.last_timing})
        tick = time.perf_counter()
        fleet = service.fleet("2015-10-15T00:00Z")
        fleet_seconds = time.perf_counter() - tick
        save_new(config.run_dir / "fleet_example.json", fleet)
        memory = psutil.Process().memory_info()
    result = {
        "status": "completed_bounded_registered_study",
        "cases": len(records),
        "categories": dict(Counter(r["category"] for r in records)),
        "statuses": dict(Counter(r["status"] for r in records)),
        "records": records,
        "case_timings": timings,
        "cold_service_initialization_seconds": cold,
        "study_wall_seconds": time.perf_counter() - start,
        "fleet": {
            "snapshot": "2015-10-15T00:00:00+00:00",
            "cases": len(fleet),
            "seconds": fleet_seconds,
        },
        "memory": {
            "process_rss_bytes": memory.rss,
            "peak_working_set_bytes": getattr(memory, "peak_wset", None),
            "scope": (
                "CPU process with verified source/cache tables, Python libraries; no "
                "neural model loaded"
            ),
        },
        "graph_before": graph_before,
        "graph_after": graph_integrity(),
        "registration_sha256": digest(registry.record),
    }
    save_new(config.run_dir / "case_study.json", result)
    return {k: result[k] for k in ["status", "cases", "statuses", "study_wall_seconds"]}


class IndependentOracle:
    """CSV masks and a separate greedy loop; no graph query or service filtering helpers."""

    def __init__(self):
        self.machines = pd.read_csv("data/raw/azure/PdM_machines.csv").set_index("machineID")
        self.events = []
        revision = read_json("data/raw/azure/source_manifest.json")["revision"]
        for table, field in [("errors", "errorID"), ("maint", "comp"), ("failures", "failure")]:
            path = Path(f"data/raw/azure/PdM_{table}.csv")
            h = sha256(path)
            f = pd.read_csv(path)
            f["datetime"] = pd.to_datetime(f.datetime, utc=True)
            f["source_row"] = np.arange(1, len(f) + 1)
            f["kind"] = table
            f["code"] = f[field]
            f["id"] = [identity(revision, h, f"PdM_{table}.csv:data-row:{i}") for i in f.source_row]
            self.events.append(f[[*KEYS, "source_row", "kind", "code", "id"]])
        self.events = pd.concat(self.events).sort_values(["datetime", "kind", "id"])
        self.predictions = pd.read_parquet(
            BASELINE / "test_predictions.parquet", columns=[*KEYS, "probability"]
        )
        self.lookup = self.predictions.set_index(KEYS)
        self.threshold = read_json(BASELINE / "policy.json")["threshold"]
        self.policy = {}
        last = {}
        for row in self.predictions.sort_values(KEYS).itertuples(index=False):
            high = row.probability >= self.threshold
            prior = last.get(row.machineID)
            new = high and (prior is None or row.datetime - prior >= pd.Timedelta(hours=24))
            if new:
                last[row.machineID] = row.datetime
            self.policy[row.machineID, row.datetime] = (
                bool(high),
                bool(new),
                bool(high and not new),
                iso(last.get(row.machineID)),
            )
        self.features = pd.read_parquet(
            "data/processed/azure/snapshots.parquet",
            columns=[*KEYS, *read_json(BASELINE / "feature_contract.json")["columns"]],
        ).set_index(KEYS)
        self.temporal = pd.concat(
            [
                pd.read_parquet(P5 / f"temporal_c_{s}.parquet")
                for s in ["train", "calibration", "validation", "test"]
            ]
        ).set_index(KEYS)

    @staticmethod
    def counts(frame):
        return [
            {"kind": str(k), "code": str(c), "count": int(n)}
            for (k, c), n in frame.groupby(["kind", "code"], sort=True).size().items()
        ]

    def verify(self, report, config):
        CaseReport.model_validate(report)
        machine = report["request"]["machine_id"]
        cutoff = pd.Timestamp(report["request"]["snapshot"])
        key = (machine, cutoff)
        prediction, policy = report["prediction"], report["alert_policy"]
        if key in self.lookup.index:
            assert prediction["status"] == "verified"
            assert (
                prediction["machine_id"] == machine
                and pd.Timestamp(prediction["snapshot"]) == cutoff
            )
            assert prediction["probability"] == self.lookup.loc[key, "probability"]
            assert policy["threshold"] == self.threshold
            assert (
                tuple(
                    policy[k]
                    for k in [
                        "above_threshold",
                        "new_alert",
                        "cooldown_suppressed",
                        "last_episode_timestamp",
                    ]
                )
                == self.policy[key]
            )
        else:
            assert prediction["status"] == "unavailable" and prediction["probability"] is None
            assert policy["status"] == "unavailable"
        evidence = report["historical_evidence"]
        if machine not in self.machines.index:
            assert report["status"] == "abstained"
        else:
            assert evidence["status"] == "verified"
            start = cutoff - pd.Timedelta(hours=config.window_hours)
            eligible = self.events.loc[self.events.datetime < cutoff]
            own = eligible.loc[eligible.machineID == machine]
            window = own.loc[own.datetime >= start]
            assert [r["id"] for r in evidence["facts"]] == window.head(
                config.evidence_limit
            ).id.tolist()
            for fact in evidence["facts"]:
                assert pd.Timestamp(fact["event_timestamp"]) < cutoff
                source = window.loc[window.id == fact["id"]].iloc[0]
                assert (
                    source.machineID == fact["machine_id"]
                    and source.code == fact["code"]
                    and source.source_row == fact["source_row"]
                )
            aggregate = evidence["derived_aggregates"]
            assert aggregate["lifetime_counts"] == self.counts(own)
            assert aggregate["window_counts"] == self.counts(window)
            model = self.machines.loc[machine, "model"]
            peers = self.machines.loc[
                (self.machines.model == model) & (self.machines.index != machine)
            ]
            peer = eligible.loc[eligible.machineID.isin(peers.index) & (eligible.datetime >= start)]
            expected_peers = [{"machine_id": int(i), "model": model} for i in sorted(peers.index)]
            assert aggregate["model_peers"] == expected_peers
            assert evidence["machine"]["model"] == model
            expected_counts = (
                []
                if peers.empty
                else [
                    {
                        "model": model,
                        "eligible_peer_machines": len(peers),
                        "failure_records": int((peer.kind == "failures").sum()),
                        "maintenance_records": int((peer.kind == "maint").sum()),
                        "error_records": int((peer.kind == "errors").sum()),
                    }
                ]
            )
            assert aggregate["peer_window_counts"] == expected_counts
            assert aggregate["supporting_source_fact_ids"] == sorted(set(own.id) | set(peer.id))
        temporal = report["temporal_context"]
        if key in self.temporal.index and machine in self.machines.index:
            row = self.temporal.loc[key]
            for name, value in temporal["supplementary_chronos_context"]["values"].items():
                assert value == float(row[name]) if pd.notna(row[name]) else value is None
            for name, value in temporal["approved_predictor_inputs"]["values"].items():
                assert (
                    value == float(self.features.loc[key, name])
                    if pd.notna(self.features.loc[key, name])
                    else value is None
                )
            for clock in [
                "latest_source_observation_timestamp",
                "latest_residual_observation_timestamp",
            ]:
                value = temporal["supplementary_chronos_context"][clock]
                assert value is None or pd.Timestamp(value) < cutoff
            issue = temporal["supplementary_chronos_context"]["forecast_issue_timestamp"]
            assert issue is None or pd.Timestamp(issue) <= cutoff
        else:
            assert temporal["status"] == "unavailable"
        self.grounding(report)

    @staticmethod
    def grounding(report):
        e, t, p, policy = [
            report[k]
            for k in ["historical_evidence", "temporal_context", "prediction", "alert_policy"]
        ]
        expected = []
        if p["status"] == "verified":
            if policy["new_alert"]:
                expected.append("R001")
            elif policy["cooldown_suppressed"]:
                expected.append("R002")
        if e["status"] == "verified":
            for kind, rule in [("errors", "R003"), ("maint", "R004"), ("failures", "R005")]:
                if any(f["kind"] == kind for f in e["facts"]):
                    expected.append(rule)
        if "approved_predictor_inputs" in t:
            expected.append("R006")
        if p["status"] != "verified" or e["status"] != "verified" or t["status"] != "verified":
            expected.append("R007")
        assert [r["rule_id"] for r in report["recommendations"]] == expected
        allowed = {report["data_availability"]["record_id"]}
        if p["status"] == "verified":
            allowed.update([p["record_id"], policy["record_id"]])
        if e["status"] == "verified":
            allowed.update(f["id"] for f in e["facts"])
        if "approved_predictor_inputs" in t:
            allowed.add(t["approved_predictor_inputs"]["record_id"])
        for rec in report["recommendations"]:
            assert (
                rec["text"] == TEMPLATES[rec["rule_id"]]
                and rec["trigger"] == TRIGGERS[rec["rule_id"]]
            )
            assert rec["human_review_required"] is True
            assert set(rec["supporting_evidence_ids"]) <= allowed
            assert rec["cutoff_exclusive"] == report["request"]["snapshot"]


class OfflineEvaluationHarness:
    def __init__(self, config):
        self.config = config

    def run(self):
        c = self.config
        registry = ArtifactRegistry(c)
        study_result = read_json(c.run_dir / "case_study.json")
        for path, expected in read_json(c.run_dir / "implementation_freeze.json").items():
            if sha256(Path(path)) != expected:
                raise ValueError("Frozen implementation changed after case study")
        oracle = IndependentOracle()
        checks, failures = [], []
        with CaseReportBuilder(c) as service:
            for record, request in zip(
                study_result["records"], registry.record["cases"], strict=True
            ):
                path = c.run_dir / record["path"]
                assert sha256(path) == record["sha256"]
                report = read_json(path)
                try:
                    oracle.verify(report, c)
                    repeat = service.build(request["machine_id"], request["snapshot"])
                    assert digest(repeat) == digest(report)
                    checks.append({"case_id": report["case_id"], "passed": True})
                except (AssertionError, ValueError, KeyError) as error:
                    failures.append(
                        {"case_id": report["case_id"], "error_type": type(error).__name__}
                    )
            # Explicit in-memory infrastructure faults; no accepted input is altered.
            fault_results = []
            original = service.evidence.error
            service.evidence.error = "injected_database_unavailable"
            report = service.build(17, "2015-10-15T00:00Z")
            assert (
                report["historical_evidence"]["status"] == "unavailable"
                and "facts" not in report["historical_evidence"]
            )
            assert not (
                {"R003", "R004", "R005"} & set(report["provenance"]["recommendation_rule_ids"])
            )
            fault_results.append(
                {"fault": "database_unavailable", "status": report["status"], "safe": True}
            )
            service.evidence.error = original
            service.predictions.error = "injected_unverified_prediction"
            report = service.build(17, "2015-10-15T00:00Z")
            assert report["prediction"]["probability"] is None
            assert not ({"R001", "R002"} & set(report["provenance"]["recommendation_rule_ids"]))
            fault_results.append(
                {"fault": "unverified_prediction", "status": report["status"], "safe": True}
            )
        timing_keys = [k for k in study_result["case_timings"][0] if k != "case_id"]
        performance = {
            k: {
                "p50": float(np.median([r[k] for r in study_result["case_timings"]])),
                "p95": float(np.quantile([r[k] for r in study_result["case_timings"]], 0.95)),
                "scope": "Warm service, sequential registered requests",
            }
            for k in timing_keys
        }
        output = {
            "status": "passed" if not failures else "failed",
            "cases": len(checks),
            "failures": failures,
            "checks": checks,
            "engineering_endpoints": {
                k: not failures
                for k in [
                    "independent_source_evidence",
                    "temporal_faithfulness",
                    "recommendation_grounding",
                    "fixed_template_no_unsupported_diagnoses",
                    "determinism",
                    "model_policy_parity",
                    "no_future_label_disclosure",
                ]
            },
            "all_test_policy_rows_independently_replayed": len(oracle.policy),
            "all_test_episode_count": sum(row[1] for row in oracle.policy.values()),
            "faults": fault_results,
            "performance_seconds": performance,
            "protected_files_unchanged": verify_protected(c),
            "graph_integrity": graph_integrity(),
            "registration_sha256": digest(registry.record),
            "prospective_validation": False,
        }
        save_new(c.run_dir / "evaluation.json", output)
        if failures:
            raise ValueError("Registered evaluation failed; failure evidence retained")
        return {k: output[k] for k in ["status", "cases", "protected_files_unchanged"]}
