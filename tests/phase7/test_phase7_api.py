"""Interface/security software tests; fake engine values are not reported benchmarks."""

import copy
import logging
import time
from collections import deque

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from pydantic import ValidationError

from factorygraph.phase6.common import read_json
from factorygraph.phase7.api import create_app
from factorygraph.phase7.config import Settings
from factorygraph.phase7.runtime import PortableConfig, project, utc

TOKEN = "test-only-operator-credential-" + "o" * 32
VIEWER = "test-only-viewer-credential-" + "v" * 32
HEADERS = {"Authorization": "Bearer " + TOKEN}


class Engine:
    def __init__(self, settings):
        self.settings = settings
        self.metrics = deque(maxlen=256)
        self.builder = None
        self.startup_seconds = 0.0
        self.available = True
        self.closed = False
        self.delay = 0

    def ready(self):
        return self.available

    def machines(self):
        return [{"machine_id": 1, "model": "model1"}, {"machine_id": 17, "model": "model3"}]

    def snapshots(self, machine):
        return [{"snapshot": "2015-10-16T12:00:00+00:00", "eligibility": "primary"}]

    def case(self, machine, snapshot):
        time.sleep(self.delay)
        return project(read_json("tests/fixtures/illustrative_case.json"))

    def close(self):
        self.closed = True


def client(settings=None, factory=Engine):
    return TestClient(
        create_app(
            settings or Settings(), factory, lambda name: TOKEN if name == "operator" else VIEWER
        )
    )


def test_lifespan_liveness_auth_and_sanitized_headers():
    c = client()
    with c:
        assert c.get("/api/v1/health/live").status_code == 200
        for path in ["metadata", "machines", "health/ready", "metrics", "schema"]:
            assert c.get("/api/v1/" + path).status_code == 401
            assert (
                c.get("/api/v1/" + path, headers={"Authorization": "Bearer invalid"}).status_code
                == 401
            )
        r = c.get("/api/v1/metadata", headers=HEADERS)
        assert r.status_code == 200 and r.json()["mode"] == "full"
        assert r.headers["cache-control"] == "no-store"
        assert r.headers["x-frame-options"] == "DENY"
        assert "C:" not in r.text and TOKEN not in r.text
        engine = c.app.state.engine
    assert engine.closed


def test_resource_authorization_across_routes():
    with client() as c:
        viewer = {"Authorization": "Bearer " + VIEWER}
        assert c.get("/api/v1/machines", headers=viewer).json()["total"] == 1
        for path, params in [
            ("snapshots", {"machine_id": 1}),
            ("cases/1", {"snapshot_time": "2015-10-16T12:00Z"}),
            ("telemetry/1", {"snapshot_time": "2015-10-16T12:00Z"}),
        ]:
            assert c.get("/api/v1/" + path, params=params, headers=viewer).status_code == 403
        assert c.get("/api/v1/metrics", headers=viewer).status_code == 403
        assert (
            c.post(
                "/api/v1/fleet/replay",
                headers=viewer,
                json={"snapshot": "2015-10-16T12:00Z", "machines": [1]},
            ).status_code
            == 403
        )


@pytest.mark.parametrize(
    "value",
    [
        "2015-10-16",
        "2015-10-16T12:00:00",
        "2015-10-16T12:00:00+02:00",
        "malformed",
        "../../.env.phase4",
    ],
)
def test_invalid_timestamp_and_path_inputs(value):
    with client() as c:
        r = c.get("/api/v1/cases/1", params={"snapshot_time": value}, headers=HEADERS)
        assert r.status_code == 422 and "probability" not in r.text
        assert ".env.phase4" not in r.text


def test_unknown_snapshot_machine_query_and_cors():
    with client() as c:
        assert (
            c.get(
                "/api/v1/cases/1000", params={"snapshot_time": "2015-10-16T12:00Z"}, headers=HEADERS
            ).status_code
            == 404
        )
        assert (
            c.get(
                "/api/v1/cases/1", params={"snapshot_time": "2015-10-16T12:01Z"}, headers=HEADERS
            ).status_code
            == 404
        )
        assert c.get("/api/v1/machines?path=/etc/passwd", headers=HEADERS).status_code == 422
        assert c.get("/api/v1/machines?limit=1&limit=2", headers=HEADERS).status_code == 422
        r = c.get("/api/v1/metadata", headers={**HEADERS, "Origin": "https://attacker.invalid"})
        assert r.status_code == 403 and "access-control-allow-origin" not in r.headers


