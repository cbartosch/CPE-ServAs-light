from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_control_tower_crosslink_is_responsive_and_complete() -> None:
    source = (ROOT / "src/lpr_cpe_demo/ui/theme_dark.py").read_text(encoding="utf-8")
    assert "display: flex" in source
    assert "flex-wrap: wrap" in source
    assert "@media (max-width: 1100px)" in source
    assert "grid-template-columns: minmax(0, 1fr) auto" not in source
    assert 'href="digital-twin?view=caddi"' in source
    assert "DvSum CADDI/Genesys contract" in source
    assert 'href="footprint"' in source
    assert 'href="simulator"' in source


def test_streamlit_header_matches_dark_surface() -> None:
    source = (ROOT / "src/lpr_cpe_demo/ui/theme_dark.py").read_text(encoding="utf-8")
    assert '[data-testid="stHeader"]' in source
    assert '[data-testid="stToolbar"]' in source
    assert "rgba(23,23,23,0.98)" in source
