from __future__ import annotations

from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from lpr_cpe_demo.config import Settings
from lpr_cpe_demo.mcp_server.app import create_app
from lpr_cpe_demo.mcp_server.store import EffectStore
from lpr_cpe_demo.mcp_server.tools import ToolRegistry
from lpr_cpe_demo.workflow.scenarios import ScenarioCatalog


def _client(tmp_path: Path) -> TestClient:
    settings = Settings(
        _env_file=None,
        app_environment="test",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'unused.db'}",
        mcp_effect_db=str(tmp_path / "effects.db"),
        mcp_protocol_version="2026-07-28",
        mcp_strict_version=True,
    )
    registry = ToolRegistry(
        settings=settings,
        catalog=ScenarioCatalog(settings=settings),
        store=EffectStore(settings.mcp_effect_db),
    )
    return TestClient(create_app(settings=settings, registry=registry))


def test_mcp_health_and_tool_list_are_available(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["protocol_profile"] == "custom_stateless_2026"
        assert health.json()["protocol_version"] == "2026-07-28"
        assert health.json()["implementation"] == "custom_strict_stateless_http"
        assert {"fastapi", "uvicorn", "mcp", "pydantic"}.issubset(
            health.json()["runtime_versions"]
        )

        response = client.post(
            "/mcp",
            headers={
                "Mcp-Protocol-Version": "2026-07-28",
                "Mcp-Method": "tools/list",
                "Mcp-Name": "bundle-test",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        assert response.status_code == 200
        tools = response.json()["result"]["tools"]
        assert {item["name"] for item in tools} >= {
            "get_nxt_snapshot",
            "simulate_remote_action",
            "create_or_update_mr",
        }


def test_mcp_strict_protocol_rejects_version_or_header_mismatch(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        wrong_version = client.post(
            "/mcp",
            headers={
                "Mcp-Protocol-Version": "2025-11-25",
                "Mcp-Method": "tools/list",
                "Mcp-Name": "bundle-test",
            },
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        assert wrong_version.status_code == 400
        assert wrong_version.json()["error"]["message"] == "UnsupportedProtocolVersionError"

        mismatch = client.post(
            "/mcp",
            headers={
                "Mcp-Protocol-Version": "2026-07-28",
                "Mcp-Method": "tools/call",
                "Mcp-Name": "bundle-test",
            },
            json={"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}},
        )
        assert mismatch.status_code == 400
        assert "does not match" in mismatch.json()["error"]["message"]


def test_mcp_read_only_tool_returns_structured_content(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/mcp",
            headers={
                "Mcp-Protocol-Version": "2026-07-28",
                "Mcp-Method": "tools/call",
                "Mcp-Name": "get_nxt_snapshot",
            },
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "get_nxt_snapshot",
                    "arguments": {"scenario_name": "hfc_remote_success", "cycle": 0},
                },
            },
        )
        assert response.status_code == 200
        result = response.json()["result"]
        assert result["isError"] is False
        assert result["structuredContent"]["technology"] == "HFC"
        assert result["structuredContent"]["source"].startswith("CommScope ServAssure NXT")


def test_http_client_fails_fast_on_profile_or_version_mismatch(monkeypatch, tmp_path: Path) -> None:
    import httpx

    from lpr_cpe_demo.mcp_client import HTTPMCPClient, MCPClientError

    settings = Settings(
        _env_file=None,
        app_environment="test",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'unused.db'}",
        mcp_profile="custom_stateless_2026",
        mcp_protocol_version="2026-07-28",
        mcp_health_url="http://mcp.invalid/health",
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "protocol_profile": "custom_stateless_2026",
                "protocol_version": "2025-11-25",
                "stateless": True,
            },
        )

    transport = httpx.MockTransport(handler)

    def fake_get(url: str, **kwargs):
        with httpx.Client(transport=transport) as client:
            return client.get(url, **kwargs)

    monkeypatch.setattr(httpx, "get", fake_get)
    with pytest.raises(MCPClientError, match="version mismatch"):
        HTTPMCPClient(settings).verify_compatibility()
