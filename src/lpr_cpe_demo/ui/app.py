from __future__ import annotations

import streamlit as st

from lpr_cpe_demo.ui.common import ROLES
from lpr_cpe_demo.ui.pages import (cockpit, decisions, footprint, incident,
                                   model_monitor, scenarios, system)

# DEMONSTRATION MODE: the Human Decision Center controls simulated actions only.

st.set_page_config(
    page_title="LPR CPE Service Assurance",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .block-container {padding-top: 1.25rem; padding-bottom: 2rem;}
    [data-testid="stMetric"] {border: 1px solid #d8e1eb; padding: 0.8rem; border-radius: 0.65rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("LPR CPE Assurance")
    st.session_state.demo_user = st.text_input(
        "Demo user", value=st.session_state.get("demo_user", "demo.operator")
    )
    current_role = st.session_state.get("demo_role", "operations_supervisor")
    st.session_state.demo_role = st.selectbox(
        "Role", ROLES, index=ROLES.index(current_role) if current_role in ROLES else 0
    )
    st.warning("DEMONSTRATION MODE", icon="⚠️")
    st.caption("Identity and role selection are mock-only. Production must use enterprise authentication.")

pages = {
    "Operate": [
        st.Page(scenarios.render, title="Scenario Launcher", icon="▶️", url_path="scenarios"),
        st.Page(cockpit.render, title="Operations Cockpit", icon="📊", url_path="cockpit", default=True),
        st.Page(incident.render, title="Incident Workbench", icon="🔎", url_path="incident"),
        st.Page(decisions.render, title="Decision Center", icon="✅", url_path="decisions"),
        st.Page(footprint.render, title="Footprint & Dispatch", icon="🗺️", url_path="footprint"),
    ],
    "Govern": [
        st.Page(model_monitor.render, title="Decision & Model Monitor", icon="🧭", url_path="model-monitor"),
        st.Page(system.render, title="System Monitor", icon="🛡️", url_path="system"),
    ],
}

navigation = st.navigation(pages, position="sidebar", expanded=True)
navigation.run()
