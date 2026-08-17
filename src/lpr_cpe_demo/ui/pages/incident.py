from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from lpr_cpe_demo.config import get_settings

from lpr_cpe_demo.ui.client import APIError
from lpr_cpe_demo.ui.common import api, demo_header, render_banner, stage_label


STAGES = [
    "validate",
    "correlate",
    "evidence",
    "deterministic_rca",
    "llm_rca",
    "fusion",
    "action_ranking",
    "policy",
    "waiting_approval",
    "execute",
    "verify",
    "reconcile",
    "closed",
]


def _proposal_card(title: str, proposal: dict | None) -> None:
    st.markdown(f"#### {title}")
    if not proposal:
        st.caption("Not yet available")
        return
    st.metric("Responsibility domain", proposal["recommended_domain"])
    st.progress(float(proposal["confidence"]), text=f"Confidence {proposal['confidence']:.0%}")
    st.write(proposal["concise_rationale"])
    with st.expander("Hypotheses and evidence"):
        st.json(proposal)


@st.fragment(run_every=f"{get_settings().ui_refresh_seconds}s")
def live_incident(incident_id: str) -> None:
    try:
        item = api().incident(incident_id)
    except APIError as exc:
        st.error(str(exc))
        return
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Technology", item["technology"])
    col2.metric("Priority", item["priority"])
    col3.metric("Owner", item["current_owner"])
    own_deadline = datetime.fromisoformat(item["sla_deadline"])
    parent_raw = item.get("parent_sla_deadline")
    parent_deadline = datetime.fromisoformat(parent_raw) if parent_raw else None
    effective_deadline = (
        parent_deadline
        if item.get("sla_mode") == "inherits_parent" and parent_deadline is not None
        else own_deadline
    )
    col4.metric("Authoritative SLA", effective_deadline.strftime("%Y-%m-%d %H:%M"))
    st.markdown(
        "**Workflow:** "
        + " → ".join(
            (f"**{stage_label(stage)}**" if stage == item["stage"] else stage_label(stage))
            for stage in STAGES
        )
    )
    if item.get("pending_approval_id"):
        st.warning(f"Human decision required: {item['pending_approval_id']}")
    if item.get("parent_incident_id"):
        own_text = own_deadline.strftime("%Y-%m-%d %H:%M")
        parent_text = parent_deadline.strftime("%Y-%m-%d %H:%M") if parent_deadline else "not supplied"
        st.info(
            f"Common-cause child of {item['parent_incident_id']}. "
            f"Parent SLA is authoritative ({parent_text}); the child's original "
            f"deadline ({own_text}) remains preserved and is not reset."
        )

    tab_summary, tab_evidence, tab_actions, tab_timeline, tab_raw = st.tabs(
        ["RCA & Decisions", "Evidence", "Actions / Field", "Timeline", "Raw state"]
    )
    with tab_summary:
        left, right = st.columns(2)
        with left:
            _proposal_card("Deterministic RCA", item.get("deterministic_rca"))
        with right:
            _proposal_card("LLM-assisted RCA", item.get("llm_rca"))
        st.markdown(
            f"**Agreement:** `{item.get('domain_agreement')}`  |  "
            f"**Gate reason:** `{item.get('gate_reason')}`"
        )
        best = item.get("selected_action")
        next_best = item.get("next_best_action")
        if best:
            st.success(
                f"Best action: **{best['label']}** — expected success {best['expected_success']:.0%}."
            )
        if next_best:
            st.info(
                f"Next-best action: **{next_best['label']}** — use only after failure or ineligibility and re-RCA."
            )
        if item.get("policy_decision"):
            st.json(item["policy_decision"])
    with tab_evidence:
        evidence = pd.DataFrame(item.get("evidence") or [])
        if evidence.empty:
            st.info("Evidence has not yet been assembled.")
        else:
            st.dataframe(evidence, hide_index=True, use_container_width=True)
    with tab_actions:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Remote attempts", item.get("remote_attempts", 0))
        c2.metric("Self-help", item.get("self_help_attempts", 0))
        c3.metric("Field visits", item.get("field_visits", 0))
        c4.metric("MR attempts", item.get("mr_attempts", 0))
        st.dataframe(pd.DataFrame(item.get("action_history") or []), hide_index=True, use_container_width=True)
        if item.get("work_orders"):
            st.markdown("#### Work orders")
            st.json(item["work_orders"])
        if item.get("mr_records"):
            st.markdown("#### jTrack MR records")
            st.json(item["mr_records"])
    with tab_timeline:
        timeline = pd.DataFrame(item.get("timeline") or [])
        if not timeline.empty:
            st.dataframe(timeline, hide_index=True, use_container_width=True)
    with tab_raw:
        st.json(item)


def render() -> None:
    demo_header("Incident Workbench", "Evidence, RCA, best action, human gates and verified outcomes.")
    render_banner()
    try:
        incidents = api().incidents()
    except APIError as exc:
        st.error(str(exc))
        return
    if not incidents:
        st.info("Start a scenario first.")
        return
    ids = [item["incident_id"] for item in incidents]
    default = st.session_state.get("selected_incident_id")
    index = ids.index(default) if default in ids else 0
    incident_id = st.selectbox("Incident", ids, index=index)
    st.session_state.selected_incident_id = incident_id
    live_incident(incident_id)
