"""Seal separately executed console evidence. Never fabricate tests or refresh old results."""

import argparse
import json
import re
from pathlib import Path

import httpx
import psutil

from factorygraph.io import sha256
from factorygraph.phase6.common import read_json, save_new


def finalize(root, output):
    browser = read_json(root / "browser-final/browser_results.json")
    fault = read_json(root / "browser-fault-r4/browser_results.json")
    quality = read_json(root / "quality-final/browser_results.json")
    preservation = read_json(root / "preservation.json")
    regressions = read_json(root / "original-regressions/test_results.json")
    release = read_json(root / "original-regressions/release_checks.json")
    security = read_json(root / "security-contract-final/test.json")
    assert read_json(root / "final_source_checks.json")["passed"]
    for value in [browser, fault, quality]:
        assert value["status"] == "PASS" and not value["security_findings"]
        assert not any(entry["type"] == "pageerror" for entry in value["console"])
    assert preservation["status"] == "PASS" and release["passed"]
    assert security["returncode"] == 0 and "pass 2" in security["output"]
    for name in ["typecheck", "build"]:
        assert read_json(root / f"build-final/{name}.json")["returncode"] == 0
    tests = {}
    for name, value in regressions.items():
        assert value["returncode"] == value["dependency_returncode"] == 0
        match = re.search(r"(\d+) passed(?:, (\d+) skipped)?", value["summary"][0])
        tests[name] = {"passed": int(match[1]), "skipped": int(match[2] or 0)}
    assert tests["phase7"] == {"passed": 174, "skipped": 0}
    assert all(
        read_json(root / f"fault-control-r4/{mode}-closed.json")["genuine_lifespan_closed"]
        for mode in ["fault", "gallery"]
    )
    protected = read_json(root / "protected.json")
    assert len(protected) == preservation["protected_files"]
    original_ui = "apps/factorygraph_dashboard/app.py"
    assert sha256(Path(original_ui)) == protected[original_ui]
    app = Path("apps/factorygraph_console")
    source_paths = {
        p
        for p in app.rglob("*")
        if p.is_file()
        and not any(part in {"node_modules", ".next"} for part in p.parts)
        and p.name != "tsconfig.tsbuildinfo"
        and not p.name.startswith(".env")
    }
    source_paths.update(Path("scripts").glob("operations_console*.py"))
    source_paths.update(Path("docs").glob("OPERATIONS_CONSOLE_V2_*.md"))
    sources = {
        p.as_posix(): {"sha256": sha256(p), "bytes": p.stat().st_size} for p in sorted(source_paths)
    }
    secret_files = [
        "artifacts/phase7/secrets/operator.token",
        "artifacts/phase7/secrets/viewer.token",
        ".env.phase4",
        "artifacts/operations_console_v2/secrets/operator.login",
        "artifacts/operations_console_v2/secrets/viewer.login",
    ]
    secrets = [Path(name).read_bytes().strip() for name in secret_files]
    static_files = [p for p in (app / ".next/static").rglob("*") if p.is_file()]
    for path in [*source_paths, *static_files]:
        data = path.read_bytes()
        assert not any(value and value in data for value in secrets), path.as_posix()
    audit = json.loads((root / "npm-audit.json").read_text(encoding="utf-8-sig"))
    assert audit["metadata"]["vulnerabilities"]["total"] == 0
    credentials = Path("artifacts/phase7/secrets/operator.token").read_text().strip()
    with httpx.Client(trust_env=False, timeout=10) as client:
        health = {
            "console": client.get("http://localhost:18601/api/session").status_code,
            "favicon": client.get("http://localhost:18601/favicon.ico").status_code,
            "original_Streamlit": client.get("http://127.0.0.1:18501/_stcore/health").status_code,
            "original_API_readiness": client.get(
                "http://127.0.0.1:18080/api/v1/health/ready",
                headers={"Authorization": "Bearer " + credentials},
            ).status_code,
        }
    assert set(health.values()) == {200}
    record = read_json(root / "runtime-handoff/server-18601.json")
    process = psutil.Process(record["pid"])
    assert process.create_time() == record["created"]
    family = [process, *process.children(recursive=True)]
    resources = [
        {
            "pid": p.pid,
            "name": p.name(),
            "rss_bytes": p.memory_info().rss,
            "cumulative_cpu_seconds": p.cpu_times().user + p.cpu_times().system,
        }
        for p in family
    ]
    bindings = [
        {"address": c.laddr.ip, "port": c.laddr.port}
        for c in psutil.net_connections("tcp")
        if c.status == "LISTEN" and c.laddr.port in [18601, 18603, 18604, 18605, 18082, 18083]
    ]
    assert bindings == [{"address": "127.0.0.1", "port": 18601}]
    save_new(
        root / "handoff_observation.json",
        {
            "health": health,
            "process_family": resources,
            "scope": "Point-in-time process observations; not isolated peaks or per-request CPU",
            "bindings": bindings,
        },
    )
    evidence = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in {"artifact_manifest.json", "file_inventory.json"}:
            continue
        if path == root / "runtime-handoff/server-18601.log":
            continue  # The active log may grow after handoff.
        data = path.read_bytes()
        assert not any(value and value in data for value in secrets), path.as_posix()
        evidence[path.relative_to(root).as_posix()] = sha256(path)
    save_new(root / "artifact_manifest.json", evidence)
    result = {
        "date": "2026-11-16",
        "milestone": "Operations Console v2",
        "status": "verified_local_native",
        "gates_A_to_J": "PASS in documented local scope",
        "public_deployment": False,
        "url": "http://localhost:18601",
        "original_Streamlit_preserved": True,
        "primary_predictor": "Phase 1 calibrated LightGBM / exact Phase 5 A0",
        "threshold": 0.9996602309282403,
        "cooldown_hours": 24,
        "phase5_replacement": "NO-GO",
        "default_runtime": "Original B; C1 stays optional",
        "protected_files": preservation["protected_files"],
        "preservation_evidence_sha256": sha256(root / "preservation.json"),
        "graph": preservation["graph"],
        "tests": tests,
        "node_tests": 2,
        "browser": {
            "version": browser["browser"],
            "full_grouped_checks": len(browser["checks"]),
            "full_captures": len(browser["screenshots"]),
            "fault_captures": len(fault["screenshots"]),
            "quality_grouped_checks": len(quality["checks"]),
            "quality_captures": len(quality["screenshots"]),
            "unhandled_page_errors": 0,
            "observed_backend_credential_leaks": 0,
        },
        "evidence_roots": {
            "full": "browser-final",
            "fault": "browser-fault-r4",
            "quality": "quality-final",
            "regressions": "original-regressions",
            "security": "security-contract-final",
        },
        "accessibility_certified": False,
        "npm_audit_known_vulnerabilities": 0,
        "client_static_files_scanned": len(static_files),
        "health": health,
        "process_observation": resources,
        "next_build_seconds": read_json(root / "build-final/build.json")["seconds"],
        "native_startup_poll_seconds": read_json(root / "runtime-handoff/ready-18601.json")[
            "seconds"
        ],
        "new_matched_performance_study": False,
        "run_dir": root.as_posix(),
        "source_inventory": sources,
        "artifact_manifest_sha256": sha256(root / "artifact_manifest.json"),
        "evidence_files": len(evidence),
        "active_log_excluded": "runtime-handoff/server-18601.log",
        "limitations": [
            "Synthetic retrospective demonstration, no real-machinery validation",
            "No WCAG/security certification",
            "Local identity/localhost cookies; public identity/TLS and rights review remain open",
            "No Docker, public hosting, new model or subsequent research phase",
        ],
    }
    save_new(output, result)
    save_new(
        root / "file_inventory.json",
        {**sources, output.as_posix(): {"sha256": sha256(output), "bytes": output.stat().st_size}},
    )
    print(
        {
            "status": result["status"],
            "source_files": len(sources),
            "evidence_files": len(evidence),
            "health": health,
        }
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--report-output", type=Path)
    args = parser.parse_args()
    finalize(args.run_dir, args.report_output or args.run_dir / "results.json")
