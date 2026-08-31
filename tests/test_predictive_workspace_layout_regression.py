"""Regression guards for the executive workspace navigation layout."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_workspace_navigation_preserves_readable_summary_width() -> None:
    style = _source("src/lpr_cpe_demo/digital_twin/executive_style.py")
    markup = _source("src/lpr_cpe_demo/digital_twin/streamlit_app.py")

    assert ".lpr-crosslink-summary" in style
    assert '<div class="lpr-crosslink-summary">' in markup
    assert "display:flex;" in style
    assert "flex-direction:column;" in style
    assert "grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));" in style
    assert "white-space:normal;" in style
    assert "grid-template-columns:minmax(0,1fr) auto" not in style
    assert "connected operational views" in markup


def test_workspace_header_uses_the_same_dark_surface_as_the_page() -> None:
    style = _source("src/lpr_cpe_demo/digital_twin/executive_style.py")

    assert '[data-testid="stHeader"]' in style
    assert '[data-testid="stToolbar"]' in style
    assert "background: #383C41 !important;" in style
    assert "fill: currentColor !important;" in style
