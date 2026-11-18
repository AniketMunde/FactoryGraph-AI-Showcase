"""FactoryGraph retrospective portfolio interface; data comes exclusively from the API."""

import json
import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

# Load only the adjacent API client; no project research modules are imported by the UI.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from client import APIError, request  # noqa: E402

PAGES = [
    "Fleet overview",
    "Machine analysis",
    "Historical events",
    "Knowledge-graph evidence",
    "Decision-support report",
    "Research & transparency",
]


def status_label(report):
    if report["status"] != "complete":
        return report["status"].replace("_", " ").title()
    policy = report["alert_policy"]
    return (
        "Alert generated"
        if policy["new_alert"]
        else "Alert suppressed"
        if policy["cooldown_suppressed"]
        else "Below threshold"
    )


def main():
    st.set_page_config(page_title="FactoryGraph AI", page_icon="🏭", layout="wide")
    st.markdown(
        """<style>
    .stApp {background: #f6f8fb;} h1,h2,h3 {color:#112b42;}
    [data-testid="stSidebar"] {background:#e8eff5;}
    [data-testid="stMetric"] {background:white; padding:1rem; border:1px solid #d6e1ea;
    border-radius:10px;} .block-container {padding-top:2rem;}
    [data-testid="stCaptionContainer"] {opacity:1; color:#4f6072;}
    </style>""",
        unsafe_allow_html=True,
    )
    st.title("FactoryGraph AI")
    st.caption("EVIDENCE-GROUNDED INDUSTRIAL INTELLIGENCE · HISTORICAL REPLAY")
    try:
        meta = request("GET", "/metadata")
        st.warning(meta["banner"], icon="⚠️")
        st.sidebar.header("Replay workspace")
        st.sidebar.caption("UTC · immutable research artifacts")
        st.sidebar.info(
            "Full historical replay · genuine Neo4j"
            if meta["mode"] == "full"
            else "Verified saved-case gallery · no live graph queries"
        )
        page = st.sidebar.radio("Workspace", PAGES)
        machines = request("GET", "/machines")["items"]
        machine_ids = [m["machine_id"] for m in machines]
        st.sidebar.caption(f"{len(machine_ids)} authorized machine identities")
        machine = st.sidebar.selectbox("Machine", machine_ids)
        scope = st.sidebar.selectbox("Snapshot eligibility", ["primary", "all", "evidence_only"])
        index = st.sidebar.number_input(
            "Snapshot page", min_value=0, max_value=100, value=0, step=1
        )
        snaps = request(
            "GET",
            "/snapshots",
            params={
                "machine_id": machine,
                "eligibility": scope,
                "offset": int(index) * 200,
                "limit": 200,
            },
        )
        options = [s["snapshot"] for s in snaps["items"]]
        st.sidebar.caption(f"{snaps['total']} eligible snapshots · 200 per page")
        if not options:
            st.info("No snapshots on this page. Select page 0 or another eligibility scope.")
            return
        preferred = "2015-10-16T12:00:00+00:00"
        selected = st.sidebar.selectbox(
            "Historical snapshot (UTC)",
            options,
            index=options.index(preferred) if preferred in options else 0,
        )
        st.caption(f"Machine {machine} · cutoff {selected} · mode: {meta['mode']}")

        if page == "Fleet overview":
            st.header("Fleet replay")
            st.write(
                "Replay a bounded cohort at the selected timestamp. Counts describe"
                " returned historical cases, not live uptime."
            )
            count = st.selectbox("Cohort size", [3, 10, 100])
            if meta["mode"] != "full":
                st.info("Fleet inference is disabled in the saved-case gallery.")
                return
            if st.button("Run verified fleet replay", type="primary"):
                with st.spinner("Building evidence-backed historical cases…"):
                    result = request(
                        "POST",
                        "/fleet/replay",
                        json={"snapshot": selected, "machines": machine_ids[:count]},
                    )
                st.session_state["fleet"] = {"snapshot": selected, "reports": result["reports"]}
            fleet = st.session_state.get("fleet")
            if fleet and fleet["snapshot"] == selected:
                reports = fleet["reports"]
                cols = st.columns(5)
                counts = [
                    len(reports),
                    sum(bool(c["alert_policy"]["new_alert"]) for c in reports),
                    sum(bool(c["alert_policy"]["cooldown_suppressed"]) for c in reports),
                    sum(
                        c["status"] == "complete" and not c["alert_policy"]["above_threshold"]
                        for c in reports
                    ),
                    sum(c["status"] != "complete" for c in reports),
                ]
                labels = [
                    "Machines replayed",
                    "New alerts",
                    "Suppressed crossings",
                    "Below threshold",
                    "Evidence-only / unavailable",
                ]
                for col, label, n in zip(cols, labels, counts, strict=True):
                    col.metric(label, n)
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Machine": c["request"]["machine_id"],
                                "24h probability": c["prediction"]["probability"],
                                "State": status_label(c),
                                "Availability": c["status"],
                                "Review priority": c["human_review_priority"],
                            }
                            for c in reports
                        ]
                    ),
                    hide_index=True,
                    width="stretch",
                )
            else:
                st.info(
                    "Choose a cohort and run replay. A 100-machine request may take "
                    "tens of seconds."
                )
            return

        if page == "Research & transparency":
            st.header("Research, decisions and boundaries")
            st.success("Approved predictor: calibrated Phase 1 LightGBM")
            st.write(
                "Phase 5 decision: **NO-GO for replacing the primary predictor.** "
                "Higher experimental AP did not establish reliable event-recall "
                "improvement. A6 is not the approved predictor."
            )
            st.dataframe(
                pd.DataFrame(
                    [
                        {"Phase": p, "Finding": f}
                        for p, f in [
                            (1, "Calibrated synthetic benchmark baseline"),
                            (2, "Genuine Kumo benchmark; research only"),
                            (
                                3,
                                (
                                    "Genuine Chronos forecasts; supplementary context; "
                                    "MetroPT test "
                                    "incomplete"
                                ),
                            ),
                            (4, "Source-backed temporal Neo4j and provenance"),
                            (5, "Seven ablations; NO-GO for predictive replacement"),
                            (
                                6,
                                (
                                    "59 registered engineering cases; "
                                    "deterministic conservative review"
                                    " rules"
                                ),
                            ),
                        ]
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
            for limitation in meta["limitations"]:
                st.write("• " + limitation)
            st.caption("Project documentation (repository-relative references)")
            for doc in meta["documentation"]:
                st.markdown(
                    f"[{doc}](https://github.com/AniketMunde/FactoryGraph-AI/blob/main/{doc})"
                )
            return

        key = f"case:{meta['mode']}:{machine}:{selected}"
        if key not in st.session_state or st.button("Refresh verified report"):
            with st.spinner("Retrieving the approved prediction and strictly historical evidence…"):
                st.session_state[key] = request(
                    "GET", f"/cases/{machine}", params={"snapshot_time": selected}
                )
        report = st.session_state[key]["report"]
        label = status_label(report)
        if label == "Alert generated":
            st.error("ALERT GENERATED · Human assessment suggested")
        elif label == "Alert suppressed":
            st.warning("ALERT SUPPRESSED · Existing 24h cooldown; no new alert")
        else:
            st.info(label + " · Absence of an alert is not proof of equipment safety")

        if page == "Machine analysis":
            st.header("Machine analysis")
            cols = st.columns(3)
            p = report["prediction"]["probability"]
            cols[0].metric(
                "Calibrated failure probability · next 24h",
                "Unavailable" if p is None else f"{p:.6%}",
            )
            threshold = report["alert_policy"]["threshold"]
            cols[1].metric(
                "Frozen threshold", "Unavailable" if threshold is None else str(threshold)
            )
            cols[2].metric(
                "Human-review priority", report["human_review_priority"].replace("_", " ")
            )
            if threshold is None:
                st.caption("The primary alert policy is unavailable for this snapshot.")
            else:
                st.caption(f"Frozen threshold (exact): {threshold} · Original 24h cooldown policy.")
            st.json(report["data_availability"], expanded=False)
            if meta["capabilities"]["telemetry"]:
                hours = st.selectbox("Completed historical sensor window (hours)", [24, 72, 168])
                telemetry = request(
                    "GET",
                    f"/telemetry/{machine}",
                    params={"snapshot_time": selected, "hours": hours},
                )
                frame = pd.DataFrame(telemetry["observations"])
                if frame.empty:
                    st.info("No eligible measurements in this historical window.")
                else:
                    frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
                    frame = frame.set_index("timestamp")
                    plot = frame.reset_index()
                    plot["timestamp_utc"] = plot["timestamp"].map(lambda value: value.isoformat())
                    for channel in ["volt", "rotate", "pressure", "vibration"]:
                        st.subheader(channel.title() + " · original source units")
                        description = (
                            f"{channel.title()} hourly telemetry in original source units. "
                            f"Measurement times are UTC and strictly before {selected}."
                        )
                        chart = (
                            alt.Chart(plot)
                            .mark_line()
                            .encode(
                                x=alt.X(
                                    "timestamp:T",
                                    scale=alt.Scale(type="utc"),
                                    axis=alt.Axis(
                                        title="Timestamp (UTC)",
                                        format="%m-%d %H:%M",
                                        tickCount=5,
                                        labelOverlap=True,
                                    ),
                                ),
                                y=alt.Y(f"{channel}:Q", title=channel.title()),
                                tooltip=[
                                    alt.Tooltip("timestamp_utc:N", title="Timestamp (UTC)"),
                                    alt.Tooltip(f"{channel}:Q", title=channel.title()),
                                ],
                            )
                            .properties(height=160, description=description)
                        )
                        st.altair_chart(chart, width="stretch", alt=description)
                    st.caption(telemetry["units"] + " · All observations strictly precede cutoff.")
            else:
                st.info("Raw telemetry exploration is unavailable in gallery mode.")
            with st.expander(
                "Supplementary historical forecast context · does not modify probability"
            ):
                context = report["temporal_context"]
                if context["status"] != "verified":
                    reason = context.get("reason") or "unavailable"
                    st.info("Supplementary context: " + reason.replace("_", " ") + ".")
                st.json(report["temporal_context"], expanded=False)

        elif page == "Historical events":
            st.header("Recorded historical events")
            evidence = report["historical_evidence"]
            if evidence["status"] != "verified":
                st.warning("Historical evidence is unavailable; this is not an empty history.")
            else:
                kinds = st.multiselect(
                    "Recorded source kinds",
                    ["errors", "maint", "failures"],
                    default=["errors", "maint", "failures"],
                )
                rows = [r for r in evidence["facts"] if r["kind"] in kinds]
                page_num = st.number_input(
                    "Event page (10 records)", min_value=0, max_value=10, value=0
                )
                st.dataframe(
                    pd.DataFrame(rows[int(page_num) * 10 : (int(page_num) + 1) * 10]),
                    hide_index=True,
                    width="stretch",
                )
                cutoff_label = evidence["cutoff_exclusive"]
                start_label = evidence["window_start_inclusive"]
                st.caption(f"Cutoff exclusive: {cutoff_label} ? window begins {start_label}")
                st.json(evidence["pagination"], expanded=False)

        elif page == "Knowledge-graph evidence":
            st.header("Source-grounded graph context")
            e = report["historical_evidence"]
            if e["status"] == "verified":
                st.subheader("Recorded machine → recorded model")
                st.json(e["machine"], expanded=False)
                st.subheader("Derived historical aggregates and category peers")
                st.json(e["derived_aggregates"], expanded=False)
                st.info(
                    "Model peers share a recorded category. They are not physically "
                    "connected equipment. Component codes identify categories, not "
                    "installed part instances."
                )
            else:
                st.warning("Graph evidence unavailable. No substitute evidence is fabricated.")

        else:
            st.header("Decision-support report")
            for line in report["explanation"][:4]:
                st.write(line)
            for rec in report["recommendations"]:
                with st.expander(rec["rule_id"] + " · " + rec["text"], expanded=True):
                    st.write(rec["limitations"])
                    st.json(rec, expanded=False)
            with st.expander("Provenance, unknowns and limitations"):
                st.json(report["provenance"], expanded=False)
                for line in report["limitations"]:
                    st.write("• " + line)
            st.download_button(
                "Download sanitized case JSON",
                json.dumps(report, indent=2),
                file_name=f"factorygraph-machine-{machine}.json",
                mime="application/json",
            )
    except APIError as error:
        st.error(
            f"Verified API unavailable ({error.status}): "
            f"{error.payload.get('error', 'request_failed')}. "
            "No static fallback was used."
        )
    except (ValueError, KeyError):
        st.error(
            "Dashboard configuration or response contract is unavailable. Check"
            " the local service setup."
        )


if __name__ == "__main__":
    main()
