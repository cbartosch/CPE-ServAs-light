from __future__ import annotations

import streamlit as st

from lpr_cpe_demo.ui.common import ROLES
from lpr_cpe_demo.ui.pages import (
    cockpit,
    control_tower,
    decisions,
    digital_twin,
    footprint,
    incident,
    model_monitor,
    scenarios,
    simulator,
    system,
)

# DEMONSTRATION MODE: the Human Decision Center controls simulated actions only.

st.set_page_config(
    page_title="LPR Service Assurance Command Center",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

from lpr_cpe_demo.ui import artwork, executive_theme, sidebar as model_sidebar, theme  # noqa: E402

st.markdown(
    theme.css(
        header_svg_data_uri=artwork.band_data_uri(),
        watermark_svg_data_uri=artwork.watermark_data_uri(),
        show_artwork=artwork.enabled(),
    ),
    unsafe_allow_html=True,
)
st.markdown(executive_theme.css(), unsafe_allow_html=True)

with st.sidebar:
    st.markdown(
        """
        <div class="lpr-brand-lockup">
          <div class="lpr-brand-eyebrow">LPR Executive Demo</div>
          <div class="lpr-brand-title">Service Assurance<br/>Command Center</div>
          <div class="lpr-brand-subtitle">Predict · Correlate · Resolve · Govern</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    model_sidebar.render()
    with st.expander("Demo controls", expanded=False):
        st.session_state.demo_user = st.text_input(
            "Demo user", value=st.session_state.get("demo_user", "demo.operator")
        )
        current_role = st.session_state.get("demo_role", "operations_supervisor")
        st.session_state.demo_role = st.selectbox(
            "Role", ROLES, index=ROLES.index(current_role) if current_role in ROLES else 0
        )
        st.caption("Simulation identity only; production requires enterprise authentication.")
    st.caption("● DEMONSTRATION MODE · production writes disabled")

pages = {
    "Executive": [
        st.Page(
            control_tower.render,
            title="Executive Control Tower",
            icon="🛰️",
            url_path="control-tower",
        ),
        st.Page(
            cockpit.render,
            title="Operations Overview",
            icon="📊",
            url_path="cockpit",
            default=True,
        ),
        st.Page(
            digital_twin.render,
            title="Predictive & Customer Care",
            icon="✨",
            url_path="digital-twin",
        ),
    ],
    "Operations": [
        st.Page(scenarios.render, title="Launch a Scenario", icon="▶️", url_path="scenarios"),
        st.Page(incident.render, title="Incident Story", icon="🔎", url_path="incident"),
        st.Page(decisions.render, title="Decision Center", icon="✅", url_path="decisions"),
        st.Page(footprint.render, title="Footprint & Dispatch", icon="🗺️", url_path="footprint"),
        st.Page(simulator.render, title="Cost & Fault Simulator", icon="💸", url_path="simulator"),
    ],
    "Governance": [
        st.Page(
            model_monitor.render,
            title="AI & Decision Governance",
            icon="🧭",
            url_path="model-monitor",
        ),
        st.Page(system.render, title="Platform Health", icon="🛡️", url_path="system"),
    ],
}

navigation = st.navigation(pages, position="sidebar", expanded=True)
navigation.run()
