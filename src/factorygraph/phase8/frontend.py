"""Separate small AppTest diagnostic; no browser-paint or UI speedup claim."""

import os
import time
from pathlib import Path
from unittest.mock import patch

import httpx
import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from factorygraph.io import sha256
from factorygraph.phase6.common import save_new
from factorygraph.phase8.benchmark import Service
from factorygraph.phase8.common import ROOT


def run():
    save_new(
        ROOT / "frontend_diagnostic_registration.json",
        {
            "scope": (
                "Post-comparison descriptive AppTest; "
                "no frontend code/caching change or retention decision"
            ),
            "variants": ["baseline", "candidate"],
            "samples_per_variant": 1,
            "initial_page": "Fleet overview",
            "interaction": "Machine analysis",
            "remaining_workspaces": "All six execute against actual authenticated API",
            "browser_measured": False,
            "source_sha256": sha256(Path(__file__)),
        },
    )
    originals = {name: os.environ.get(name) for name in ["FG7_API_URL", "FG7_DASHBOARD_TOKEN_FILE"]}
    os.environ["FG7_API_URL"] = "http://127.0.0.1:18081"
    os.environ["FG7_DASHBOARD_TOKEN_FILE"] = str(
        Path("artifacts/phase7/secrets/operator.token").resolve()
    )
    result = {}
    try:
        for variant in ["baseline", "candidate"]:
            calls = []

            def timer(original, label, records=calls):
                def wrapper(*args, **kwargs):
                    started = time.perf_counter()
                    try:
                        return original(*args, **kwargs)
                    finally:
                        records.append({"stage": label, "seconds": time.perf_counter() - started})

                return wrapper

            with Service(variant, ROOT / ("frontend-" + variant)) as service:
                service.initialize_records()
                with (
                    patch.object(httpx, "request", timer(httpx.request, "authenticated_http")),
                    patch.object(
                        httpx.Response, "json", timer(httpx.Response.json, "response_json_decode")
                    ),
                    patch.object(pd, "to_datetime", timer(pd.to_datetime, "datetime_transform")),
                    patch.object(
                        pd.DataFrame, "set_index", timer(pd.DataFrame.set_index, "index_transform")
                    ),
                    patch.object(st, "line_chart", timer(st.line_chart, "chart_creation")),
                ):
                    tick = time.perf_counter()
                    at = AppTest.from_file(
                        Path("apps/factorygraph_dashboard/app.py").resolve(), default_timeout=120
                    ).run()
                    initial = time.perf_counter() - tick
                    assert not at.exception
                    at.button[0].click().run()
                    assert not at.exception and len(at.dataframe) > 0
                    before = len(calls)
                    tick = time.perf_counter()
                    at.sidebar.radio[0].set_value("Machine analysis").run()
                    interaction = time.perf_counter() - tick
                    assert not at.exception and "99.983069" in at.metric[0].value
                    interaction_calls = calls[before:]
                    for page in [
                        "Historical events",
                        "Knowledge-graph evidence",
                        "Decision-support report",
                        "Research & transparency",
                    ]:
                        at.sidebar.radio[0].set_value(page).run()
                        assert not at.exception
                result[variant] = {
                    "initial_python_apptest_seconds": initial,
                    "machine_interaction_seconds": interaction,
                    "all_six_workspaces_passed": True,
                    "interaction_stages": interaction_calls,
                    "all_calls": calls,
                    "timings_overlap": True,
                    "sample_count": 1,
                    "browser_paint_measured": False,
                }
        save_new(ROOT / "frontend_diagnostic.json", result)
    finally:
        for key, value in originals.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return {
        v: {
            k: r[k]
            for k in [
                "initial_python_apptest_seconds",
                "machine_interaction_seconds",
                "all_six_workspaces_passed",
            ]
        }
        for v, r in result.items()
    }


if __name__ == "__main__":
    print(run())
