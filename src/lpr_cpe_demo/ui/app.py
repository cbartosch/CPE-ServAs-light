from __future__ import annotations

import streamlit as st

from lpr_cpe_demo.ui.common import ROLES
from lpr_cpe_demo.ui.pages import (cockpit, decisions, footprint, incident,
                                   model_monitor, scenarios, simulator, system)

# DEMONSTRATION MODE: the Human Decision Center controls simulated actions only.

st.set_page_config(
    page_title="LPR CPE Service Assurance",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Visual identity. Artwork is original SVG confined to the header band and a
# corner watermark, at an opacity capped in ui.theme; readability of every text
# pairing is asserted by tests/test_theme.py rather than eyeballed.
from lpr_cpe_demo.ui import artwork, theme  # noqa: E402

st.markdown(
    theme.css(header_svg_data_uri=artwork.band_data_uri(),
              watermark_svg_data_uri=artwork.watermark_data_uri(),
              show_artwork=artwork.enabled()),
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
        st.Page(simulator.render, title="Fault Simulator & Cost", icon="💸", url_path="simulator"),
    ],
    "Govern": [
        st.Page(model_monitor.render, title="Decision & Model Monitor", icon="🧭", url_path="model-monitor"),
        st.Page(system.render, title="System Monitor", icon="🛡️", url_path="system"),
    ],
}

navigation = st.navigation(pages, position="sidebar", expanded=True)
navigation.run()
