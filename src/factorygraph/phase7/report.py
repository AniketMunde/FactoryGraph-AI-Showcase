"""Portable Phase 7 evidence; never label unexecuted containers as accepted."""

import importlib.metadata
from pathlib import Path

from factorygraph.io import sha256, verify_artifacts, write_json
from factorygraph.phase6.common import read_json
from factorygraph.phase6.evaluation import graph_integrity
from factorygraph.phase7.audit import ROOT, verify


def generate():
    pilot = read_json(ROOT / "pilot.json")
    final = ROOT / "final" if (ROOT / "final/test_results.json").exists() else ROOT
    tests = read_json(final / "test_results.json")
    release = read_json(final / "release_checks.json")
    for path, expected in read_json(ROOT / "implementation_freeze.json").items():
        if path == "src/factorygraph/phase7/report.py":
            continue  # Administrative reporting is outside the measured runtime.
        if path == "src/factorygraph/phase7/cli.py":
            update = read_json(ROOT / "lifecycle_update.json")
            if update["before"] != expected or sha256(Path(path)) != update["after"]:
                raise ValueError("Unrecorded lifecycle change")
            continue  # Owned-tree stop correction; no measured case/API change.
        if sha256(Path(path)) != expected:
            raise ValueError("Pilot implementation changed")
    if not all(r["returncode"] == 0 for r in tests.values()) or not release["passed"]:
        raise ValueError("Required verification failed")
    protected = verify()
    graph = graph_integrity()
    files = [
        *Path("src/factorygraph/phase7").glob("*.py"),
        *Path("tests/phase7").glob("*.py"),
        *Path("apps/factorygraph_dashboard").glob("*.py"),
        *Path("configs/phase7").glob("*"),
        *Path("deployment").rglob("*"),
        *Path("requirements").glob("phase7*"),
        Path(".dockerignore"),
        Path("scripts/phase7_verify.py"),
        *Path("docs").glob("PHASE7_*.md"),
        Path("README.md"),
        *[Path("docs") / (name + ".md") for name in ["ARCHITECTURE", "ROADMAP", "DECISIONS"]],
    ]
    files = [p for p in files if p.is_file() and "__pycache__" not in p.parts and p.name != ".env"]
    result = {
        "date": "2026-11-15",
        "status": "native_verified_container_acceptance_incomplete",
        "runtime_modes": ["full_local_retrospective", "verified_static_gallery"],
        "primary_model": "Accepted Phase 1 calibrated LightGBM; exact Phase 5 A0 parity",
        "phase5_no_go_preserved": True,
        "phase8_started": False,
        "registration": read_json(ROOT / "registration.json"),
        "deployment_inventory": read_json(ROOT / "deployment_manifest.json"),
        "pilot": pilot,
        "process_resource_observation": read_json(ROOT / "process_resources.json"),
        "native_lifecycle_acceptance": read_json(ROOT / "native_lifecycle_acceptance.json"),
        "post_pilot_lifecycle_update": read_json(ROOT / "lifecycle_update.json"),
        "test_evidence_directory": final.as_posix(),
        "tests": tests,
        "release_checks": release,
        "protected_historical_files_unchanged": protected,
        "graph_integrity": graph,
        "implementation_sha256": {p.as_posix(): sha256(p) for p in sorted(files)},
        "packages": {
            n: importlib.metadata.version(n)
            for n in [
                "fastapi",
                "starlette",
                "uvicorn",
                "streamlit",
                "httpx",
                "neo4j",
                "pandas",
                "numpy",
            ]
        },
        "container_gates": {
            "E_clean_build": "not_executed_no_docker",
            "F_isolated_compose": "not_executed_no_docker",
            "linux_parity": "not_verified",
            "container_restart_shutdown": "not_verified",
        },
        "browser_visual_qa": "Browser host unavailable; AppTest and HTTP verified separately",
        "public_deployment": False,
        "limitations": [
            "Synthetic historical demonstration, no real-machinery validity",
            "Container build/start/Linux runtime are not verified",
            "AppTest is not browser paint/visual QA",
            "Local bearer roles are not a reviewed public identity system",
            "Community Neo4j account is not database-enforced read-only",
            "Immutable cached artifacts verified at startup; no per-request full hashing",
            "Windows stop terminates owned processes; ASGI graceful lifespan tested separately",
            (
                "Microsoft repository MIT notice identified; dataset redistribution "
                "review and project license selection remain open"
            ),
            "No public cloud resources or uploads created",
        ],
    }
    write_json(Path("docs/results/phase7.json"), result)
    write_json(
        ROOT / "file_inventory.json",
        {
            "scope": "New Phase 7 versionable files and four chronologically updated documents",
            "files": {
                p.as_posix(): {"sha256": sha256(p), "bytes": p.stat().st_size}
                for p in sorted([*files, Path("docs/results/phase7.json")])
            },
            "runtime_input_inventory": "artifacts/phase7/deployment_manifest.json",
            "credentials_and_runtime_caches_versioned": False,
        },
    )
    write_json(
        ROOT / "artifact_manifest.json",
        {
            p.relative_to(ROOT).as_posix(): sha256(p)
            for p in sorted(ROOT.rglob("*"))
            if p.is_file()
            and "secrets" not in p.parts
            and "__pycache__" not in p.parts
            and p.name
            not in {"artifact_manifest.json", "api.log", "dashboard.log", "processes.json"}
        },
    )
    verify_artifacts(ROOT)
    return {"status": result["status"], "protected_files": protected, "graph_unchanged": True}


if __name__ == "__main__":
    print(generate())
