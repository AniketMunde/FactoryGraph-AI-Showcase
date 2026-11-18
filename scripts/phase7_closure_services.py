"""Owned local-only QA services; no accepted serving file or database is changed."""

import argparse
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn

from factorygraph.phase6.common import save_new
from factorygraph.phase7.api import create_app
from factorygraph.phase7.config import Settings
from factorygraph.phase7.runtime import Runtime


def application(root, mode):
    def factory(settings):
        engine = Runtime(settings)
        if mode == "fault":
            original_read, original_case = engine.db.read, engine.case

            def read(query, **parameters):
                if (root / "graph-unavailable").exists():
                    raise ConnectionError("Closure-only controlled dependency fault")
                return original_read(query, **parameters)

            def case(*args):
                if (root / "slow-case").exists():
                    time.sleep(1)
                elif (root / "busy-case").exists():
                    time.sleep(0.25)
                return original_case(*args)

            engine.db.read, engine.case = read, case
        return engine

    app = create_app(
        Settings(
            mode="gallery" if mode == "gallery" else "full",
            case_deadline_seconds=0.5 if mode == "fault" else 120,
        ),
        factory,
    )
    lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def managed(app):
        async with lifespan(app):
            save_new(
                root / (mode + "-ready.json"),
                {
                    "pid": os.getpid(),
                    "mode": mode,
                    "scope": "Closure-only service; controlled faults are not real DB shutdown",
                },
            )
            yield
        save_new(root / (mode + "-closed.json"), {"graceful_lifespan_closed": True})

    app.router.lifespan_context = managed
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["gallery", "fault"], required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()

    class Server(uvicorn.Server):
        async def on_tick(self, counter):
            if (args.root / "stop-services").exists():
                self.should_exit = True
            return await super().on_tick(counter)

    Server(
        uvicorn.Config(
            application(args.root, args.mode),
            host="127.0.0.1",
            port=18082 if args.mode == "gallery" else 18083,
            access_log=False,
            proxy_headers=False,
        )
    ).run()
