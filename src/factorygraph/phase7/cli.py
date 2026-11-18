"""Local startup/shutdown and frozen-contract registration; no cloud operations."""

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

import httpx
import psutil

from factorygraph.io import sha256
from factorygraph.phase6.common import read_json, save_new

ROOT = Path("artifacts/phase7")


def credentials():
    root = ROOT / "secrets"
    root.mkdir(parents=True, exist_ok=True)
    for name in ["operator", "viewer", "neo4j-demo"]:
        path = root / (name + ".token")
        if not path.exists():
            with path.open("x", encoding="utf-8") as stream:
                stream.write(secrets.token_urlsafe(48))
    auth = root / "neo4j-auth.txt"
    if not auth.exists():
        auth.write_text("neo4j/" + (root / "neo4j-demo.token").read_text(), encoding="utf-8")
    if os.name != "nt":
        for path in root.iterdir():
            path.chmod(0o600)
    return {"status": "credential_files_ready", "directory": str(root), "values_disclosed": False}


def register():
    from factorygraph.phase7.api import app

    policies = [
        "docs/PHASE7_ARCHITECTURE.md",
        "docs/PHASE7_SECURITY.md",
        "docs/PHASE7_TEST_PROTOCOL.md",
        "docs/PHASE7_API.md",
        "configs/phase7/local.yaml",
    ]
    schema_path = Path("configs/phase7/openapi-v1.json")
    save_new(schema_path, app.openapi())
    paths = [*policies, schema_path.as_posix()]
    record = {
        "date": "2026-11-15",
        "registered_before_acceptance_and_performance": True,
        "contract_sha256": {p: sha256(Path(p)) for p in paths},
        "single_worker": True,
        "concurrency": 1,
        "case_deadline_seconds": 120,
        "result_cache": False,
        "docker_status": "unavailable_not_executed",
    }
    save_new(ROOT / "registration.json", record)
    return {"status": "registered"}


def start(mode):
    from factorygraph.phase7.config import load_settings

    cfg = load_settings()
    if (ROOT / "processes.json").exists():
        raise ValueError("A run record exists; stop it explicitly before another startup")
    credentials()
    env = os.environ.copy()
    env.update(
        {
            "FG7_MODE": mode,
            "FG7_OPERATOR_TOKEN_FILE": str((ROOT / "secrets/operator.token").resolve()),
            "FG7_VIEWER_TOKEN_FILE": str((ROOT / "secrets/viewer.token").resolve()),
            "FG7_DASHBOARD_TOKEN_FILE": str((ROOT / "secrets/operator.token").resolve()),
            "FG7_API_URL": "http://127.0.0.1:18080",
            "PYTHONUNBUFFERED": "1",
        }
    )
    if mode == "full" and not (
        env.get("FACTORYGRAPH_NEO4J_PASSWORD") or env.get("FG7_NEO4J_PASSWORD_FILE")
    ):
        raise ValueError("Configure the existing local graph credential first")
    commands = {
        "api": [sys.executable, "-m", "factorygraph.phase7.server"],
        "dashboard": [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "apps/factorygraph_dashboard/app.py",
            "--server.address",
            "127.0.0.1",
            "--server.port",
            str(cfg.dashboard_port),
            "--server.headless",
            "true",
            "--browser.gatherUsageStats",
            "false",
            "--server.fileWatcherType",
            "none",
            "--server.enableXsrfProtection",
            "true",
        ],
    }
    records = {}
    start_time = time.perf_counter()
    for name, command in commands.items():
        log = ROOT / f"{name}.log"
        with log.open("a", encoding="utf-8") as stream:
            kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
            process = subprocess.Popen(command, env=env, stdout=stream, stderr=stream, **kwargs)
        records[name] = {
            "pid": process.pid,
            "created": psutil.Process(process.pid).create_time(),
            "command": command,
        }
    save_new(ROOT / "processes.json", records)
    token = (ROOT / "secrets/operator.token").read_text()
    good = False
    for _ in range(60):
        try:
            api = httpx.get(
                "http://127.0.0.1:18080/api/v1/health/ready",
                headers={"Authorization": "Bearer " + token},
                timeout=3,
            )
            ui = httpx.get("http://127.0.0.1:18501/_stcore/health", timeout=3)
            good = api.status_code == 200 and ui.status_code == 200
            if good:
                break
        except httpx.HTTPError:
            pass
        if not all(psutil.pid_exists(r["pid"]) for r in records.values()):
            break
        time.sleep(1)
    output = {
        "ready": good,
        "mode": mode,
        "startup_to_native_ready_seconds": time.perf_counter() - start_time,
        "api": "http://127.0.0.1:18080",
        "dashboard": "http://127.0.0.1:18501",
    }
    save_new(ROOT / f"startup-{time.time_ns()}.json", output)
    if not good:
        raise ValueError("Local startup failed; inspect Phase 7 logs, no gallery substitution")
    return output


def stop():
    path = ROOT / "processes.json"
    records = read_json(path)
    for record in records.values():
        try:
            process = psutil.Process(record["pid"])
            if abs(process.create_time() - record["created"]) > 0.01:
                raise ValueError("PID identity changed; refusing termination")
            cmd = " ".join(process.cmdline())
            if (
                "factorygraph.phase7.server" not in cmd
                and "apps/factorygraph_dashboard/app.py" not in cmd
            ):
                raise ValueError("Process is not this demo")
            # Windows venv launchers can spawn two Python descendants. Capture
            # only this validated process's tree before terminating its leaves.
            owned = [process, *process.children(recursive=True)]
            identities = [(p, p.create_time()) for p in reversed(owned)]
            for child, created in identities:
                try:
                    if abs(child.create_time() - created) > 0.01:
                        raise ValueError("Child PID identity changed; refusing termination")
                    child.terminate()
                except psutil.NoSuchProcess:
                    pass
            _, alive = psutil.wait_procs(owned, timeout=15)
            if alive:
                raise RuntimeError("Owned demo processes did not stop; preserve lifecycle record")
        except psutil.NoSuchProcess:
            pass
    # Preserve the owned lifecycle record instead of deleting audit evidence.
    path.rename(ROOT / f"processes-stopped-{time.time_ns()}.json")
    return {"status": "stopped_owned_api_and_dashboard_only"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["credentials", "register", "start", "stop"])
    parser.add_argument("--mode", choices=["full", "gallery"], default="full")
    args = parser.parse_args()
    print(json.dumps(start(args.mode) if args.stage == "start" else globals()[args.stage]()))
