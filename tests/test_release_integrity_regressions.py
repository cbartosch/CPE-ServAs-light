from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_customer_care_deep_link_alias_is_present() -> None:
    source = (ROOT / "src/lpr_cpe_demo/digital_twin/streamlit_app.py").read_text(
        encoding="utf-8"
    )
    assert '"customer-care": "care"' in source


def test_changelog_leads_with_current_project_version() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    match = re.search(r'^version = "([^"]+)"', pyproject, re.M)
    assert match
    first_heading = next(
        line
        for line in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("## ")
    )
    assert first_heading.split()[1].startswith(match.group(1))


def test_active_runtime_is_python_3147_and_tls_verified() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'requires-python = ">=3.14.7,<3.14.8"' in pyproject
    for relative in (
        "Dockerfile",
        "docker/Dockerfile.digital-twin",
        "docker/app.Dockerfile",
        "docker/mcp.Dockerfile",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "3.14.7" in text
        assert "--trusted-host" not in text
        assert "PIP_STRICT_TLS" not in text