@pytest.mark.parametrize(
    "body",
    [
        {"snapshot": "2015-10-16T12:00Z", "machines": list(range(1, 102))},
        {"snapshot": "2015-10-16T12:00Z", "machines": [True]},
        {"snapshot": "2015-10-16T12:00Z", "machines": [1, 1]},
        {"snapshot": "2015-10-16T12:00Z", "machines": [1], "path": "/etc/passwd"},
    ],
)
def test_fleet_payload_rejections(body):
    with client() as c:
        assert c.post("/api/v1/fleet/replay", json=body, headers=HEADERS).status_code == 422


def test_body_limits_invalid_json_rate_limits_and_log_redaction(caplog):
    caplog.set_level(logging.INFO, logger="factorygraph.phase7")
    with client(Settings(requests_per_minute=10)) as c:
        assert (
            c.post("/api/v1/fleet/replay", content=b"x" * 17000, headers=HEADERS).status_code == 413
        )
        assert (
            c.post(
                "/api/v1/fleet/replay",
                content=b"{invalid",
                headers={**HEADERS, "Content-Type": "application/json"},
            ).status_code
            == 422
        )
        for _ in range(12):
            r = c.get("/api/v1/metadata", headers=HEADERS)
        assert r.status_code == 429
    assert caplog.records
    assert TOKEN not in caplog.text and VIEWER not in caplog.text


def test_dependency_failure_is_not_gallery_or_empty_history():
    with client() as c:
        c.app.state.engine.available = False
        assert c.get("/api/v1/health/live").status_code == 200
        assert c.get("/api/v1/health/ready", headers=HEADERS).status_code == 503
        r = c.get("/api/v1/cases/1", params={"snapshot_time": "2015-10-16T12:00Z"}, headers=HEADERS)
        assert r.status_code == 503 and "report" not in r.json()


def test_projection_is_exact_except_internal_path():
    original = read_json("tests/fixtures/illustrative_case.json")
    changed = project(original)
    expected = copy.deepcopy(original)
    expected["temporal_context"]["supplementary_chronos_context"].pop("artifact_path")
    assert (
        changed == expected
        and changed["prediction"]["probability"] == original["prediction"]["probability"]
    )
    assert "artifact_path" not in str(changed)
    assert "artifact_path" in original["temporal_context"]["supplementary_chronos_context"]


def test_portable_identity_config_and_invalid_runtime_modes():
    from factorygraph.phase6.common import Config

    record = {"config": Config().model_dump(mode="json")}
    c = PortableConfig.model_validate(record["config"])
    c._registered_spelling = record["config"]["run_dir"]
    assert c.model_dump(mode="json") == record["config"]
    with pytest.raises(ValidationError):
        Settings(mode="hosted")
    with pytest.raises(ValidationError):
        Settings(concurrency=2)
    assert utc("2015-10-16T12:00Z").hour == 12


def test_timeout_retains_bounded_work_slot():
    with client(Settings(case_deadline_seconds=0.001)) as c:
        c.app.state.engine.delay = 0.15
        r = c.get("/api/v1/cases/1", params={"snapshot_time": "2015-10-16T12:00Z"}, headers=HEADERS)
        assert r.status_code == 504
        r = c.get("/api/v1/cases/1", params={"snapshot_time": "2015-10-16T12:00Z"}, headers=HEADERS)
        assert r.status_code == 503 and r.json()["error"] == "service_busy"


def test_unexpected_exception_and_startup_failure_sanitized():
    class Broken(Engine):
        def case(self, *args):
            raise RuntimeError("secret-data C:/private/file")

    with client(factory=Broken) as c:
        r = c.get("/api/v1/cases/1", params={"snapshot_time": "2015-10-16T12:00Z"}, headers=HEADERS)
        assert r.status_code == 503 and "private" not in r.text

    def failed(_settings):
        raise ValueError("dependency initialization failure")

    with pytest.raises(ValueError):
        with client(factory=failed):
            pass
