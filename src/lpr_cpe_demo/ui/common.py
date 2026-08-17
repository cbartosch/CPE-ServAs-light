from __future__ import annotations

import streamlit as st

from lpr_cpe_demo.ui.client import DemoAPI


ROLES = [
    "viewer",
    "noc_analyst",
    "l2_sme",
    "dispatcher",
    "plant_supervisor",
    "operations_supervisor",
]


def api() -> DemoAPI:
    if "api_client" not in st.session_state:
        st.session_state.api_client = DemoAPI()
    return st.session_state.api_client


def identity() -> tuple[str, str]:
    return (
        str(st.session_state.get("demo_user", "demo.operator")),
        str(st.session_state.get("demo_role", "operations_supervisor")),
    )


def demo_header(title: str, subtitle: str = "") -> None:
    st.title(title)
    if subtitle:
        st.caption(subtitle)


def render_banner() -> None:
    st.warning(
        "DEMONSTRATION MODE — NXT, CPE, WFM and jTrack operations are simulated. "
        "No production system writes are enabled.",
        icon="⚠️",
    )


def stage_label(value: str) -> str:
    return value.replace("_", " ").title()
