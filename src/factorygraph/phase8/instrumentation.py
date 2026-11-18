"""Profiling-only instrumentation; no timers are installed in matched timing blocks."""

import contextvars
import cProfile
import functools
import json
import pstats
import time
from pathlib import Path

from starlette.responses import JSONResponse

TRACE = contextvars.ContextVar("phase8_trace", default=None)


def record(name, elapsed):
    trace = TRACE.get()
    if trace is not None:
        item = trace["stages"].setdefault(name, {"seconds": 0.0, "calls": 0})
        item["seconds"] += elapsed
        item["calls"] += 1


def timed(target, name, label, profile=None):
    original = getattr(target, name)

    @functools.wraps(original)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        profiling = profile and TRACE.get() and TRACE.get()["path"].startswith("/api/v1/cases/")
        if profiling:
            profile.enable()
        try:
            return original(*args, **kwargs)
        finally:
            if profiling:
                profile.disable()
            record(label, time.perf_counter() - start)

    setattr(target, name, wrapper)


class Observer:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.profile = cProfile.Profile()

    def engine(self, engine):
        for name in ["machines", "snapshots", "case", "fleet", "ready", "telemetry"]:
            timed(engine, name, "runtime_" + name)
        b = engine.builder
        if b:
            for obj, name, label in [
                (b.predictions, "get", "prediction_lookup"),
                (b.policy, "get", "policy_lookup"),
                (b.catalog, "visible", "source_visible_selection"),
                (b.evidence, "get", "evidence_inclusive"),
                (b.temporal, "get", "temporal_lookup"),
                (b.rules, "apply", "rules_apply"),
                (b.rules, "validate", "rules_validation"),
                (b.provenance, "record", "provenance"),
                (b, "fleet", "builder_fleet_inclusive"),
                (engine.db, "read", "managed_read_inclusive"),
                (engine.db.driver, "session", "session_constructor_only"),
            ]:
                timed(obj, name, label)
            timed(b, "build", "builder_case_inclusive", self.profile)
        from factorygraph.phase6.evidence import EvidenceValidator
        from factorygraph.phase6.schema import CaseReport

        timed(EvidenceValidator, "bundle", "source_validation_inclusive")
        timed(CaseReport, "__init__", "case_schema_constructor")
        original = CaseReport.model_validate.__func__

        @classmethod
        def validate(cls, *args, **kwargs):
            start = time.perf_counter()
            try:
                return original(cls, *args, **kwargs)
            finally:
                record("case_schema_validation", time.perf_counter() - start)

        CaseReport.model_validate = validate
        timed(JSONResponse, "render", "json_render")
        return engine

    def application(self, app):
        seen = set()
        for route in app.routes:
            dependant = getattr(route, "dependant", None)
            if dependant is None:
                continue
            original = dependant.call

            @functools.wraps(original)
            async def endpoint(*args, _original=original, **kwargs):
                start = time.perf_counter()
                try:
                    return await _original(*args, **kwargs)
                finally:
                    record("endpoint_inclusive", time.perf_counter() - start)

            dependant.call = endpoint
            for dependency in dependant.dependencies:
                if dependency.call.__name__ != "principal" or id(dependency) in seen:
                    continue
                seen.add(id(dependency))
                original_auth = dependency.call

                @functools.wraps(original_auth)
                async def auth(*args, _original=original_auth, **kwargs):
                    start = time.perf_counter()
                    try:
                        return await _original(*args, **kwargs)
                    finally:
                        record("authentication", time.perf_counter() - start)

                dependency.call = auth
        return TraceApplication(app, self)

    def save(self):
        self.profile.dump_stats(str(self.directory / "builder.prof"))
        stats = pstats.Stats(self.profile)
        rows = [
            {
                "file": k[0],
                "line": k[1],
                "function": k[2],
                "primitive_calls": v[0],
                "calls": v[1],
                "self_seconds": v[2],
                "cumulative_seconds": v[3],
            }
            for k, v in stats.stats.items()
        ]
        rows.sort(key=lambda r: r["cumulative_seconds"], reverse=True)
        (self.directory / "profile_top.json").write_text(json.dumps(rows[:80], indent=2))


class TraceApplication:
    def __init__(self, app, observer):
        self.app, self.observer = app, observer

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            try:
                await self.app(scope, receive, send)
            finally:
                if scope["type"] == "lifespan":
                    self.observer.save()
            return
        start = time.perf_counter()
        trace = {"path": scope["path"], "stages": {}, "response_bytes": 0}
        token = TRACE.set(trace)

        async def measured_send(message):
            if message["type"] == "http.response.start":
                trace["status"] = message["status"]
                trace["first_send_seconds"] = time.perf_counter() - start
            if message["type"] == "http.response.body":
                trace["response_bytes"] += len(message.get("body", b""))
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body"):
                trace["last_send_seconds"] = time.perf_counter() - start

        try:
            await self.app(scope, receive, measured_send)
        finally:
            trace["asgi_seconds"] = time.perf_counter() - start
            with (self.observer.directory / "traces.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(trace) + "\n")
            TRACE.reset(token)
