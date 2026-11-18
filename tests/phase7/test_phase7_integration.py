"""Genuine Phase 6/Neo4j integration; explicit local credential opt-in."""

import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from factorygraph.phase6.common import read_json
from factorygraph.phase7.api import create_app
from factorygraph.phase7.config import Settings
from factorygraph.phase7.runtime import Runtime, project

pytestmark = pytest.mark.skipif(
    os.environ.get("FACTORYGRAPH_PHASE7_INTEGRATION") != "1",
    reason="Genuine local Phase 7/Neo4j opt-in required",
)


def test_real_api_cases_gallery_telemetry_and_graph_identity():
    token = "integration-only-test-token-" + "t" * 32
    app = create_app(Settings(), token_loader=lambda n: token if n == "operator" else "v" * 64)
    with TestClient(app) as c:
        headers = {"Authorization": "Bearer " + token}
        for example in ["new_alert", "cooldown", "non_alert", "missing_forecast"]:
            expected = project(read_json(f"docs/examples/phase6/{example}.json"))
            r = c.get(
                f"/api/v1/cases/{expected['request']['machine_id']}",
                params={"snapshot_time": expected["request"]["snapshot"]},
                headers=headers,
            )
            assert r.status_code == 200, r.text
            assert r.json()["report"] == expected
        t = c.get(
            "/api/v1/telemetry/17",
            params={"snapshot_time": "2015-10-15T00:00Z", "hours": 24},
            headers=headers,
        )
        assert t.status_code == 200
        assert len(t.json()["observations"]) == 24
        assert all(r["timestamp"] < "2015-10-15T00:00:00+00:00" for r in t.json()["observations"])
        r = c.post(
            "/api/v1/fleet/replay",
            json={"snapshot": "2015-10-15T00:00Z", "machines": [1, 17, 42]},
            headers=headers,
        )
        assert r.status_code == 200 and len(r.json()["reports"]) == 3
        db = app.state.engine.db
        assert db.signature() == read_json("artifacts/phase4/full/build.json")["signature"]
        with pytest.raises(PermissionError):
            db.write("CREATE ()")
        with pytest.raises(ValueError):
            db.read("MATCH (n) DETACH DELETE n")
    with TestClient(
        create_app(
            Settings(mode="gallery"), token_loader=lambda n: token if n == "operator" else "v" * 64
        )
    ) as c:
        r = c.get(
            "/api/v1/cases/10001", params={"snapshot_time": "2015-10-15T00:00Z"}, headers=headers
        )
        assert r.status_code == 200 and r.json()["report"]["status"] == "abstained"
        assert (
            c.post(
                "/api/v1/fleet/replay",
                json={"snapshot": "2015-10-15T00:00Z", "machines": [17]},
                headers=headers,
            ).status_code
            == 409
        )


def test_real_dependency_fault_is_sanitized(monkeypatch):
    from neo4j import GraphDatabase

    original = GraphDatabase.driver

    def unavailable(*args, **kwargs):
        raise ConnectionError("injected credential or graph failure")

    monkeypatch.setattr(GraphDatabase, "driver", unavailable)
    with pytest.raises(ConnectionError):
        Runtime(Settings())
    monkeypatch.setattr(GraphDatabase, "driver", original)
