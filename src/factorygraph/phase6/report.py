"""Offline verification and portable summary; never rerun previous experiments."""

import argparse
import importlib.metadata
import platform
from pathlib import Path

from factorygraph.io import sha256, write_json
from factorygraph.phase6.common import load_config, manifest, read_json
from factorygraph.phase6.evaluation import graph_integrity
from factorygraph.phase6.integrity import ArtifactRegistry, verify_protected


def generate(config):
    registry = ArtifactRegistry(config)
    evaluation = read_json(config.run_dir / "evaluation.json")
    if evaluation["status"] != "passed":
        raise ValueError("Offline evaluation has not passed")
    tests = read_json(config.run_dir / "test_results.json")
    checks = read_json(config.run_dir / "release_checks.json")
    if not all(v["returncode"] == 0 for v in tests.values()) or not checks["passed"]:
        raise ValueError("Required regression/release checks failed")
    frozen = read_json(config.run_dir / "implementation_freeze.json")
    for path, expected in frozen.items():
        if sha256(Path(path)) != expected:
            raise ValueError("Frozen service implementation changed")
    preserved = verify_protected(config)
    graph = graph_integrity()
    study = read_json(config.run_dir / "case_study.json")
    examples = []
    for record in study["records"]:
        case = read_json(config.run_dir / record["path"])
        examples.append(
            {
                "case_id": case["case_id"],
                "request": case["request"],
                "category": record["category"],
                "status": case["status"],
                "probability": case["prediction"]["probability"],
                "new_alert": case["alert_policy"]["new_alert"],
                "cooldown_suppressed": case["alert_policy"]["cooldown_suppressed"],
                "rules": case["provenance"]["recommendation_rule_ids"],
            }
        )
    paths = [
        *Path("src/factorygraph/phase6").glob("*.py"),
        *Path("tests/phase6").glob("*.py"),
        *Path("configs/phase6").glob("*"),
        Path("requirements/phase6.lock"),
    ]
    summary = {
        "date": "2026-11-14",
        "status": "completed_phase6_bounded_synthetic_replay",
        "approved_predictor": (
            "Phase 1 calibrated LightGBM saved predictions; exact Phase 5 A0 parity"
        ),
        "phase5_replacement_decision": "NO-GO preserved",
        "phase5_wording_erratum": (
            "A0 and A6 share 134 detected events; their respective totals are 141 and 144."
        ),
        "gate_a": read_json(config.run_dir / "gate_a.json"),
        "registration": registry.record,
        "case_study": study,
        "evaluation": evaluation,
        "case_summary": examples,
        "tests": tests,
        "release_checks": checks,
        "protected_historical_files_unchanged": preserved,
        "graph_integrity": graph,
        "implementation_sha256": {p.as_posix(): sha256(p) for p in sorted(paths)},
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "packages": {
                p: importlib.metadata.version(p)
                for p in ["numpy", "pandas", "pydantic", "neo4j", "lightgbm"]
            },
        },
        "scope": (
            "59 registered label-free cases and a bounded 100-machine exact-"
            "snapshot fleet replay; no prospective study"
        ),
        "phase7_started": False,
        "limitations": [
            "Synthetic historical replay and previously observed benchmark",
            "Immediate arrival and UTC are assumptions",
            "No diagnosis, physical actuation, new predictor or predictive-accuracy claim",
            "No real industrial operational validation; MetroPT test remains incomplete",
            "Hash manifests detect drift but are not signed trust roots",
            "Warm CPU process includes complete verified caches and source tables",
            (
                "No authentication/authorization, HTTP service, monitoring or "
                "production governance implemented"
            ),
        ],
    }
    write_json(Path("docs/results/phase6.json"), summary)
    manifest(config.run_dir)
    return {"status": summary["status"], "protected_files": preserved, "cases": study["cases"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args()
    print(generate(load_config(run_dir=args.run_dir)))
