from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request

import pandas as pd
import plotly.express as px
import streamlit as st

from lpr_cpe_demo.config import get_settings
from lpr_cpe_demo.caddi import caddi_contract, caddi_contract_rows
from lpr_cpe_demo.ui.client import APIError
from lpr_cpe_demo.ui.common import (
    api,
    demo_header,
    digital_twin_api,
    render_banner,
    stage_label,
)
from lpr_cpe_demo.ui.measurement import (
    format_metric,
    render_common_kpis,
    render_measurement_context,
    render_status_partition,
)


def _active_run_comparison(operations: dict) -> None:
    """Show why live operations and the Digital Twin may legitimately differ."""

    try:
        active = digital_twin_api().active_projection()
    except APIError:
        active = None
    if not active:
        st.caption(
            "No active Digital Twin projection is available for comparison. "
            "The live Operations metrics remain complete for their own repository."
        )
        return

    keys = (
        "root_incidents",
        "at_risk_services",
        "predictive_match_rate_pct",
        "closed_root_incidents",
        "pending_approvals",
        "scan_coverage_pct",
    )
    rows = []
    for key in keys:
        active_record = active.get("metrics", {}).get(key, {})
        operations_record = operations.get("metrics", {}).get(key, {})
        percent = key.endswith("_pct")
        rows.append(
            {
                "Metric": active_record.get("label") or operations_record.get("label") or key,
                "Digital Twin active run": format_metric(
                    active_record.get("value"),
                    percent=percent,
                ),
                "Live Operations": format_metric(
                    operations_record.get("value"),
                    percent=percent,
                ),
                "Same grain": active_record.get("grain") == operations_record.get("grain"),
            }
        )
    with st.expander("Reconcile with the active Digital Twin run", expanded=False):
        st.warning(
            "These columns use the same metric definitions but different populations. "
            "Live Operations is not implicitly linked to the active Digital Twin run; "
            "therefore values are not expected to match until shared run/service IDs are projected."
        )
        st.dataframe(rows, hide_index=True, use_container_width=True)


def _install_assurance_projection() -> dict | None:
    base = os.getenv("DT_API_URL", "http://digital-twin-api:8001")
    user = os.getenv("DT_USER", "demo")
    password = os.getenv("DT_PASSWORD", "CHANGE_ME")
    request = urllib.request.Request(base + "/api/install-assurance/projection")
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read())
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError):
        return None


def _install_assurance_panel() -> None:
    projection = _install_assurance_projection()
    st.subheader("24-Hour Install Assurance")
    if not projection:
        st.caption(
            "No active install watch is available. Install supervision remains "
            "separate from the break/fix incident queue."
        )
        st.markdown(
            '<a href="digital-twin?view=install-assurance" target="_self">'
            "Open Install Assurance</a>",
            unsafe_allow_html=True,
        )
        return
    summary = projection["summary"]
    lifecycle = summary["lifecycle_partition"]
    workload = summary["workload"]
    columns = st.columns(6)
    columns[0].metric("Active", lifecycle.get("ACTIVE", 0))
    columns[1].metric("Recovering", lifecycle.get("RECOVERING", 0))
    columns[2].metric("Passed", lifecycle.get("PASSED_24H", 0))
    columns[3].metric("Promoted", lifecycle.get("PROMOTED_TO_INCIDENT", 0))
    columns[4].metric("Clean Boots", workload.get("clean_boots_work_orders", 0))
    columns[5].metric("MR handoffs", workload.get("maintenance_requests", 0))
    st.caption(
        "Episode lifecycle is mutually exclusive. Workload counters are separate "
        "and may overlap with promoted episodes. DvSum CADDI receives a "
        "customer-safe projection; Operations owns execution and closure."
    )
    st.markdown(
        '<a href="digital-twin?view=install-assurance" target="_self">'
        "Open the supervised-install queue</a>",
        unsafe_allow_html=True,
    )


@st.fragment(run_every=f"{get_settings().ui_refresh_seconds}s")
def live_cockpit() -> None:
    try:
        projection = api().get("/api/operations-projection")
        incidents = api().incidents()
    except APIError as exc:
        st.error(str(exc))
        return

    render_measurement_context(projection, title="Live Operations measurement context")
    render_common_kpis(projection)
    st.subheader("Root-incident status")
    render_status_partition(projection)

    workload = projection.get("workload", {})
    cols = st.columns(5)
    cols[0].metric("Pending approvals", int(workload.get("pending_approvals", 0)))
    cols[1].metric("Remote attempts", int(workload.get("remote_attempts", 0)))
    cols[2].metric("Field visits", int(workload.get("field_visits", 0)))
    cols[3].metric("MR attempts", int(workload.get("mr_attempts", 0)))
    cols[4].metric("Returned to RCA", int(workload.get("returned_to_rca", 0)))
    _active_run_comparison(projection)

    if not incidents:
        st.info("Start a scenario to populate the cockpit.")
        return
    frame = pd.DataFrame(
        [
            {
                "incident_id": item["incident_id"],
                "technology": item["technology"],
                "stage": stage_label(item["stage"]),
                "status": item["status"],
                "owner": item["current_owner"],
                "priority": item["priority"],
                "agreement": item.get("domain_agreement", "unknown"),
                "field_visits": item.get("field_visits", 0),
                "mr_attempts": item.get("mr_attempts", 0),
            }
            for item in incidents
        ]
    )
    left, right = st.columns(2)
    with left:
        chart = frame.groupby("stage", as_index=False).size()
        st.plotly_chart(
            px.bar(chart, x="stage", y="size", title="Incidents by workflow stage"),
            use_container_width=True,
        )
    with right:
        technology = frame.groupby("technology", as_index=False).size()
        st.plotly_chart(
            px.pie(
                technology,
                names="technology",
                values="size",
                title="Technology mix",
            ),
            use_container_width=True,
        )
    st.subheader("Incident queue")
    event = st.dataframe(
        frame,
        hide_index=True,
        use_container_width=True,
        selection_mode="single-row",
        on_select="rerun",
    )
    if event.selection.rows:
        selected = frame.iloc[event.selection.rows[0]]["incident_id"]
        st.session_state.selected_incident_id = selected
        st.info(
            f"Selected {selected}. Open the Incident Workbench from the navigation menu."
        )


def _caddi_boundary() -> None:
    contract = caddi_contract()
    st.info(
        "DvSum CADDI remains the Genesys-facing call-center context layer. This Operations "
        "Cockpit remains the execution view for incidents, field work, MRs, "
        "maintenance, repair and validated closure. No live DvSum CADDI adapter is connected."
    )
    with st.expander("DvSum CADDI handoff and source-of-truth boundary", expanded=False):
        st.write(contract["source_of_truth_policy"])
        st.write(contract["operations_boundary"])
        st.dataframe(caddi_contract_rows(), hide_index=True, use_container_width=True)


def render() -> None:
    demo_header(
        "Operations Cockpit",
        "Live workflow records projected through the shared measurement contract.",
    )
    render_banner()
    _install_assurance_panel()
    _caddi_boundary()
    live_cockpit()
