"""Registered one-pass native HTTP and Streamlit AppTest performance cohort."""

import hashlib
import os
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import psutil

from factorygraph.io import sha256
from factorygraph.phase6.common import digest, read_json, save_new
from factorygraph.phase7.runtime import project

ROOT = Path("artifacts/phase7")


def run():
    if (ROOT / "pilot.json").exists():
        raise ValueError("Registered pilot already exists; no outcome-driven replacement")
    registration = read_json(ROOT / "registration.json")
    for name, expected in registration["contract_sha256"].items():
        if sha256(Path(name)) != expected:
            raise ValueError("Frozen Phase 7 contract changed")
    paths = [
        *Path("src/factorygraph/phase7").glob("*.py"),
        *Path("apps/factorygraph_dashboard").glob("*.py"),
    ]
    save_new(ROOT / "implementation_freeze.json", {p.as_posix(): sha256(p) for p in paths})
    token = (ROOT / "secrets/operator.token").read_text().strip()
    headers = {"Authorization": "Bearer " + token}
    base = "http://127.0.0.1:18080/api/v1"
    rows = []
    with httpx.Client(headers=headers, timeout=125) as client:
        for name in ["new_alert", "cooldown", "non_alert", "missing_forecast"]:
            expected = project(read_json(f"docs/examples/phase6/{name}.json"))
            request = expected["request"]
            started = time.perf_counter()
            r = client.get(
                base + f"/cases/{request['machine_id']}",
                params={"snapshot_time": request["snapshot"]},
            )
            elapsed = time.perf_counter() - started
            assert r.status_code == 200 and r.json()["report"] == expected
            rows.append(
                {
                    "scenario": name,
                    "status": r.status_code,
                    "http_seconds": elapsed,
                    "case_id": expected["case_id"],
                    "exact_phase6_projection_parity": True,
                }
            )
        hashes = []
        for _ in range(5):
            started = time.perf_counter()
            r = client.get(base + "/cases/17", params={"snapshot_time": "2015-10-15T00:00Z"})
            assert r.status_code == 200
            hashes.append(digest(r.json()["report"]))
            rows.append(
                {
                    "scenario": "sequential",
                    "status": r.status_code,
                    "http_seconds": time.perf_counter() - started,
                }
            )
        assert len(set(hashes)) == 1
        barrier = threading.Barrier(3)

        def simultaneous(_):
            barrier.wait()
            started = time.perf_counter()
            response = client.get(base + "/cases/17", params={"snapshot_time": "2015-10-15T00:00Z"})
            assert response.status_code in {200, 503}
            return {
                "scenario": "concurrent",
                "status": response.status_code,
                "http_seconds": time.perf_counter() - started,
            }

        with ThreadPoolExecutor(max_workers=3) as pool:
            rows.extend(pool.map(simultaneous, range(3)))
        fleet = []
        for machines in [[1, 17, 42], list(range(1, 101))]:
            started = time.perf_counter()
            r = client.post(
                base + "/fleet/replay", json={"snapshot": "2015-10-15T00:00Z", "machines": machines}
            )
            elapsed = time.perf_counter() - started
            assert r.status_code == 200, r.text[:200]
            assert len(r.json()["reports"]) == len(machines)
            fleet.append(
                {
                    "machines": len(machines),
                    "status": r.status_code,
                    "http_seconds": elapsed,
                    "response_bytes": len(r.content),
                    "response_sha256": hashlib.sha256(r.content).hexdigest(),
                }
            )
        metrics = client.get(base + "/metrics").json()
        assert client.get("http://127.0.0.1:18501/_stcore/health").status_code == 200
    from streamlit.testing.v1 import AppTest

    os.environ["FG7_DASHBOARD_TOKEN_FILE"] = str((ROOT / "secrets/operator.token").resolve())
    os.environ["FG7_API_URL"] = "http://127.0.0.1:18080"
    started = time.perf_counter()
    app = AppTest.from_file(
        Path("apps/factorygraph_dashboard/app.py").resolve(), default_timeout=60
    ).run()
    first = time.perf_counter() - started
    assert not app.exception
    started = time.perf_counter()
    app.sidebar.radio[0].set_value("Machine analysis").run()
    interaction = time.perf_counter() - started
    assert not app.exception
    processes = read_json(ROOT / "processes.json")
    memory = {
        name: psutil.Process(value["pid"]).memory_info().rss for name, value in processes.items()
    }
    database = []
    for process in psutil.process_iter(["name", "memory_info"]):
        if "java" in process.info["name"].lower():
            database.append({"rss_bytes": process.info["memory_info"].rss})
    sequential = [r["http_seconds"] for r in rows if r["scenario"] == "sequential"]
    result = {
        "status": "passed_native_bounded_pilot",
        "date": "2026-11-15",
        "requests": rows,
        "fleet": fleet,
        "sequential_http_seconds": {
            "median": statistics.median(sequential),
            "max": max(sequential),
        },
        "api_metrics": metrics,
        "frontend": {
            "framework": "Streamlit AppTest with actual authenticated HTTP API",
            "initial_render_seconds": first,
            "machine_page_interaction_seconds": interaction,
            "browser_paint_latency_measured": False,
        },
        "rss_bytes": memory,
        "java_processes_rss_observed": database,
        "result_cache": False,
        "frontend_session_response_reuse": (
            "Keyed machine/time/mode state; manual refresh; "
            "AppTest measurement starts a fresh session"
        ),
        "container_execution": "not_executed_docker_unavailable",
        "browser_visual_qa": "unavailable_computer_browser_host",
    }
    save_new(ROOT / "pilot.json", result)
    return {"status": result["status"], "fleet": fleet, "rss_bytes": memory}


if __name__ == "__main__":
    print(run())
