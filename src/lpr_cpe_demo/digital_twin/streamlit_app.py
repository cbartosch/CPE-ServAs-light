# ruff: noqa: E501
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request

import streamlit as st

API = os.getenv("DT_API_URL", "http://api:8001")
USER = os.getenv("DT_USER", "demo")
PASSWORD = os.getenv("DT_PASSWORD", "CHANGE_ME")
DATASETS = [
    "subscriber_master",
    "scenario_manifests",
    "telemetry_tr181",
    "nxt_alarms",
    "contacts",
    "incidents",
    "work_orders",
    "field_evidence",
    "mrs",
    "validation_events",
    "resolution_events",
    "deterministic_decisions",
    "agent_decisions",
    "reconciliation_records",
    "human_decisions",
    "action_events",
    "predictive_modem_pulls",
    "predictive_tickets",
    "care_tickets",
    "care_ticket_reviews",
]


def _request(path: str, method: str = "GET", body: dict | None = None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    token = base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
    req.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API {exc.code}: {detail}") from exc


def _remember_run(run_id: str):
    st.session_state["run_id"] = run_id


def _run_id(key: str) -> str:
    return st.text_input("Run ID", value=st.session_state.get("run_id", ""), key=key)


def _show_predictive_summary(summary: dict) -> None:
    cols = st.columns(6)
    cols[0].metric("Scanned", f"{summary.get('scanned', 0):,}")
    cols[1].metric("Healthy", f"{summary.get('healthy', 0):,}")
    cols[2].metric("Tickets", f"{summary.get('tickets', 0):,}")
    cols[3].metric("Flag rate", f"{100 * float(summary.get('flag_rate', 0)):.2f}%")
    cols[4].metric("Care matched", f"{summary.get('care_tickets_correlated', 0):,}")
    cols[5].metric("Engine", str(summary.get("engine", "unknown")).split(".")[-1])
    st.caption(
        "Forecast = fitted KPI trend reaches an alarm threshold inside the horizon; "
        "proactive = the modem KPI has already crossed the threshold before the customer call."
    )


def render():
    st.title("LPR CPE Digital Twin / TAO")
    st.caption(
        "v2.4.0 P0 Fixed R3 Hotfix5 — predictive modem + Customer Care integration; "
        "simulation only; production writes disabled"
    )
    tabs = st.tabs(
        [
            "Generator",
            "Predictive Assurance",
            "Customer Care",
            "Data Explorer",
            "Subscriber 360",
            "Decision Control",
            "Release Status",
        ]
    )

    with tabs[0]:
        homes = st.number_input("Homes", min_value=1, max_value=500000, value=500)
        scenarios = st.multiselect(
            "Scenarios",
            [
                "slow_wifi",
                "no_service",
                "intermittent_service",
                "iptv_degradation",
                "fiber_cut",
                "hfc_ingress",
                "congestion",
                "power_outage",
                "storm",
                "flooding",
                "hurricane",
                "provisioning_error",
                "cpe_failure",
            ],
            default=["slow_wifi", "fiber_cut", "power_outage"],
        )
        enable_predictive = st.checkbox("Generate predictive modem snapshot", value=True)
        predictive_population = st.number_input(
            "Predictive modem population (0 = profile default)",
            min_value=0,
            max_value=500000,
            value=0,
            disabled=not enable_predictive,
        )
        predictive_days = st.slider(
            "Predictive trend window (days)",
            7,
            60,
            14,
            disabled=not enable_predictive,
        )
        provider = st.selectbox("LLM provider", ["fake", "disabled", "openai", "anthropic"])
        enable_llm = provider in {"openai", "anthropic"}
        model = st.text_input("Model name", disabled=not enable_llm)
        if st.button("Generate", type="primary"):
            payload = {
                "config": {
                    "profile": "smoke",
                    "homes": int(homes),
                    "scenarios": scenarios,
                    "enable_llm": enable_llm,
                    "llm_provider": provider,
                    "llm_model": model,
                    "enable_predictive": enable_predictive,
                    "predictive_population": int(predictive_population),
                    "predictive_days": int(predictive_days),
                }
            }
            try:
                result = _request("/api/runs", "POST", payload)
                _remember_run(result["run_id"])
                st.success(f"Run {result['run_id']} — quality passed: {result['quality']['passed']}")
                st.json(result)
            except Exception as exc:
                st.error(str(exc))

    with tabs[1]:
        st.subheader("Predictive modem pulls")
        st.write(
            "Run an explicit TR-069/TR-181-style predictive pull against the synthetic modem estate. "
            "In the integrated host repository the adapter uses `lpr_cpe_demo.predictive.scanner`; "
            "the standalone bundle retains a compatible offline fallback."
        )
        run_id = _run_id("predictive_run")
        pcols = st.columns(3)
        population = pcols[0].number_input(
            "Modems to scan", min_value=1, max_value=500000, value=500, step=100
        )
        days = pcols[1].slider("Trend days", 7, 60, 14)
        day_index = pcols[2].number_input("Simulation day", min_value=0, max_value=365, value=0)
        if st.button("Run predictive pull", type="primary") and run_id:
            try:
                summary = _request(
                    f"/api/runs/{urllib.parse.quote(run_id)}/predictive/scans",
                    "POST",
                    {"population": int(population), "days": int(days), "day_index": int(day_index)},
                )
                st.session_state["predictive_scan_id"] = summary["scan_id"]
                st.session_state["predictive_summary"] = summary
            except Exception as exc:
                st.error(str(exc))
        summary = st.session_state.get("predictive_summary")
        if summary and summary.get("canonical_run_id") == run_id:
            _show_predictive_summary(summary)
            scan_id = summary["scan_id"]
            try:
                detail = _request(
                    f"/api/runs/{urllib.parse.quote(run_id)}/predictive/scans/{urllib.parse.quote(scan_id)}?limit=500"
                )
                st.subheader("Predictive tickets")
                st.dataframe(detail["tickets"], use_container_width=True)
                with st.expander("Modem pull evidence"):
                    st.dataframe(detail["pulls"], use_container_width=True)
            except Exception as exc:
                st.error(str(exc))
        if run_id and st.button("Show canonical predictive snapshot"):
            try:
                result = _request(
                    f"/api/runs/{urllib.parse.quote(run_id)}/datasets/predictive_tickets?limit=1000"
                )
                st.dataframe(result["rows"], use_container_width=True)
            except Exception as exc:
                st.error(str(exc))

    with tabs[2]:
        st.subheader("Customer Care ticket review")
        st.write(
            "Care contacts are promoted to a governed ticket queue and correlated to predictive modem "
            "evidence, the canonical root incident, deterministic RCA, LLM/fake-agent assessment and reconciliation."
        )
        run_id = _run_id("care_run")
        filters = st.columns(3)
        status = filters[0].selectbox("Status", ["ALL", "OPEN", "CLOSED"])
        priority = filters[1].selectbox("Priority", ["ALL", "P1", "P2", "P3"])
        pred_filter = filters[2].selectbox("Predictive correlation", ["ALL", "MATCHED", "UNMATCHED"])
        if st.button("Load care queue") and run_id:
            params = {}
            if status != "ALL":
                params["status"] = status
            if priority != "ALL":
                params["priority"] = priority
            if pred_filter != "ALL":
                params["predictive_match"] = "true" if pred_filter == "MATCHED" else "false"
            query = urllib.parse.urlencode(params)
            suffix = f"?{query}" if query else ""
            try:
                queue = _request(
                    f"/api/runs/{urllib.parse.quote(run_id)}/care/tickets{suffix}"
                )
                st.session_state["care_queue"] = queue["rows"]
            except Exception as exc:
                st.error(str(exc))
        queue = st.session_state.get("care_queue", [])
        if queue:
            st.dataframe(queue, use_container_width=True)
            care_id = st.selectbox(
                "Ticket to review",
                [row["care_ticket_id"] for row in queue],
                format_func=lambda value: next(
                    f"{row['care_ticket_id']} — {row['priority']} — {row['category']} — "
                    f"predictive={'yes' if row['predictive_match'] else 'no'}"
                    for row in queue
                    if row["care_ticket_id"] == value
                ),
            )
            if st.button("Review selected care ticket"):
                try:
                    detail = _request(
                        f"/api/runs/{urllib.parse.quote(run_id)}/care/tickets/{urllib.parse.quote(care_id)}"
                    )
                    st.session_state["care_detail"] = detail
                except Exception as exc:
                    st.error(str(exc))
        detail = st.session_state.get("care_detail")
        if detail:
            left, right = st.columns(2)
            with left:
                st.markdown("**Care ticket**")
                st.json(detail["ticket"])
                st.markdown("**Predictive evidence**")
                if detail.get("predictive"):
                    st.json(detail["predictive"])
                else:
                    st.info("No predictive modem ticket preceded this customer contact.")
            with right:
                st.markdown("**Deterministic + agent reconciliation review**")
                st.json(detail.get("review"))
                st.markdown("**Control-plane case**")
                st.json(detail.get("case"))

    with tabs[3]:
        run_id = _run_id("data_run")
        dataset = st.selectbox("Dataset", DATASETS)
        limit = st.slider("Rows", 10, 1000, 100, 10)
        if st.button("Load dataset") and run_id:
            result = _request(
                f"/api/runs/{urllib.parse.quote(run_id)}/datasets/{dataset}?limit={limit}"
            )
            st.caption(f"Showing {result['returned']} of {result['total']} rows")
            st.dataframe(result["rows"], use_container_width=True)
            st.download_button(
                "Download displayed rows (JSON)",
                json.dumps(result["rows"], indent=2),
                file_name=f"{dataset}.json",
                mime="application/json",
            )

    with tabs[4]:
        run_id = _run_id("sub_run")
        service_id = st.text_input("Service ID", value="SVC-0000001")
        if st.button("Load Subscriber 360") and run_id:
            result = _request(
                f"/api/runs/{urllib.parse.quote(run_id)}/subscriber/{urllib.parse.quote(service_id)}"
            )
            st.subheader("Subscriber / service master")
            st.json(result["subscriber"])
            for name, rows in result["related"].items():
                st.subheader(name)
                st.dataframe(rows, use_container_width=True)

    with tabs[5]:
        run_id = _run_id("decision_run")
        case_id = st.text_input("Case ID", value="CASE-0000001-SLOW_WIFI")
        if st.button("Load case") and run_id:
            st.session_state["case"] = _request(
                f"/api/runs/{urllib.parse.quote(run_id)}/cases/{urllib.parse.quote(case_id)}"
            )
        case = st.session_state.get("case")
        if case:
            st.json(case)
            if case["state"] == "WAITING_HUMAN":
                response = st.selectbox(
                    "Decision", ["approve", "reject", "request_evidence", "escalate"]
                )
                rationale = st.text_area("Rationale")
                if st.button("Submit decision"):
                    payload = {
                        "case_id": case["case_id"],
                        "revision": case["revision"],
                        "response": response,
                        "actor": USER,
                        "rationale": rationale or "Operator decision",
                    }
                    updated = _request(
                        f"/api/runs/{urllib.parse.quote(run_id)}/decisions",
                        "POST",
                        payload,
                    )
                    st.session_state["case"] = updated
                    st.success(f"Case state: {updated['state']}")
                    st.rerun()

    with tabs[6]:
        st.write(
            "P0 release controls: causal chain, evidence-backed closure, immutable canonical run identity, "
            "path containment, fail-closed model reconciliation, human gate for side effects, predictive-to-care "
            "deduplication and root-incident correlation."
        )
        st.success(
            "Hotfix5 adds predictive modem pulls and Customer Care review directly to the Docker UI/API. "
            "On-demand predictive scans are stored as immutable child artifacts and do not mutate the parent run."
        )


render()
