from __future__ import annotations

import streamlit as st

from lpr_cpe_demo.config import get_settings

from lpr_cpe_demo.ui.client import APIError
from lpr_cpe_demo.ui.common import api, demo_header, identity, render_banner


DOMAINS = [
    "cpe",
    "wifi_or_home",
    "premise_wiring",
    "drop",
    "hfc_tap",
    "pon_odp",
    "shared_network",
    "plant",
    "provisioning",
    "service_platform",
    "commercial_power",
    "unknown",
]


@st.fragment(run_every=f"{get_settings().ui_refresh_seconds}s")
def live_decisions() -> None:
    try:
        approvals = api().approvals("pending")
    except APIError as exc:
        st.error(str(exc))
        return
    st.metric("Pending human decisions", len(approvals))
    if not approvals:
        st.success("No approvals are waiting.")
        return
    user, role = identity()
    for approval in approvals:
        with st.expander(
            f"{approval['kind'].replace('_', ' ').title()} · {approval['incident_id']} · {approval['requested_role']}",
            expanded=True,
        ):
            st.caption(f"Approval ID: {approval['approval_id']} | Action: {approval['action_type']}")
            st.json(approval["proposal"])
            with st.form(f"decision-{approval['approval_id']}"):
                decision = st.selectbox(
                    "Decision",
                    ["approve", "override", "request_more", "reject"],
                    key=f"choice-{approval['approval_id']}",
                )
                selected_domain = None
                selected_option = None
                if approval["kind"] == "rca_review":
                    suggested = (
                        approval.get("proposal", {})
                        .get("deterministic", {})
                        .get("recommended_domain", "unknown")
                    )
                    selected_domain = st.selectbox(
                        "Approved responsibility domain",
                        DOMAINS,
                        index=DOMAINS.index(suggested) if suggested in DOMAINS else DOMAINS.index("unknown"),
                        key=f"domain-{approval['approval_id']}",
                    )
                else:
                    proposal = approval.get("proposal", {})
                    reviewed = [
                        item.get("action_type")
                        for item in (proposal.get("best"), proposal.get("next_best"))
                        if item and item.get("action_type")
                    ]
                    if reviewed:
                        selected_option = st.selectbox(
                            "Reviewed action",
                            reviewed,
                            key=f"action-{approval['approval_id']}",
                        )
                reason = st.text_area(
                    "Decision rationale",
                    value="Approved after reviewing evidence and policy controls." if decision == "approve" else "",
                    key=f"reason-{approval['approval_id']}",
                )
                submitted = st.form_submit_button("Submit decision", type="primary")
            if submitted:
                payload = {
                    "decision": decision,
                    "actor": user,
                    "role": role,
                    "reason": reason,
                    "selected_domain": selected_domain,
                    "selected_option": selected_option if decision == "override" else None,
                }
                try:
                    state = api().decide(
                        approval["approval_id"], payload, user=user, role=role
                    )
                except APIError as exc:
                    st.error(str(exc))
                else:
                    st.session_state.selected_incident_id = state["incident_id"]
                    st.success(f"Decision recorded. Case stage: {state['stage'].replace('_', ' ')}")
                    st.rerun()


def render() -> None:
    demo_header(
        "Human Decision Center",
        "Approve, override, request more evidence or reject RCA, remote, dispatch and handover proposals.",
    )
    render_banner()
    user, role = identity()
    st.caption(f"Acting as {user} with role `{role}`.")
    live_decisions()
