"""Regression guards for target Ruff 0.13.3 findings from the v1.27.12 gate."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_repair_client_uses_default_utf8_encoding() -> None:
    source = _source("scripts/repair_current_schema_run.py")
    assert '.encode("utf-8")' not in source


def test_repair_client_has_no_unused_sys_import() -> None:
    tree = ast.parse(_source("scripts/repair_current_schema_run.py"))
    imported = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "sys" not in imported


def test_ui_client_import_block_is_ruff_stable() -> None:
    source = _source("src/lpr_cpe_demo/ui/client.py")
    expected = (
        "from __future__ import annotations\n\n"
        "from typing import Any\n\n"
        "DEFAULT_REQUEST_TIMEOUT_SECONDS"
    )
    assert source.startswith(expected)
    module = ast.parse(source)
    top_level_imports = [
        node
        for node in module.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert len(top_level_imports) == 2
    assert "import os" in source
    assert "import httpx" in source


def test_new_release_surfaces_respect_line_length() -> None:
    for relative in (
        "scripts/runtime_smoke.py",
        "scripts/verify_manifest.py",
        "src/lpr_cpe_demo/digital_twin/executive_style.py",
        "src/lpr_cpe_demo/digital_twin/install_assurance.py",
        "src/lpr_cpe_demo/ui/client.py",
        "tests/test_predictive_workspace_layout_regression.py",
        "tests/test_reachability.py",
        "tests/test_runtime_connectivity_regressions.py",
    ):
        lines = _source(relative).splitlines()
        offenders = [index for index, line in enumerate(lines, 1) if len(line) > 100]
        assert not offenders, f"{relative}: lines over 100 columns: {offenders}"


def test_install_assurance_generator_calls_are_not_double_parenthesized() -> None:
    source = _source("src/lpr_cpe_demo/digital_twin/install_assurance.py")
    assert not re.search(r"\b(?:all|any|sum)\(\(", source)


def test_first_party_imports_keep_canonical_module_order() -> None:
    api = _source("src/lpr_cpe_demo/api/main.py")
    dashboard = _source("src/lpr_cpe_demo/dashboard.py")
    cockpit = _source("src/lpr_cpe_demo/ui/pages/cockpit.py")
    tests = _source("tests/test_caddi.py")

    assert api.index("from lpr_cpe_demo.caddi") < api.index("from lpr_cpe_demo.config")
    assert dashboard.index("from .caddi") < dashboard.index("from .commercial")
    assert cockpit.index("from lpr_cpe_demo.caddi") < cockpit.index(
        "from lpr_cpe_demo.config"
    )
    assert tests.index("from lpr_cpe_demo.caddi") < tests.index("from lpr_cpe_demo.cadi")


def test_protected_lint_paths_have_no_duplicate_constants() -> None:
    tree = ast.parse(_source("tests/test_lint_baseline.py"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Set):
            continue
        values = [
            item.value
            for item in node.elts
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        ]
        assert len(values) == len(set(values))
