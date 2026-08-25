"""Embedded Digital Twin / TAO page for the unified Streamlit application."""

from __future__ import annotations

from lpr_cpe_demo.digital_twin.streamlit_app import render as render_digital_twin


def render() -> None:
    """Render the Digital Twin inside the main LPR CPE navigation shell."""
    render_digital_twin()
