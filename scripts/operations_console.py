"""Local console credentials/lifecycle. No backend credential values enter arguments or output."""

import argparse
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import time
from pathlib import Path

import httpx
import psutil

from factorygraph.phase6.common import read_json, save_new

PROJECT = Path(__file__).resolve().parents[1]
APP = PROJECT / "apps/factorygraph_console"
SECRETS = PROJECT / "artifacts/operations_console_v2/secrets"


def credentials():
    if SECRETS.exists():
        raise ValueError("Console credential directory exists; do not overwrite")
    SECRETS.mkdir(parents=True)
    users = []
    for role in ["operator", "viewer"]:
        password, salt = secrets.token_urlsafe(24), secrets.token_hex(16)
        hashed = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1, dklen=64)
        users.append({"username": role, "role": role, "salt": salt, "hash": hashed.hex()})
        (SECRETS / (role + ".login")).write_text(password, encoding="utf-8")
    (SECRETS / "users.json").write_text(json.dumps(users, indent=2), encoding="utf-8")
    print({"console_accounts_created": True, "password_directory": str(SECRETS)})


def start(root, port, api_port):
    if (root / f"server-{port}.json").exists():
        raise ValueError("Owned process record exists; use a fresh run directory")
    if not (SECRETS / "users.json").is_file() or not (APP / ".next/BUILD_ID").is_file():
        raise ValueError("Create console credentials and build the frontend first")
    if any(c.status == "LISTEN" and c.laddr.port == port for c in psutil.net_connections("tcp")):
        raise ValueError("Requested local port is occupied")
    node = shutil.which("node")
    if not node:
        raise ValueError("Node is unavailable")
    env = os.environ.copy()
    env.update(
        {
            "NODE_ENV": "production",
            "NEXT_TELEMETRY_DISABLED": "1",
            "FG_CONSOLE_ORIGIN": f"http://localhost:{port}",
            "FG_CONSOLE_API_URL": f"http://127.0.0.1:{api_port}",
            "FG_CONSOLE_USERS_FILE": str(SECRETS / "users.json"),
            "FG7_OPERATOR_TOKEN_FILE": str(PROJECT / "artifacts/phase7/secrets/operator.token"),
            "FG7_VIEWER_TOKEN_FILE": str(PROJECT / "artifacts/phase7/secrets/viewer.token"),
        }
    )
    command = [
        node,
        str(APP / "node_modules/next/dist/bin/next"),
        "start",
        "--hostname",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    root.mkdir(parents=True, exist_ok=True)
    with (root / f"server-{port}.log").open("x", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            cwd=APP,
            env=env,
            stdout=log,
            stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    record = {
        "pid": process.pid,
        "created": psutil.Process(process.pid).create_time(),
        "command": command,
    }
    save_new(root / f"server-{port}.json", record)
    tick = time.perf_counter()
    with httpx.Client(trust_env=False, timeout=2) as client:
        for _ in range(90):
            try:
                response = client.get(f"http://localhost:{port}/api/session")
                if response.status_code == 200:
                    save_new(
                        root / f"ready-{port}.json",
                        {
                            "status": "ready",
                            "seconds": time.perf_counter() - tick,
                            "port": port,
                            "api_port": api_port,
                        },
                    )
                    print({"url": f"http://localhost:{port}", "status": "ready"})
                    return
            except httpx.HTTPError:
                pass
            if process.poll() is not None:
                break
            time.sleep(0.5)
    raise RuntimeError("Console failed readiness; retain logs")


def stop(root, port):
    record = read_json(root / f"server-{port}.json")
    process = psutil.Process(record["pid"])
    if (
        process.create_time() != record["created"]
        or str(APP).lower() not in " ".join(process.cmdline()).lower()
    ):
        raise ValueError("Process identity changed; refusing stop")
    owned = process.children(recursive=True) + [process]
    for child in reversed(owned):
        try:
            child.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(owned, timeout=15)
    if alive:
        raise RuntimeError("Owned console processes remain alive")
    save_new(root / f"closed-{port}.json", {"owned_process_tree_stopped": True})
    print({"owned_console_stopped": port})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["credentials", "start", "stop"])
    parser.add_argument(
        "--run-dir", type=Path, default=Path("artifacts/operations_console_v2/study/runtime")
    )
    parser.add_argument("--port", type=int, choices=range(18601, 18606), default=18601)
    parser.add_argument("--api-port", type=int, choices=[18080, 18082, 18083, 18089], default=18080)
    args = parser.parse_args()
    if args.stage == "credentials":
        credentials()
    elif args.stage == "start":
        start(args.run_dir, args.port, args.api_port)
    else:
        stop(args.run_dir, args.port)
