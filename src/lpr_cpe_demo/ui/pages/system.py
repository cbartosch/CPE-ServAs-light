from __future__ import annotations

import streamlit as st

from lpr_cpe_demo.ui.client import APIError
from lpr_cpe_demo.ui.common import api, demo_header, render_banner


def render() -> None:
    demo_header("System and Control Monitor", "Runtime mode, model, MCP tools and safety posture.")
    render_banner()
    try:
        status = api().get("/api/system/status")
    except APIError as exc:
        st.error(str(exc))
        return
    cols = st.columns(4)
    cols[0].metric("Workflow engine", status.get("workflow_engine_active", "unknown"))
    cols[1].metric("Model provider", status.get("model_provider", "unknown"))
    cols[2].metric("MCP status", status.get("mcp_status", "unknown"))
    cols[3].metric("Writes permitted", str(status.get("writes_permitted", False)))
    st.subheader("Safety and runtime details")
    st.json(status)
    if st.button("Reset all demo cases", type="secondary"):
        try:
            api().post("/api/reset", {"confirm": "RESET DEMO"})
            st.success("Demo data reset.")
        except APIError as exc:
            st.error(str(exc))
