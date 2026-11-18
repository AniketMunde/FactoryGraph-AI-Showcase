"""One-worker opt-in study server; accepted Phase 7 code remains unchanged."""

import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn

from factorygraph.phase6.common import save_new
from factorygraph.phase7.api import create_app
from factorygraph.phase7.config import Settings
from factorygraph.phase7.runtime import Runtime
from factorygraph.phase8.common import config


def application():
    directory = Path(os.environ["FG8_OUTPUT"])
    variant = os.environ.get("FG8_VARIANT", "baseline")
    if variant not in {"baseline", "candidate", "profile"}:
        raise ValueError("Unknown registered variant")
    observer = None
    if variant == "candidate":
        from factorygraph.phase8.candidate import CandidateRuntime

        factory = CandidateRuntime
    else:
        factory = Runtime
    if variant == "profile":
        from factorygraph.phase8.instrumentation import Observer

        observer = Observer(directory)

        def instrumented(settings):
            return observer.engine(Runtime(settings))

        factory = instrumented
    app = create_app(Settings(), runtime_factory=factory)
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifecycle(app):
        async with original_lifespan(app):
            save_new(
                directory / "engine.json",
                {
                    "pid": os.getpid(),
                    "startup_seconds": app.state.engine.startup_seconds,
                    "variant": variant,
                },
            )
            yield
        save_new(directory / "closed.json", {"graceful_lifespan_closed": True})

    app.router.lifespan_context = lifecycle
    return observer.application(app) if observer else app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    output = Path(os.environ["FG8_OUTPUT"])

    # The control file carries no secret or public API capability.
    def stop_requested():
        return (output / "stop").exists()

    class ControlledServer(uvicorn.Server):
        async def on_tick(self, counter):
            if stop_requested():
                self.should_exit = True
            return await super().on_tick(counter)

    started = time.perf_counter()
    server = ControlledServer(
        uvicorn.Config(
            application(),
            host="127.0.0.1",
            port=config()["port"],
            workers=1,
            access_log=False,
            proxy_headers=False,
        )
    )
    server.run()
    save_new(output / "server_exit.json", {"wall_seconds": time.perf_counter() - started})
