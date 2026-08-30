from __future__ import annotations

import ast
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_compose_has_required_services_and_healthchecks() -> None:
    payload = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = payload["services"]
    assert {"postgres", "mcp-sim", "api", "ui", "test"}.issubset(services)
    for name in ("postgres", "mcp-sim", "api", "ui"):
        assert "healthcheck" in services[name]
    assert services["api"]["depends_on"]["mcp-sim"]["condition"] == "service_healthy"
    assert services["api"]["build"]["dockerfile"] == "docker/app.Dockerfile"
    assert services["mcp-sim"]["build"]["dockerfile"] == "docker/mcp.Dockerfile"
    assert "PIP_INDEX_URL" in services["api"]["build"]["args"]


def test_env_template_contains_safe_defaults() -> None:
    # .env is intentionally local/ignored and must not be required in a clean clone.
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "APPLICATION_MODE=simulation" in text
    assert "PRODUCTION_WRITES_ENABLED=false" in text
    assert "MODEL_PROVIDER=fake" in text
    assert "MCP_PROFILE=custom_stateless_2026" in text
    assert "MCP_PROTOCOL_VERSION=2026-07-28" in text
    assert "UI_REFRESH_SECONDS=2" in text


def test_streamlit_source_parses() -> None:
    source = (ROOT / "src/lpr_cpe_demo/ui/app.py").read_text(encoding="utf-8")
    ast.parse(source)
    common = (ROOT / "src/lpr_cpe_demo/ui/common.py").read_text(encoding="utf-8")
    assert "DEMONSTRATION MODE" in common
    decisions = (ROOT / "src/lpr_cpe_demo/ui/pages/decisions.py").read_text(encoding="utf-8")
    assert "Human Decision Center" in decisions
    monitor = (ROOT / "src/lpr_cpe_demo/ui/pages/model_monitor.py").read_text(encoding="utf-8")
    ast.parse(monitor)
    assert "Decision and Model Monitor" in monitor


def test_corporate_ca_support_is_present_without_disabling_tls() -> None:
    for name in ("docker/app.Dockerfile", "docker/mcp.Dockerfile"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "update-ca-certificates" in text
        assert "SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt" in text
        assert "--trusted-host" not in text
    assert (ROOT / "scripts/stage-ca.sh").exists()
    assert (ROOT / "scripts/stage-ca.ps1").exists()
    assert (ROOT / "scripts/tls-doctor.sh").exists()
    assert (ROOT / "scripts/tls-doctor.ps1").exists()


def test_requirement_sets_are_split_and_exactly_pinned() -> None:
    app = (ROOT / "requirements-app.txt").read_text(encoding="utf-8")
    mcp = (ROOT / "requirements-mcp.txt").read_text(encoding="utf-8")
    assert "streamlit==" in app
    assert "langgraph==" in app
    assert "streamlit" not in mcp
    assert "fastapi==" in mcp
