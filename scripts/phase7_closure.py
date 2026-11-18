"""Separate closure audit/evidence; never refresh accepted Phase 7/8 results in place."""

import argparse
import hashlib
import importlib.metadata
import importlib.util
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import psutil

from factorygraph.io import sha256, verify_artifacts
from factorygraph.phase6.common import read_json, save_new
from factorygraph.phase6.evaluation import graph_integrity
from factorygraph.phase6.integrity import prediction_parity, verify_mapping


def command(args):
    p = subprocess.run(args, capture_output=True)

    def decode(raw):
        return raw.decode("utf-16le" if b"\x00" in raw else "utf-8", errors="replace").strip()

    return {
        "command": args,
        "returncode": p.returncode,
        "stdout": decode(p.stdout),
        "stderr": decode(p.stderr),
    }


def verified_mapping(mapping, amendments=None):
    amendments = amendments or {}
    assert set(amendments) <= {"apps/factorygraph_dashboard/app.py"}
    amended = []
    for name, expected in mapping.items():
        actual = sha256(Path(name))
        if actual == expected:
            continue
        record = amendments[name]
        assert expected == record["before"] and actual == record["after"], name
        assert sha256(Path(record["backup"])) == expected, name
        assert record["scientific_case_semantics_changed"] is False
        amended.append(name)
    return {"unchanged": len(mapping) - len(amended), "documented_amendments": amended}


def audit(root, amendments_path=None):
    if root.exists():
        raise ValueError("Use a fresh closure directory; never overwrite evidence")
    old = read_json("artifacts/phase8/study/protected.json")
    amendments = read_json(amendments_path) if amendments_path else {}
    verified_mapping(old, amendments)
    verify_artifacts(Path("artifacts/phase8/study"))
    p8 = read_json("docs/results/phase8.json")
    verified_mapping(p8["implementation_sha256"], amendments)
    paths = set(old) | set(p8["implementation_sha256"])
    paths.update(["docs/results/phase8.json", "artifacts/phase8/study/artifact_manifest.json"])
    paths.update(
        (Path("artifacts/phase8/study") / p).as_posix()
        for p in read_json("artifacts/phase8/study/artifact_manifest.json")
    )
    protected = {p: sha256(Path(p)) for p in sorted(paths)}
    graph = graph_integrity()
    variants = {
        "B": {p.as_posix(): sha256(p) for p in Path("src/factorygraph/phase7").glob("*.py")},
        "C1": {p.as_posix(): sha256(p) for p in Path("src/factorygraph/phase8").glob("*.py")},
        "frontend": {
            p.as_posix(): sha256(p) for p in Path("apps/factorygraph_dashboard").glob("*.py")
        },
    }
    wsl = shutil.which("wsl")
    capability = {
        "platform": platform.platform(),
        "python": sys.version,
        "physical_cpus": psutil.cpu_count(False),
        "logical_cpus": psutil.cpu_count(),
        "total_ram_bytes": psutil.virtual_memory().total,
        "available_ram_bytes": psutil.virtual_memory().available,
        "disk_free_bytes": shutil.disk_usage(".").free,
        "docker_cli": shutil.which("docker"),
        "docker_desktop_standard_path": Path(
            r"C:\Program Files\Docker\Docker\Docker Desktop.exe"
        ).exists(),
        "wsl_status": command([wsl, "--status"]) if wsl else None,
        "existing_browser_binaries": {
            str(p): p.exists()
            for p in [
                Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
                Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            ]
        },
        "accepted_environment_browser_packages": {
            n: importlib.util.find_spec(n) is not None
            for n in ["playwright", "selenium", "pytest_playwright"]
        },
        "supported_browser_tool_probe": {
            "method": "cua.getState and sky.list_apps",
            "native_error": (
                "Computer Use native pipe is unavailable: failed to connect native pipe: "
                "The system cannot find the file specified. (os error 2)"
            ),
            "browser_error": "The browser access host is unavailable",
            "js_playwright_import_error": (
                "The requested module './index.js' does not provide an export named 'default'"
            ),
        },
        "packages": {
            d.metadata["Name"]: d.version
            for d in importlib.metadata.distributions()
            if d.metadata["Name"]
        },
        "container_gate": "BLOCKED" if not shutil.which("docker") else "PENDING",
    }
    save_new(root / "protected.json", protected)
    save_new(root / "capabilities.json", capability)
    save_new(
        root / "registration.json",
        {
            "date": "2026-11-15",
            "scope": "Phase 7 closure, no new research phase",
            "variants": variants,
            "protected_count": len(protected),
            "prior_source_amendments": amendments,
            "prior_phase8_protected_count": len(old),
            "graph": graph,
            "prediction_policy_parity": prediction_parity(),
            "approved_inputs_sha256": read_json("artifacts/phase6/study/registration.json")[
                "inputs_sha256"
            ],
            "deployment_inventory_sha256": sha256(
                Path("artifacts/phase7/deployment_manifest.json")
            ),
            "case_gallery_manifest_sha256": sha256(Path("docs/examples/phase6/manifest.json")),
            "openapi_sha256": sha256(Path("configs/phase7/openapi-v1.json")),
            "capability_report_sha256": sha256(Path("docs/PHASE7_CLOSURE_CAPABILITIES.md")),
            "browser_plan": {
                "framework": "Isolated Playwright 1.65.2 using installed Edge, no browser download",
                "desktop": [1440, 1000],
                "narrow": [390, 844],
                "full_mode_url": "http://127.0.0.1:18501",
                "checks": [
                    "six_workspaces",
                    "machine_snapshot_selection",
                    "UTC",
                    "new_alert",
                    "cooldown",
                    "below_threshold",
                    "evidence_only_missing_forecast",
                    "explicit_gallery_unknown_abstention",
                    "provenance",
                    "telemetry_charts",
                    "sanitized_export",
                    "keyboard_focus",
                    "responsive_layout",
                    "errors",
                    "browser_console_network_secret_scan",
                ],
                "screenshots": "Only actual captures; secrets excluded; no saved HTML/auth headers",
                "accessibility": "Bounded keyboard/label/contrast checks, no certification",
            },
            "policy": (
                "No Docker/WSL/virtualization changes; no public upload/deployment; C1 optional"
            ),
        },
    )
    return {
        "protected_files": len(protected),
        "graph": graph,
        "container_gate": capability["container_gate"],
    }


