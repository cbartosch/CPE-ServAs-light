from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from lpr_cpe_demo.config import get_settings

from lpr_cpe_demo.ui.client import APIError
from lpr_cpe_demo.ui.common import api, demo_header, render_banner


@st.fragment(run_every=f"{get_settings().ui_refresh_seconds}s")
def live_model_monitor() -> None:
    try:
        incidents = api().incidents()
        approvals = list(api().get("/api/approvals"))
        system = api().get("/api/system/status")
    except APIError as exc:
        st.error(str(exc))
        return

    decision_rows: list[dict[str, object]] = []
    for item in incidents:
        deterministic = item.get("deterministic_rca") or {}
        assisted = item.get("llm_rca") or {}
        selected = item.get("selected_action") or {}
        decision_rows.append(
            {
                "incident_id": item["incident_id"],
                "technology": item["technology"],
                "deterministic_domain": deterministic.get("recommended_domain", "pending"),
                "assisted_domain": assisted.get("recommended_domain", "pending"),
                "assistant_source": assisted.get("source", "pending"),
                "assistant_confidence": assisted.get("confidence"),
                "agreement": item.get("domain_agreement", "unknown"),
                "gate_reason": item.get("gate_reason", "none"),
                "best_action": selected.get("action_type", "pending"),
                "status": item["status"],
            }
        )

    decisions = pd.DataFrame(decision_rows)
    approval_frame = pd.DataFrame(approvals)
    overrides = 0
    human_decisions = 0
    if not approval_frame.empty:
        human_decisions = int(approval_frame["status"].isin(["approved", "rejected", "request_more", "consumed"]).sum())
        overrides = int(approval_frame["selected_option"].notna().sum())
    disagreements = int((decisions["agreement"] == "disagree").sum()) if not decisions.empty else 0
    fallbacks = int((decisions["assistant_source"] == "fallback").sum()) if not decisions.empty else 0

    cols = st.columns(5)
    cols[0].metric("Assistant provider", system.get("model_provider", "unknown"))
    cols[1].metric("Human decisions", human_decisions)
    cols[2].metric("Domain disagreements", disagreements)
    cols[3].metric("Human overrides", overrides)
    cols[4].metric("Model fallbacks", fallbacks)

    st.caption(
        "Only structured RCA proposals, evidence references, confidence, policy results and human dispositions "
        "are displayed. Hidden model reasoning is not stored or exposed."
    )

    if decisions.empty:
        st.info("Start a scenario to populate the decision monitor.")
        return

    left, right = st.columns(2)
    with left:
        gate_counts = decisions.groupby("gate_reason", as_index=False).size()
        st.plotly_chart(
            px.bar(gate_counts, x="gate_reason", y="size", title="Decision gates"),
            use_container_width=True,
        )
    with right:
        action_counts = decisions.groupby("best_action", as_index=False).size()
        st.plotly_chart(
            px.pie(action_counts, names="best_action", values="size", title="Best-action recommendations"),
            use_container_width=True,
        )

    st.subheader("RCA and action decision register")
    st.dataframe(decisions, hide_index=True, use_container_width=True)

    if not approval_frame.empty:
        st.subheader("Human disposition register")
        columns = [
            "approval_id",
            "incident_id",
            "kind",
            "action_type",
            "status",
            "requested_role",
            "decided_by",
            "decision_reason",
            "selected_option",
            "decided_at",
            "consumed_at",
        ]
        st.dataframe(
            approval_frame[[column for column in columns if column in approval_frame.columns]],
            hide_index=True,
            use_container_width=True,
        )


def render() -> None:
    demo_header(
        "Decision and Model Monitor",
        "Structured RCA, best/next-best action, policy gates and human disposition across incidents.",
    )
    render_banner()
    live_model_monitor()
