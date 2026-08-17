from __future__ import annotations

import streamlit as st

from lpr_cpe_demo.ui.client import APIError
from lpr_cpe_demo.ui.common import api, demo_header, render_banner


def render() -> None:
    demo_header(
        "Scenario Launcher",
        "Start a controlled HFC or PON case and run it to the next human decision or terminal state.",
    )
    render_banner()
    try:
        scenarios = api().scenarios()
    except APIError as exc:
        st.error(str(exc))
        return
    if not scenarios:
        st.info("No scenarios are installed.")
        return
    labels = {f"{item['label']} ({item['technology']})": item for item in scenarios}
    selected_label = st.selectbox("Demonstration scenario", list(labels))
    selected = labels[selected_label]
    st.info(selected["description"])
    col1, col2 = st.columns(2)
    col1.metric("Technology", selected["technology"])
    col2.metric("Expected path", " → ".join(selected.get("expected_path") or ["RCA", "Decision"]))
    if st.button("Start scenario", type="primary", use_container_width=True):
        try:
            incident = api().start(selected["name"])
        except APIError as exc:
            st.error(str(exc))
            return
        st.session_state.selected_incident_id = incident["incident_id"]
        st.success(
            f"Started {incident['incident_id']}. Current stage: {incident['stage'].replace('_', ' ')}."
        )