def start(root):
    if (root / "owned_processes.json").exists():
        raise ValueError("Closure processes already recorded")
    env = os.environ.copy()
    env.update(
        {
            "FG7_OPERATOR_TOKEN_FILE": str(
                Path("artifacts/phase7/secrets/operator.token").resolve()
            ),
            "FG7_VIEWER_TOKEN_FILE": str(Path("artifacts/phase7/secrets/viewer.token").resolve()),
        }
    )
    commands = {
        mode: [
            sys.executable,
            "scripts/phase7_closure_services.py",
            "--mode",
            mode,
            "--root",
            str(root.resolve()),
        ]
        for mode in ["gallery", "fault"]
    }
    for port in range(18502, 18507):
        commands[str(port)] = [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "apps/factorygraph_dashboard/app.py",
            "--server.address",
            "127.0.0.1",
            "--server.port",
            str(port),
            "--server.headless",
            "true",
            "--browser.gatherUsageStats",
            "false",
            "--server.fileWatcherType",
            "none",
            "--server.enableXsrfProtection",
            "true",
        ]
    records = {}
    for name, cmd in commands.items():
        child = env.copy()
        if name.isdigit():
            port = int(name)
            target = {18502: 18080, 18503: 18089, 18504: 18080, 18505: 18082, 18506: 18083}[port]
            child["FG7_API_URL"] = f"http://127.0.0.1:{target}"
            token = "viewer" if port == 18502 else "operator"
            child["FG7_DASHBOARD_TOKEN_FILE"] = str(
                Path(f"artifacts/phase7/secrets/{token}.token").resolve()
            )
            if port == 18504:
                child["FG7_DASHBOARD_TOKEN_FILE"] = str(root / "nonexistent.token")
        with (root / (name + ".log")).open("x", encoding="utf-8") as stream:
            p = subprocess.Popen(
                cmd,
                env=child,
                stdout=stream,
                stderr=stream,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        records[name] = {
            "pid": p.pid,
            "created": psutil.Process(p.pid).create_time(),
            "command": cmd,
        }
    save_new(root / "owned_processes.json", records)
    token = Path("artifacts/phase7/secrets/operator.token").read_text()
    ready = False
    for _ in range(60):
        try:
            ready = all(
                httpx.get(
                    f"http://127.0.0.1:{port}/api/v1/health/ready",
                    headers={"Authorization": "Bearer " + token},
                    timeout=2,
                ).status_code
                == 200
                for port in [18082, 18083]
            )
            ready = ready and all(
                httpx.get(f"http://127.0.0.1:{port}/_stcore/health", timeout=2).status_code == 200
                for port in range(18502, 18507)
            )
            if ready:
                break
        except httpx.HTTPError:
            pass
        time.sleep(1)
    save_new(
        root / "native_qa_service_readiness.json",
        {
            "ready": ready,
            "ports": [18082, 18083, *range(18502, 18507)],
            "original_services_unchanged": True,
            "fault_scope": "Explicit closure-only injection, not original DB shutdown",
        },
    )
    if not ready:
        raise RuntimeError("Closure-only service startup failed; retain logs")
    return {"ready": ready, "owned_services": len(records)}


def stop(root):
    (root / "stop-services").touch()
    records = read_json(root / "owned_processes.json")
    for name, r in records.items():
        try:
            p = psutil.Process(r["pid"])
            if abs(p.create_time() - r["created"]) > 0.01:
                raise ValueError("PID identity changed")
            cmd = " ".join(p.cmdline())
            if (
                "phase7_closure_services.py" not in cmd
                and "apps/factorygraph_dashboard/app.py" not in cmd
            ):
                raise ValueError("Refuse to stop an unrelated process")
            if not name.isdigit():
                try:
                    p.wait(timeout=15)
                    continue
                except psutil.TimeoutExpired:
                    pass
            owned = [p, *p.children(recursive=True)]
            for child in reversed(owned):
                try:
                    child.terminate()
                except psutil.NoSuchProcess:
                    pass
            _, alive = psutil.wait_procs(owned, timeout=15)
            if alive:
                raise RuntimeError("Closure-owned processes still running")
        except psutil.NoSuchProcess:
            pass
    save_new(
        root / "native_qa_services_closed.json",
        {
            "owned_services_stopped": True,
            "gallery_graceful_close": read_json(root / "gallery-closed.json"),
            "fault_graceful_close": read_json(root / "fault-closed.json"),
            "original_graph_untouched": True,
        },
    )
    return {"owned_services_stopped": True}


def api(root, browser_run):
    from factorygraph.phase6.schema import CaseReport
    from factorygraph.phase7.runtime import project

    token = Path("artifacts/phase7/secrets/operator.token").read_text().strip()
    viewer = Path("artifacts/phase7/secrets/viewer.token").read_text().strip()
    credentials = [token, viewer, Path(".env.phase4").read_text().strip()]
    records = []
    status = "FAIL"

    def request(client, name, method, path, expected, **kwargs):
        started = time.perf_counter()
        r = client.request(method, path, **kwargs)
        record = {
            "name": name,
            "status": r.status_code,
            "expected": expected,
            "seconds": time.perf_counter() - started,
            "body_sha256": hashlib.sha256(r.content).hexdigest(),
        }
        records.append(record)
        assert r.status_code == expected, name
        assert not any(s and s.encode() in r.content for s in credentials), "Secret in response"
        return r.json()

    try:
        with httpx.Client(
            base_url="http://127.0.0.1:18080/api/v1", timeout=125, trust_env=False
        ) as c:
            request(c, "anonymous_readiness", "GET", "/health/ready", 401)
            request(
                c,
                "invalid_auth",
                "GET",
                "/metadata",
                401,
                headers={"Authorization": "Bearer invalid"},
            )
            c.headers["Authorization"] = "Bearer " + token
            request(c, "authenticated_readiness", "GET", "/health/ready", 200)
            for name in ["new_alert", "cooldown", "non_alert", "missing_forecast"]:
                expected = project(read_json(f"docs/examples/phase6/{name}.json"))
                req = expected["request"]
                actual = request(
                    c,
                    name,
                    "GET",
                    f"/cases/{req['machine_id']}",
                    200,
                    params={"snapshot_time": req["snapshot"]},
                )["report"]
                CaseReport.model_validate(actual)
                assert actual == expected
                records[-1]["exact_phase6_projection"] = True
            request(
                c,
                "unknown_machine",
                "GET",
                "/cases/10001",
                404,
                params={"snapshot_time": "2015-10-15T00:00Z"},
            )
            request(
                c,
                "unsupported_timestamp",
                "GET",
                "/cases/1",
                404,
                params={"snapshot_time": "2015-10-16T12:01Z"},
            )
            request(
                c,
                "malformed_UTC",
                "GET",
                "/cases/1",
                422,
                params={"snapshot_time": "2015-10-16T12:00:00"},
            )
            request(
                c,
                "malformed_JSON",
                "POST",
                "/fleet/replay",
                422,
                content=b"{bad",
                headers={"Content-Type": "application/json"},
            )
            request(c, "oversized_body", "POST", "/fleet/replay", 413, content=b"x" * 17000)
            request(c, "path_injection", "GET", "/machines?path=../../.env.phase4", 422)
            request(c, "duplicate_query", "GET", "/machines?limit=1&limit=2", 422)
            schema = request(c, "schema", "GET", "/schema", 200)
            assert schema == read_json("configs/phase7/openapi-v1.json")
            c.headers["Authorization"] = "Bearer " + viewer
            request(
                c,
                "viewer_forbidden_machine",
                "GET",
                "/cases/1",
                403,
                params={"snapshot_time": "2015-10-16T12:00Z"},
            )
            request(
                c,
                "viewer_allowed_machine",
                "GET",
                "/cases/17",
                200,
                params={"snapshot_time": "2015-10-15T00:00Z"},
            )
            request(c, "viewer_metrics_forbidden", "GET", "/metrics", 403)
            machines = request(c, "viewer_list", "GET", "/machines", 200)
            assert [r["machine_id"] for r in machines["items"]] == [17]
        with httpx.Client(
            base_url="http://127.0.0.1:18082/api/v1",
            timeout=125,
            trust_env=False,
            headers={"Authorization": "Bearer " + token},
        ) as c:
            body = request(
                c,
                "explicit_gallery_abstention",
                "GET",
                "/cases/10001",
                200,
                params={"snapshot_time": "2015-10-15T00:00Z"},
            )
            assert body["mode"] == "gallery" and body["report"]["status"] == "abstained"
        with httpx.Client(
            base_url="http://127.0.0.1:18083/api/v1",
            timeout=125,
            trust_env=False,
            headers={"Authorization": "Bearer " + token},
        ) as c:
            flag = root / "graph-unavailable"
            flag.touch()
            try:
                request(c, "injected_graph_unavailable", "GET", "/health/ready", 503)
                body = request(
                    c,
                    "injected_graph_no_fallback",
                    "GET",
                    "/cases/1",
                    503,
                    params={"snapshot_time": "2015-10-16T12:00Z"},
                )
                assert "report" not in body
            finally:
                flag.unlink()
            flag = root / "slow-case"
            flag.touch()
            try:
                request(
                    c,
                    "injected_timeout",
                    "GET",
                    "/cases/17",
                    504,
                    params={"snapshot_time": "2015-10-15T00:00Z"},
                )
                request(
                    c,
                    "timeout_slot_remains_busy",
                    "GET",
                    "/cases/17",
                    503,
                    params={"snapshot_time": "2015-10-15T00:00Z"},
                )
            finally:
                flag.unlink()
            time.sleep(1.1)
            flag = root / "busy-case"
            flag.touch()
            barrier = threading.Barrier(3)

            def busy(_):
                barrier.wait()
                r = c.get("/cases/17", params={"snapshot_time": "2015-10-15T00:00Z"})
                return r.status_code

            try:
                with ThreadPoolExecutor(max_workers=3) as pool:
                    statuses = sorted(pool.map(busy, range(3)))
                assert statuses == [200, 503, 503]
                records.append(
                    {
                        "name": "bounded_busy",
                        "statuses": statuses,
                        "scope": "Controlled delay, genuine report",
                    }
                )
            finally:
                flag.unlink()
            count = 0
            for _ in range(241):
                r = c.get("/metadata")
                if r.status_code == 429:
                    count += 1
                else:
                    assert r.status_code == 200
            assert count > 0
            records.append({"name": "rate_limiting", "requests": 241, "HTTP_429": count})
        downloaded = read_json(browser_run / "download-new-alert.json")
        expected = project(read_json("docs/examples/phase6/new_alert.json"))
        CaseReport.model_validate(downloaded)
        assert downloaded == expected
        invalid = dict(downloaded)
        invalid.pop("case_id")
        from pydantic import ValidationError

        try:
            CaseReport.model_validate(invalid)
        except ValidationError:
            pass
        else:
            raise AssertionError("Invalid downloaded report accepted")
        records.append(
            {"name": "download_exact_schema_parity_invalid_copy_rejected", "status": "PASS"}
        )
        status = "PASS"
    finally:
        save_new(
            root / "api_acceptance.json",
            {
                "status": status,
                "checks": records,
                "faults": "Controlled failure/delay in owned full engine; original DB not stopped",
                "scientific_outputs_or_default_configuration_modified": False,
            },
        )
    return {"api_checks": len(records), "status": "PASS"}


def review(root):
    import yaml

    manifest = read_json("artifacts/phase7/deployment_manifest.json")
    for path, record in manifest["files"].items():
        assert sha256(Path(path)) == record["sha256"]
        assert sha256(Path("artifacts/phase7/runtime") / path) == record["sha256"]
        assert not any(part.startswith(".venv") for part in Path(path).parts)
        assert not path.startswith("data/models/")
    compose = yaml.safe_load(Path("deployment/docker-compose.yml").read_text())
    services = compose["services"]
    assert "ports" not in services["neo4j"]
    for name in ["api", "dashboard"]:
        s = services[name]
        assert all(p.startswith("127.0.0.1:") for p in s["ports"])
        assert s["read_only"] and s["cap_drop"] == ["ALL"] and s["secrets"]
    assert not services["dashboard"].get("volumes")
    frontend = Path("deployment/dashboard/Dockerfile").read_text()
    assert "COPY apps/factorygraph_dashboard /app" in frontend
    assert "COPY . " not in frontend
    assert "neo4j" not in Path("apps/factorygraph_dashboard/client.py").read_text().lower()
    observations = {
        "runtime_files_verified": len(manifest["files"]),
        "runtime_bytes": manifest["bytes"],
        "runtime_original_and_staging_hashes_match": True,
        "weights_environments_secrets_excluded_from_runtime_inventory": True,
        "frontend_has_no_raw_backend_data_mount": True,
        "frontend_talks_only_to_authenticated_API": True,
        "compose_static_constraints_checked": True,
        "container_execution": "BLOCKED",
        "native_listeners": [
            {"address": c.laddr.ip, "port": c.laddr.port}
            for c in psutil.net_connections("tcp")
            if c.status == "LISTEN" and c.laddr.port in [17687, 18080, 18501]
        ],
        "root_publication_license_present": any(
            Path(p).exists() for p in ["LICENSE", "LICENSE.md", "COPYING"]
        ),
        "microsoft_notice_sha256": sha256(Path("artifacts/phase7/legal/LICENSE")),
        "dataset_specific_redistribution_permission_established": False,
        "public_identity_TLS_review_complete": False,
        "vulnerability_or_image_scan_executed": False,
        "findings": [
            "Docker/WSL absent: Linux, images, bootstrap/restart and resource gates blocked",
            "Local bearer roles/loopback HTTP need separate public identity/TLS review",
            "Project license and dataset redistribution approval unresolved",
            "Broad src/** Docker context rule does not explicitly exclude source bytecode caches",
            "Liveness-only image healthcheck does not replace authenticated readiness acceptance",
            "Dependency consistency checks are not a vulnerability audit",
        ],
    }
    assert all(r["address"] in ["127.0.0.1", "::1"] for r in observations["native_listeners"])
    save_new(root / "artifact_security_review.json", observations)
    return {"runtime_files_verified": len(manifest["files"]), "public_release": "NOT READY"}


def verify(root):
    registration = read_json(root / "registration.json")
    amendments = read_json(root / "source_amendments.json")
    preservation = verified_mapping(read_json(root / "protected.json"), amendments)
    for name, mapping in registration["variants"].items():
        verified_mapping(mapping, amendments if name == "frontend" else None)
    verify_mapping(Path("."), registration["approved_inputs_sha256"])
    graph = graph_integrity()
    assert graph == registration["graph"]
    parity = prediction_parity()
    assert parity == registration["prediction_policy_parity"]
    verify_artifacts(Path("artifacts/phase8/study"))
    result = {
        "status": "PASS",
        "preservation": preservation,
        "protected_original_count": registration["protected_count"],
        "amendments": amendments,
        "B_and_C1_backend_unchanged": True,
        "approved_inputs_unchanged": True,
        "original_graph": graph,
        "baseline_A0_prediction_policy_parity": parity,
        "prior_phase8_artifact_manifest_verified": True,
    }
    save_new(root / "preservation.json", result)
    return result


def finalize(root, browser_run, verification_run, report_output):
    browser = read_json(browser_run / "browser_results.json")
    protocol = read_json(root / "browser-protocol/browser_results.json")
    api_result = read_json(root / "native-fixed/api_acceptance.json")
    preservation = read_json(root / "preservation.json")
    tests = read_json(verification_run / "test_results.json")
    checks = read_json(verification_run / "release_checks.json")
    package_directory = verification_run / "dist"
    if (verification_run / "post-documentation_checks.json").exists():
        post = read_json(verification_run / "post-documentation_checks.json")
        assert post["passed"]
        package_directory = Path(post["package_directory"])
    security = read_json(root / "artifact_security_review.json")
    closed = read_json(root / "native-fixed/native_qa_services_closed.json")
    visual = read_json(root / "visual_review.json")
    assert browser["status"] == protocol["status"] == api_result["status"] == "PASS"
    assert preservation["status"] == "PASS" and checks["passed"]
    assert not browser["security_findings"] and not protocol["security_findings"]
    assert closed["owned_services_stopped"] and visual["status"] == "PASS_bounded_visual_scope"
    assert graph_integrity() == preservation["original_graph"]
    assert (
        verified_mapping(
            read_json(root / "protected.json"), read_json(root / "source_amendments.json")
        )
        == preservation["preservation"]
    )
    listeners = [
        {"address": c.laddr.ip, "port": c.laddr.port}
        for c in psutil.net_connections("tcp")
        if c.status == "LISTEN" and c.laddr.port in [17687, 18080, 18501, *range(18502, 18507)]
    ]
    assert {r["port"] for r in listeners} == {17687, 18080, 18501}
    assert all(r["address"] in {"127.0.0.1", "::1"} for r in listeners)
    token = Path("artifacts/phase7/secrets/operator.token").read_text().strip()
    with httpx.Client(trust_env=False, timeout=30) as client:
        live = client.get("http://127.0.0.1:18080/api/v1/health/live").status_code
        ready = client.get(
            "http://127.0.0.1:18080/api/v1/health/ready",
            headers={"Authorization": "Bearer " + token},
        ).status_code
        ui = client.get("http://127.0.0.1:18501/_stcore/health").status_code
    assert live == ready == ui == 200
    for record in read_json(root / "source_amendments.json").values():
        assert sha256(Path("apps/factorygraph_dashboard/app.py")) == record["after"]
    totals = {}
    for name, record in tests.items():
        assert record["returncode"] == record["dependency_returncode"] == 0
        log = read_json(verification_run / f"regressions/{name}.json")
        match = re.search(r"(\d+) passed(?:, (\d+) skipped)?", log["output"])
        assert match
        totals[name] = {"passed": int(match[1]), "skipped": int(match[2] or 0)}
    assert totals["phase7"] == {"passed": 174, "skipped": 0}
    packages = {}
    for path in package_directory.glob("*"):
        if path.suffix == ".whl":
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                for source in Path("src/factorygraph").rglob("*.py"):
                    assert archive.read(source.relative_to("src").as_posix()) == source.read_bytes()
        elif path.name.endswith(".tar.gz"):
            with tarfile.open(path) as archive:
                names = archive.getnames()
        else:
            raise AssertionError("Unexpected package")
        assert not any(
            part in {"artifacts", "data"} or part.startswith((".env", ".venv"))
            for name in names
            for part in Path(name).parts
        )
        packages[path.name] = {"sha256": sha256(path), "members": len(names)}
    assert len(packages) == 2
    save_new(root / "package_inventory.json", packages)
    evidence = {}
    credentials = [
        Path(p).read_bytes().strip()
        for p in [
            "artifacts/phase7/secrets/operator.token",
            "artifacts/phase7/secrets/viewer.token",
            ".env.phase4",
        ]
    ]
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in {"artifact_manifest.json", "file_inventory.json"}:
            continue
        content = path.read_bytes()
        assert not any(value and value in content for value in credentials), path.as_posix()
        evidence[path.relative_to(root).as_posix()] = {
            "sha256": sha256(path),
            "bytes": len(content),
        }
    save_new(root / "artifact_manifest.json", evidence)
    implementation_paths = [
        *Path("scripts").glob("phase7_closure*.py"),
        *Path("docs").glob("PHASE7_*CLOSURE*.md"),
        Path("docs/PHASE7_BROWSER_QA.md"),
        Path("docs/PHASE7_CONTAINER_ACCEPTANCE.md"),
        Path("docs/PHASE7_RELEASE_READINESS.md"),
        Path("requirements/phase7-closure-browser.lock"),
        Path("apps/factorygraph_dashboard/app.py"),
    ]
    implementation = {p.as_posix(): sha256(p) for p in sorted(set(implementation_paths))}
    for name in implementation:
        assert not any(value and value in Path(name).read_bytes() for value in credentials), name
    result = {
        "date": "2026-11-15",
        "scope": "Phase 7 closure; no new research phase or publication",
        "run_dir": root.as_posix(),
        "outcomes": {
            "A_native_browser_QA": "PASS",
            "B_container_build_runtime": "BLOCKED",
            "C_public_release": "NOT READY",
        },
        "primary_predictor": "Phase 1 calibrated LightGBM, exactly Phase 5 A0",
        "threshold": 0.9996602309282403,
        "cooldown_hours": 24,
        "phase5_replacement": "NO-GO",
        "C1": "Optional native runtime; default B unchanged; no container experiment",
        "browser": {
            "version": browser["browser"],
            "channel": browser["channel"],
            "headless": browser["headless"],
            "functional_checks": len(browser["checks"]),
            "screenshots": len(browser["actual_screenshots"]),
            "evidence": browser_run.as_posix(),
            "protocol_checks": len(protocol["checks"]),
            "websocket_frames_inspected": protocol["websocket_frames_inspected_in_memory"],
            "security_findings": [],
            "accessibility_certified": False,
        },
        "api_export_checks": len(api_result["checks"]),
        "tests": totals,
        "regression_evidence": verification_run.as_posix(),
        "preservation": preservation,
        "security": security,
        "container_measurements": None,
        "container_blocker": "Docker CLI/Desktop absent; WSL is not installed",
        "benchmark_note": "No new matched performance study; original Phase 7/8 evidence preserved",
        "package_inventory": packages,
        "package_directory": package_directory.as_posix(),
        "owned_test_services_stopped": True,
        "original_loopback_demo_and_graph_retained": True,
        "final_listeners": listeners,
        "final_HTTP_health": {"liveness": live, "authenticated_readiness": ready, "UI": ui},
        "implementation_sha256": implementation,
        "artifact_manifest_sha256": sha256(root / "artifact_manifest.json"),
        "evidence_files": len(evidence),
    }
    save_new(report_output, result)
    inventory = dict(implementation)
    inventory[report_output.as_posix()] = sha256(report_output)
    save_new(root / "file_inventory.json", inventory)
    return {"outcomes": result["outcomes"], "tests": totals, "evidence_files": len(evidence)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage", choices=["audit", "start", "stop", "api", "review", "verify", "finalize"]
    )
    parser.add_argument("--run-dir", type=Path, default=Path("artifacts/phase7_closure/study"))
    parser.add_argument("--source-amendments", type=Path)
    parser.add_argument("--browser-run", type=Path)
    parser.add_argument("--verification-run", type=Path)
    parser.add_argument("--report-output", type=Path)
    args = parser.parse_args()
    if args.stage == "audit":
        print(audit(args.run_dir, args.source_amendments))
    elif args.stage in {"api", "finalize"}:
        if args.browser_run is None:
            parser.error("This stage requires --browser-run containing genuine browser evidence")
        if args.stage == "finalize":
            if args.verification_run is None:
                parser.error("finalize requires --verification-run")
            print(
                finalize(
                    args.run_dir,
                    args.browser_run,
                    args.verification_run,
                    args.report_output or args.run_dir / "results.json",
                )
            )
        else:
            print(api(args.run_dir, args.browser_run))
    else:
        print(globals()[args.stage](args.run_dir))
