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
    "subscriber_master", "scenario_manifests", "telemetry_tr181", "nxt_alarms", "contacts",
    "incidents", "work_orders", "field_evidence", "mrs", "validation_events", "resolution_events",
    "deterministic_decisions", "agent_decisions", "reconciliation_records", "human_decisions", "action_events",
]


def _request(path: str, method: str = "GET", body: dict | None = None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(API + path, data=data, method=method, headers={"Content-Type": "application/json"})
    token = base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
    req.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API {exc.code}: {detail}") from exc


def _remember_run(run_id: str):
    st.session_state["run_id"] = run_id


def render():
    st.title("LPR CPE Digital Twin / TAO")
    st.caption("v2.4.0 P0 Fixed R3 — simulation only; production writes disabled")
    tabs = st.tabs(["Generator", "Data Explorer", "Subscriber 360", "Decision Control", "Release Status"])

    with tabs[0]:
        homes = st.number_input("Homes", min_value=1, max_value=500000, value=500)
        scenarios = st.multiselect(
            "Scenarios",
            ["slow_wifi", "no_service", "intermittent_service", "iptv_degradation", "fiber_cut", "hfc_ingress", "congestion", "power_outage", "storm", "flooding", "hurricane", "provisioning_error", "cpe_failure"],
            default=["slow_wifi", "fiber_cut", "power_outage"],
        )
        provider = st.selectbox("LLM provider", ["fake", "disabled", "openai", "anthropic"])
        enable_llm = provider in {"openai", "anthropic"}
        model = st.text_input("Model name", disabled=not enable_llm)
        if st.button("Generate", type="primary"):
            payload = {"config": {"profile": "smoke", "homes": int(homes), "scenarios": scenarios, "enable_llm": enable_llm, "llm_provider": provider, "llm_model": model}}
            try:
                result = _request("/api/runs", "POST", payload)
                _remember_run(result["run_id"])
                st.success(f"Run {result['run_id']} — quality passed: {result['quality']['passed']}")
                st.json(result)
            except Exception as exc:
                st.error(str(exc))

    with tabs[1]:
        run_id = st.text_input("Run ID", value=st.session_state.get("run_id", ""), key="data_run")
        dataset = st.selectbox("Dataset", DATASETS)
        limit = st.slider("Rows", 10, 1000, 100, 10)
        if st.button("Load dataset") and run_id:
            result = _request(f"/api/runs/{urllib.parse.quote(run_id)}/datasets/{dataset}?limit={limit}")
            st.caption(f"Showing {result['returned']} of {result['total']} rows")
            st.dataframe(result["rows"], use_container_width=True)
            st.download_button("Download displayed rows (JSON)", json.dumps(result["rows"], indent=2), file_name=f"{dataset}.json", mime="application/json")

    with tabs[2]:
        run_id = st.text_input("Run ID", value=st.session_state.get("run_id", ""), key="sub_run")
        service_id = st.text_input("Service ID", value="SVC-0000001")
        if st.button("Load Subscriber 360") and run_id:
            result = _request(f"/api/runs/{urllib.parse.quote(run_id)}/subscriber/{urllib.parse.quote(service_id)}")
            st.subheader("Subscriber / service master")
            st.json(result["subscriber"])
            for name, rows in result["related"].items():
                st.subheader(name)
                st.dataframe(rows, use_container_width=True)

    with tabs[3]:
        run_id = st.text_input("Run ID", value=st.session_state.get("run_id", ""), key="decision_run")
        case_id = st.text_input("Case ID", value="CASE-0000001-SLOW_WIFI")
        if st.button("Load case") and run_id:
            st.session_state["case"] = _request(f"/api/runs/{urllib.parse.quote(run_id)}/cases/{urllib.parse.quote(case_id)}")
        case = st.session_state.get("case")
        if case:
            st.json(case)
            if case["state"] == "WAITING_HUMAN":
                response = st.selectbox("Decision", ["approve", "reject", "request_evidence", "escalate"])
                rationale = st.text_area("Rationale")
                if st.button("Submit decision"):
                    payload = {"case_id": case["case_id"], "revision": case["revision"], "response": response, "actor": USER, "rationale": rationale or "Operator decision"}
                    updated = _request(f"/api/runs/{urllib.parse.quote(run_id)}/decisions", "POST", payload)
                    st.session_state["case"] = updated
                    st.success(f"Case state: {updated['state']}")
                    st.rerun()

    with tabs[4]:
        st.write("P0 release controls: compile/test/smoke gate, causal chain, evidence-backed closure, immutable run identity, path containment, fail-closed model reconciliation, human gate for side effects.")
        st.info("Docker target-laptop verification remains required because Docker Engine was unavailable in the assembly environment.")


render()
