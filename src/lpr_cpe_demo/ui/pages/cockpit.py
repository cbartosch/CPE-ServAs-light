from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from lpr_cpe_demo.cadi import cadi_contract, cadi_contract_rows
from lpr_cpe_demo.config import get_settings
from lpr_cpe_demo.ui.client import APIError
from lpr_cpe_demo.ui.common import api, demo_header, render_banner, stage_label


@st.fragment(run_every=f"{get_settings().ui_refresh_seconds}s")
def live_cockpit() -> None:
    try:
        summary = api().get("/api/dashboard")
        incidents = api().incidents()
    except APIError as exc:
        st.error(str(exc))
        return
    cols = st.columns(5)
    for col, key, label in zip(
        cols,
        ["total", "waiting", "pending_approvals", "closed", "escalated"],
        ["Incidents", "Awaiting human", "Pending decisions", "Closed", "Escalated"],
        strict=True,
    ):
        col.metric(label, int(summary.get(key, 0)))
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
        tech = frame.groupby("technology", as_index=False).size()
        st.plotly_chart(
            px.pie(tech, names="technology", values="size", title="Technology mix"),
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
        st.info(f"Selected {selected}. Open the Incident Workbench from the navigation menu.")


def _cadi_boundary() -> None:
    contract = cadi_contract()
    st.info(
        "CADI remains the Genesys-facing call-center context layer. This Operations "
        "Cockpit remains the execution view for incidents, field work, MRs, "
        "maintenance, repair and validated closure. No live CADI adapter is connected."
    )
    with st.expander("CADI handoff and source-of-truth boundary", expanded=False):
        st.write(contract["source_of_truth_policy"])
        st.write(contract["operations_boundary"])
        st.dataframe(cadi_contract_rows(), hide_index=True, use_container_width=True)


def render() -> None:
    demo_header("Operations Cockpit", "Live read-model view of incidents, approvals and outcomes.")
    render_banner()
    _cadi_boundary()
    live_cockpit()
