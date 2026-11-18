"""Owned genuine-engine fault services. Never stop or alter the accepted Neo4j instance."""

import argparse
import os
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import psutil
import uvicorn

from factorygraph.phase6.common import read_json, save_new
from factorygraph.phase7.api import create_app
from factorygraph.phase7.config import Settings
from factorygraph.phase7.runtime import Runtime


def serve(root, mode):
    def factory(settings):
        engine = Runtime(settings)
        if mode == "fault":
            read, case = engine.db.read, engine.case

            def controlled_read(query, **parameters):
                if (root / "graph-unavailable").exists():
                    raise ConnectionError("Controlled console QA dependency fault")
                return read(query, **parameters)

            def controlled_case(*args):
                if (root / "slow-case").exists():
                    time.sleep(1)
                elif (root / "delay-case").exists():
                    time.sleep(0.25)
                return case(*args)

            engine.db.read, engine.case = controlled_read, controlled_case
        return engine

    app = create_app(
        Settings(
            mode="full" if mode == "fault" else "gallery",
            case_deadline_seconds=0.5 if mode == "fault" else 120,
            requests_per_minute=40 if mode == "fault" else 240,
        ),
        factory,
    )

    @app.middleware("http")
    async def controlled_busy(request, call_next):
        if mode == "fault":
            if (root / "busy-case").exists():
                app.state.busy = True
            elif app.state.active is None or app.state.active.done():
                app.state.busy = False
        return await call_next(request)

    lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def managed(app):
        async with lifespan(app):
            save_new(root / f"{mode}-ready.json", {"pid": os.getpid(), "mode": mode})
            yield
        save_new(root / f"{mode}-closed.json", {"genuine_lifespan_closed": True})

    app.router.lifespan_context = managed

    class Server(uvicorn.Server):
        async def on_tick(self, counter):
            if (root / "stop-services").exists():
                self.should_exit = True
            return await super().on_tick(counter)

    Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=18083 if mode == "fault" else 18082,
            access_log=False,
            proxy_headers=False,
        )
    ).run()


def start(root):
    if root.exists():
        raise ValueError("Use a fresh test-service directory")
    root.mkdir(parents=True)
    env = os.environ.copy()
    env.update(
        {
            "FG7_OPERATOR_TOKEN_FILE": str(
                Path("artifacts/phase7/secrets/operator.token").resolve()
            ),
            "FG7_VIEWER_TOKEN_FILE": str(Path("artifacts/phase7/secrets/viewer.token").resolve()),
            "FACTORYGRAPH_NEO4J_USER": "neo4j",
            "FACTORYGRAPH_NEO4J_URI": "bolt://127.0.0.1:17687",
            "FACTORYGRAPH_NEO4J_PASSWORD": Path(".env.phase4").read_text().strip(),
        }
    )
    records = {}
    for mode in ["fault", "gallery"]:
        port = 18083 if mode == "fault" else 18082
        if any(
            c.status == "LISTEN" and c.laddr.port == port for c in psutil.net_connections("tcp")
        ):
            raise ValueError("Test port occupied")
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "serve",
            "--run-dir",
            str(root.resolve()),
            "--mode",
            mode,
        ]
        with (root / f"{mode}.log").open("x", encoding="utf-8") as log:
            process = subprocess.Popen(
                command,
                env=env,
                stdout=log,
                stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        records[mode] = {"pid": process.pid, "created": psutil.Process(process.pid).create_time()}
    save_new(root / "owned.json", records)
    with httpx.Client(trust_env=False, timeout=2) as client:
        for _ in range(120):
            try:
                if all(
                    client.get(f"http://127.0.0.1:{port}/api/v1/health/live").status_code == 200
                    for port in [18082, 18083]
                ):
                    print({"owned_QA_services": "ready"})
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
    raise RuntimeError("Fault services failed readiness")


def stop(root):
    (root / "stop-services").touch(exist_ok=False)
    for record in read_json(root / "owned.json").values():
        try:
            process = psutil.Process(record["pid"])
            if process.create_time() != record["created"]:
                raise ValueError("Owned identity changed")
            process.wait(timeout=20)
        except psutil.NoSuchProcess:
            pass
    assert all(
        read_json(root / f"{mode}-closed.json")["genuine_lifespan_closed"]
        for mode in ["fault", "gallery"]
    )
    print({"owned_QA_services": "closed"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["serve", "start", "stop"])
    parser.add_argument("--mode", choices=["fault", "gallery"])
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.stage == "serve":
        serve(args.run_dir, args.mode)
    else:
        globals()[args.stage](args.run_dir)
