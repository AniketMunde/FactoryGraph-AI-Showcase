"""Offline evidence handoff with exact preservation and no benchmark reruns."""

from pathlib import Path

from factorygraph.io import sha256, verify_artifacts, write_json
from factorygraph.phase6.common import read_json
from factorygraph.phase8.common import ROOT, verify


def generate():
    analysis = read_json(ROOT / "analysis.json")
    semantics = read_json(ROOT / "semantic_equivalence.json")
    evidence = ROOT / "final" if (ROOT / "final/test_results.json").exists() else ROOT
    tests = read_json(evidence / "test_results.json")
    release = read_json(evidence / "release_checks.json")
    frontend = read_json(ROOT / "frontend_diagnostic.json")
    if not release["passed"] or not all(r["returncode"] == 0 for r in tests.values()):
        raise ValueError("Required current-source checks did not pass")
    if len(semantics["cases"]) != 59 or semantics["failures"]:
        raise ValueError("Incomplete exact semantic equivalence")
    for name, expected in read_json(ROOT / "candidate_registration.json")[
        "implementation_sha256"
    ].items():
        actual = sha256(Path(name))
        if actual != expected:
            amendment = read_json(ROOT / "administrative_amendment.json")
            if (
                name != amendment["path"]
                or expected != amendment["before_sha256"]
                or actual != amendment["after_sha256"]
                or not all(amendment["unchanged_measured_function_AST"].values())
            ):
                raise ValueError("Unrecorded candidate/runtime change")
    preservation = verify()
    decision = (
        "RETAIN C1 for opt-in native service use"
        if analysis["performance_gate_passed"]
        else "NO-GO: retain original Phase 7 service"
    )
    paths = [
        *Path("src/factorygraph/phase8").glob("*.py"),
        *Path("tests/phase8").glob("*.py"),
        *Path("configs/phase8").glob("*"),
        *Path("docs").glob("PHASE8_*.md"),
        Path("scripts/phase8_verify.py"),
        Path("README.md"),
        *[Path("docs") / (n + ".md") for n in ["ARCHITECTURE", "ROADMAP", "DECISIONS"]],
    ]
    result = {
        "date": "2026-11-15",
        "status": "completed_native_decision_support_service_study",
        "decision": decision,
        "run_dir": ROOT.as_posix(),
        "primary_predictor_unchanged": "Approved Phase 1 calibrated LightGBM / Phase 5 A0",
        "phase5_predictive_replacement_decision": "NO-GO",
        "accepted_phase7_modules_modified": False,
        "registration": read_json(ROOT / "registration.json"),
        "harness_amendment": read_json(ROOT / "harness_amendment.json"),
        "candidate_registration": read_json(ROOT / "candidate_registration.json"),
        "analysis": analysis,
        "semantic_equivalence": semantics,
        "http_equivalence": {
            "comparisons": len(read_json(ROOT / "http_equivalence.json")),
            "failures": 0,
        },
        "cypher_plans": read_json(ROOT / "cypher_plans.json"),
        "allocation_diagnostic": read_json(ROOT / "allocation_diagnostic.json"),
        "frontend_diagnostic": frontend,
        "background_resource_observations": read_json(
            ROOT / "background_resource_observations.json"
        )
        if (ROOT / "background_resource_observations.json").exists()
        else None,
        "hardware_details": read_json(ROOT / "hardware_details.json")
        if (ROOT / "hardware_details.json").exists()
        else None,
        "tests": tests,
        "test_evidence_directory": evidence.as_posix(),
        "release_checks": release,
        "preservation": preservation,
        "implementation_sha256": {p.as_posix(): sha256(p) for p in sorted(paths)},
        "retained_negative_evidence": [
            "Initial off-grid HTTP expectation failure",
            "Independent hash-verifier request-key correction",
            "No increased compute concurrency",
        ],
        "limitations": [
            "Native Windows retrospective decision-support study; no GPU/model experiment",
            "Three full-fleet pairs; local descriptive evidence, no SLA/general speedup",
            "Metadata index increases startup/memory; immutable inputs require restart",
            "Warm RSS sampling excludes unobserved startup/native allocation peaks",
            "UI AppTest n=1 per variant, fixed order and warm library effects; no UI gain claim",
            "System CPU point observations vary; workstation not isolated",
            "Graph batching, source indexes, serializer/frontend cache changes not implemented",
            "Docker/Compose/Linux and browser visual/accessibility acceptance remain incomplete",
            "MetroPT real test remains incomplete; no real-machinery predictive claim",
        ],
        "docker_executed": False,
        "browser_visual_qa_executed": False,
        "gpu_experiment": False,
        "models_retrained": False,
        "public_deployment": False,
        "subsequent_phase_started": False,
    }
    write_json(Path("docs/results/phase8.json"), result)
    paths.append(Path("docs/results/phase8.json"))
    write_json(
        ROOT / "file_inventory.json",
        {p.as_posix(): {"bytes": p.stat().st_size, "sha256": sha256(p)} for p in sorted(paths)},
    )
    write_json(
        ROOT / "artifact_manifest.json",
        {
            p.relative_to(ROOT).as_posix(): sha256(p)
            for p in sorted(ROOT.rglob("*"))
            if p.is_file() and p.name != "artifact_manifest.json" and "__pycache__" not in p.parts
        },
    )
    verify_artifacts(ROOT)
    return {"status": result["status"], "decision": decision, **preservation}


if __name__ == "__main__":
    print(generate())
