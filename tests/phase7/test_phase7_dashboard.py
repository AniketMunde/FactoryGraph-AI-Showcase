"""Streamlit's genuine app execution against the actual authenticated local HTTP API."""

import os
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

pytestmark = pytest.mark.skipif(
    os.environ.get("FACTORYGRAPH_PHASE7_HTTP") != "1",
    reason="Running native API/UI opt-in required",
)


def test_all_dashboard_workspaces_use_real_http_api(monkeypatch):
    token = Path("artifacts/phase7/secrets/operator.token").resolve()
    monkeypatch.setenv("FG7_DASHBOARD_TOKEN_FILE", str(token))
    monkeypatch.setenv("FG7_API_URL", "http://127.0.0.1:18080")
    at = AppTest.from_file(
        Path("apps/factorygraph_dashboard/app.py").resolve(), default_timeout=60
    ).run()
    assert not at.exception
    assert "synthetic historical industrial data" in at.warning[0].value
    assert any(s.label == "Machine" for s in at.sidebar.selectbox)
    at.button[0].click().run()
    assert not at.exception and len(at.dataframe) > 0
    pages = [
        "Machine analysis",
        "Historical events",
        "Knowledge-graph evidence",
        "Decision-support report",
        "Research & transparency",
    ]
    for page in pages:
        at.sidebar.radio[0].set_value(page).run()
        assert not at.exception, at.exception
        assert not at.error or "ALERT GENERATED" in at.error[0].value
        if page == "Machine analysis":
            assert "99.983069" in at.metric[0].value
        if page == "Historical events":
            assert len(at.dataframe) > 0
        if page == "Decision-support report":
            assert any("R001" in e.label for e in at.expander)
        if page == "Research & transparency":
            assert any("NO-GO" in m.value for m in at.markdown)


def test_missing_dashboard_credential_is_sanitized(monkeypatch):
    monkeypatch.setenv("FG7_DASHBOARD_TOKEN_FILE", "not-an-existing-secret-file")
    at = AppTest.from_file(Path("apps/factorygraph_dashboard/app.py").resolve()).run()
    assert not at.exception
    assert at.error and "server_credential_unavailable" in at.error[0].value
    assert "not-an-existing-secret-file" not in at.error[0].value
