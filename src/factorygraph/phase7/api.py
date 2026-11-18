"""Authenticated versioned HTTP interface; deterministic Phase 6 content is preserved."""

import asyncio
import json
import logging
import secrets
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Annotated

import psutil
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from factorygraph.phase7.config import load_settings, secret
from factorygraph.phase7.runtime import BANNER, Runtime, utc

logger = logging.getLogger("factorygraph.phase7")
bearer = HTTPBearer(auto_error=False)
PREFIX = "/api/v1"
BEARER_DEPENDENCY = Depends(bearer)


class FleetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot: str
    machines: list[Annotated[int, Field(strict=True, gt=0)]] = Field(min_length=1, max_length=100)


def create_app(settings=None, runtime_factory=Runtime, token_loader=secret):
    @asynccontextmanager
    async def lifespan(app):
        cfg = settings or load_settings()
        app.state.settings = cfg
        app.state.tokens = {name: token_loader(name) for name in ["operator", "viewer"]}
        if app.state.tokens["operator"] == app.state.tokens["viewer"]:
            raise RuntimeError("Distinct credentials required")
        app.state.engine = runtime_factory(cfg)
        app.state.busy = False
        app.state.active = None
        app.state.rates = defaultdict(deque)
        try:
            yield
        finally:
            if app.state.active:
                try:
                    await app.state.active
                except Exception:
                    pass  # A failed request has already received a sanitized response.
            app.state.engine.close()

    app = FastAPI(
        title="FactoryGraph AI",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    def response_error(status, code, request_id=None):
        return JSONResponse(status_code=status, content={"error": code, "request_id": request_id})

    @app.middleware("http")
    async def boundary(request, call_next):
        started = time.perf_counter()
        request.state.request_id = uuid.uuid4().hex
        cfg = app.state.settings
        code = None
        response = None
        host = request.headers.get("host", "").split(":")[0]
        if host not in cfg.allowed_hosts:
            response = response_error(400, "invalid_host")
        elif request.headers.get("origin") and request.headers["origin"] not in cfg.allowed_origins:
            response = response_error(403, "origin_not_allowed")
        else:
            payload = bytearray()
            try:
                async for chunk in request.stream():
                    payload.extend(chunk)
                    if len(payload) > cfg.max_body_bytes:
                        response = response_error(413, "request_too_large")
                        break
                if response is None:
                    request._body = bytes(payload)
                    response = await call_next(request)
            except Exception:
                code = "internal_error"
                response = response_error(500, code)
        response.headers.update(
            {
                "X-Request-ID": request.state.request_id,
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
            }
        )
        route = getattr(request.scope.get("route"), "path", "/unmatched")
        entry = {
            "request_id": request.state.request_id,
            "route": route,
            "status": response.status_code,
            "mode": cfg.mode,
            "duration_seconds": time.perf_counter() - started,
            "case_outcome": getattr(request.state, "outcome", None),
            "graph_available": getattr(request.state, "graph_available", None),
            "model_policy_verified": getattr(request.state, "model_verified", None),
            "error_category": code or ("request_rejected" if response.status_code >= 400 else None),
            "safe_abstention_reason": getattr(request.state, "reason", None),
            "last_case_phase6_seconds": getattr(request.state, "phase6_timing", None),
        }
        app.state.engine.metrics.append(entry)
        logger.info(json.dumps(entry))
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, _error):
        return response_error(422, "invalid_request", request.state.request_id)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, error):
        return response_error(
            error.status_code,
            str(error.detail) if isinstance(error.detail, str) else "request_rejected",
            request.state.request_id,
        )

    async def principal(
        request: Request, credential: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY
    ):
        name = None
        if credential and credential.scheme.lower() == "bearer":
            for candidate, expected in app.state.tokens.items():
                if secrets.compare_digest(credential.credentials.encode(), expected.encode()):
                    name = candidate
        bucket = app.state.rates[name or "anonymous"]
        now = time.monotonic()
        while bucket and now - bucket[0] > 60:
            bucket.popleft()
        if len(bucket) >= app.state.settings.requests_per_minute:
            raise HTTPException(429, "rate_limit")
        bucket.append(now)
        if name is None:
            raise HTTPException(401, "authentication_required")
        return name

    auth_dependency = Depends(principal)

    def query(request, allowed):
        pairs = list(request.query_params.multi_items())
        if set(k for k, _ in pairs) - set(allowed) or len({k for k, _ in pairs}) != len(pairs):
            raise HTTPException(422, "unsupported_query_parameters")

    def authorize(name, machine):
        known = {m["machine_id"] for m in app.state.engine.machines()}
        if machine not in known:
            raise HTTPException(404, "unknown_machine")
        if name == "viewer" and machine != 17:
            raise HTTPException(403, "machine_not_authorized")

    def snapshot(machine, value):
        try:
            parsed = utc(value)
        except (ValueError, TypeError, OverflowError):
            raise HTTPException(422, "invalid_utc_snapshot") from None
        if not any(utc(r["snapshot"]) == parsed for r in app.state.engine.snapshots(machine)):
            raise HTTPException(404, "unsupported_snapshot")
        return parsed

    async def compute(request, operation):
        if app.state.busy:
            raise HTTPException(503, "service_busy")
        app.state.busy = True

        async def work():
            try:
                return await asyncio.to_thread(operation)
            finally:
                app.state.busy = False

        task = asyncio.create_task(work())
        app.state.active = task
        try:
            result = await asyncio.wait_for(
                asyncio.shield(task), app.state.settings.case_deadline_seconds
            )
            request.state.graph_available = app.state.engine.settings.mode == "full"
            request.state.model_verified = True
            if app.state.engine.builder and (
                request.url.path.startswith(PREFIX + "/cases/")
                or request.url.path == PREFIX + "/fleet/replay"
            ):
                request.state.phase6_timing = dict(app.state.engine.builder.last_timing)
            return result
        except TimeoutError:
            raise HTTPException(504, "case_deadline_exceeded") from None
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "dependency_unavailable") from None

    async def ready_for_data(request):
        good = await asyncio.to_thread(app.state.engine.ready)
        request.state.graph_available = good if app.state.settings.mode == "full" else None
        if not good:
            raise HTTPException(503, "dependency_unavailable")

    def envelope(report):
        return {
            "api_version": "v1",
            "mode": app.state.settings.mode,
            "projection": "sanitized-case-v1; internal artifact paths omitted",
            "report": report,
        }

    @app.get(PREFIX + "/health/live")
    async def live(request: Request):
        query(request, [])
        return {"status": "alive"}

    @app.get(PREFIX + "/health/ready")
    async def ready(request: Request, name=auth_dependency):
        query(request, [])
        await ready_for_data(request)
        return {"status": "ready", "mode": app.state.settings.mode}

    @app.get(PREFIX + "/metadata")
    async def metadata(request: Request, name=auth_dependency):
        query(request, [])
        return {
            "api_version": "v1",
            "mode": app.state.settings.mode,
            "banner": BANNER,
            "dataset": "Microsoft Azure Predictive Maintenance synthetic historical data",
            "approved_predictor": "Phase 1 calibrated LightGBM; Phase 5 A0 verified identical",
            "horizon_hours": 24,
            "phase5_decision": "NO-GO for predictor replacement",
            "capabilities": {
                "dynamic_replay": app.state.settings.mode == "full",
                "telemetry": app.state.settings.mode == "full",
                "gallery": app.state.settings.mode == "gallery",
                "max_fleet": 100,
            },
            "limitations": [
                "Retrospective synthetic demonstration, no real-machinery validation",
                "Immediate source availability and UTC are assumptions",
                "No causal diagnosis or autonomous action",
                "MetroPT-3 test incomplete",
            ],
            "documentation": [
                "docs/PHASE6_REPORT.md",
                "docs/PHASE5_REPORT.md",
                "docs/PHASE7_SECURITY.md",
            ],
        }

    @app.get(PREFIX + "/machines")
    async def machines(request: Request, offset: int = 0, limit: int = 100, name=auth_dependency):
        query(request, ["offset", "limit"])
        if not 0 <= offset <= 1000 or not 1 <= limit <= 100:
            raise HTTPException(422, "invalid_pagination")
        rows = [
            m for m in app.state.engine.machines() if name == "operator" or m["machine_id"] == 17
        ]
        return {"total": len(rows), "items": rows[offset : offset + limit]}

    @app.get(PREFIX + "/snapshots")
    async def snapshots(
        request: Request,
        machine_id: int,
        offset: int = 0,
        limit: int = 100,
        eligibility: str = "primary",
        name=auth_dependency,
    ):
        query(request, ["machine_id", "offset", "limit", "eligibility"])
        authorize(name, machine_id)
        if (
            not 0 <= offset <= 10000
            or not 1 <= limit <= 200
            or eligibility not in {"all", "primary", "evidence_only"}
        ):
            raise HTTPException(422, "invalid_pagination_or_eligibility")
        rows = app.state.engine.snapshots(machine_id)
        if eligibility != "all" and app.state.settings.mode == "full":
            rows = [r for r in rows if r["eligibility"] == eligibility]
        return {"total": len(rows), "items": rows[offset : offset + limit]}

    @app.get(PREFIX + "/cases/{machine_id}")
    async def case(request: Request, machine_id: int, snapshot_time: str, name=auth_dependency):
        query(request, ["snapshot_time"])
        authorize(name, machine_id)
        cutoff = snapshot(machine_id, snapshot_time)
        await ready_for_data(request)
        report = await compute(request, lambda: app.state.engine.case(machine_id, cutoff))
        request.state.outcome = report["status"]
        request.state.graph_available = (
            report["historical_evidence"]["status"] == "verified"
            if app.state.settings.mode == "full"
            else None
        )
        request.state.model_verified = report["prediction"]["status"] == "verified"
        request.state.reason = report["prediction"].get("reason")
        if report["status"] == "degraded":
            return JSONResponse(
                status_code=503, content={**envelope(report), "error": "dependency_degraded"}
            )
        return envelope(report)

    @app.get(PREFIX + "/telemetry/{machine_id}")
    async def telemetry(
        request: Request,
        machine_id: int,
        snapshot_time: str,
        hours: int = 24,
        name=auth_dependency,
    ):
        query(request, ["snapshot_time", "hours"])
        authorize(name, machine_id)
        cutoff = snapshot(machine_id, snapshot_time)
        if app.state.settings.mode != "full":
            raise HTTPException(409, "capability_not_available_in_gallery")
        if not 1 <= hours <= 168:
            raise HTTPException(422, "invalid_telemetry_window")
        await ready_for_data(request)
        return await compute(request, lambda: app.state.engine.telemetry(machine_id, cutoff, hours))

    @app.post(PREFIX + "/fleet/replay")
    async def fleet(request: Request, body: FleetRequest, name=auth_dependency):
        query(request, [])
        if app.state.settings.mode != "full":
            raise HTTPException(409, "capability_not_available_in_gallery")
        if len(set(body.machines)) != len(body.machines) or any(
            isinstance(m, bool) or m <= 0 for m in body.machines
        ):
            raise HTTPException(422, "invalid_fleet_membership")
        for machine in body.machines:
            authorize(name, machine)
            cutoff = snapshot(machine, body.snapshot)
            if (machine, cutoff) not in app.state.engine.builder.predictions.index.index:
                raise HTTPException(422, "fleet_requires_primary_snapshots")
        await ready_for_data(request)
        reports = await compute(request, lambda: app.state.engine.fleet(cutoff, body.machines))
        request.state.outcome = "fleet_replay"
        status = 503 if any(c["status"] == "degraded" for c in reports) else 200
        return JSONResponse(status_code=status, content={"mode": "full", "reports": reports})

    @app.get(PREFIX + "/metrics")
    async def metrics(request: Request, name=auth_dependency):
        query(request, [])
        if name != "operator":
            raise HTTPException(403, "operator_required")
        return {
            "mode": app.state.settings.mode,
            "startup_seconds": app.state.engine.startup_seconds,
            "process_rss_bytes": psutil.Process().memory_info().rss,
            "recent_requests": list(app.state.engine.metrics),
            "result_cache": False,
        }

    @app.get(PREFIX + "/schema")
    async def schema(request: Request, name=auth_dependency):
        query(request, [])
        return app.openapi()

    return app


app = create_app()
