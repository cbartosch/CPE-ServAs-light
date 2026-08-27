from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _ruff_config() -> dict:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["tool"]["ruff"]


def test_lint_baseline_is_explicit_and_rule_scoped() -> None:
    baseline = _ruff_config()["lint"]["per-file-ignores"]
    assert baseline
    assert all("*" not in path for path in baseline)
    assert all("ALL" not in rules for rules in baseline.values())
    assert all("F821" not in rules for rules in baseline.values())


def test_stage1_and_future_feature_files_are_not_baselined() -> None:
    baseline = _ruff_config()["lint"]["per-file-ignores"]
    protected = {
        "src/lpr_cpe_demo/cadi.py",
        "src/lpr_cpe_demo/caddi.py",
        "src/lpr_cpe_demo/dalli.py",
        "src/lpr_cpe_demo/digital_twin/install_assurance.py",
        "src/lpr_cpe_demo/measurement.py",
        "src/lpr_cpe_demo/ui/measurement.py",
        "tests/test_cadi.py",
        "tests/test_install_assurance.py",
        "tests/test_measurement_semantics.py",
        "tests/test_release_gates.py",
        "tests/test_lint_baseline.py",
    }
    assert protected.isdisjoint(baseline)


def test_correctness_fixes_are_present() -> None:
    footprint = (
        ROOT / "src/lpr_cpe_demo/ui/pages/footprint.py"
    ).read_text(encoding="utf-8")
    widgets = (ROOT / "tests/test_ui_widgets.py").read_text(encoding="utf-8")
    assert "INITIAL_VIEW" in footprint.split("from lpr_cpe_demo.geo_layers", 1)[1]
    assert "from typing import Any" in widgets
