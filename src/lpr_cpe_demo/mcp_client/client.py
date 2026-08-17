from __future__ import annotations

from abc import ABC, abstractmethod
from itertools import count
from typing import Any

import httpx

from lpr_cpe_demo.config import Settings, get_settings
from lpr_cpe_demo.domain import MCPToolResult
from lpr_cpe_demo.mcp_server.tools import ToolRegistry, ToolRejection


class MCPClientError(RuntimeError):
    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class MCPClient(ABC):
    def verify_compatibility(self) -> None:
        """Fail fast when the configured MCP profile and server do not match."""

    @abstractmethod
    def list_tools(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPToolResult:
        raise NotImplementedError


class HTTPMCPClient(MCPClient):
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._ids = count(1)


    def verify_compatibility(self) -> None:
        try:
            response = httpx.get(
                self.settings.mcp_health_url,
                timeout=min(self.settings.model_timeout_seconds, 10.0),
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MCPClientError(f"MCP health check failed: {exc}") from exc
        payload = response.json()
        observed_version = str(payload.get("protocol_version") or "")
        observed_profile = str(payload.get("protocol_profile") or "")
        if observed_version != self.settings.mcp_protocol_version:
            raise MCPClientError(
                "MCP protocol version mismatch: "
                f"configured={self.settings.mcp_protocol_version}, observed={observed_version}"
            )
        if observed_profile and observed_profile != self.settings.mcp_profile:
            raise MCPClientError(
                "MCP profile mismatch: "
                f"configured={self.settings.mcp_profile}, observed={observed_profile}"
            )
        if payload.get("stateless") is not True:
            raise MCPClientError("MCP simulator must advertise stateless=true")

    def _headers(self, method: str, name: str) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Mcp-Protocol-Version": self.settings.mcp_protocol_version,
            "Mcp-Method": method,
            "Mcp-Name": name,
        }

    def _post(self, method: str, params: dict[str, Any], *, name: str) -> dict[str, Any]:
        payload = {"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params}
        try:
            response = httpx.post(
                self.settings.mcp_url,
                headers=self._headers(method, name),
                json=payload,
                timeout=self.settings.model_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise MCPClientError(f"MCP server unavailable: {exc}") from exc
        data = response.json()
        if response.status_code >= 400 or "error" in data:
            error = data.get("error") or {}
            error_data = error.get("data") or {}
            raise MCPClientError(
                str(error.get("message") or "MCP call failed"),
                code=error_data.get("code"),
                status_code=response.status_code,
            )
        return data["result"]

    def list_tools(self) -> list[dict[str, Any]]:
        result = self._post("tools/list", {}, name="lpr-cpe-demo")
        return list(result.get("tools", []))

    def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPToolResult:
        result = self._post(
            "tools/call",
            {"name": name, "arguments": arguments},
            name=name,
        )
        return MCPToolResult(
            name=name,
            structured_content=dict(result.get("structuredContent") or {}),
            is_error=bool(result.get("isError", False)),
        )


class InProcessMCPClient(MCPClient):
    """Test and local fallback client using the same tool registry as the MCP service."""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def list_tools(self) -> list[dict[str, Any]]:
        return self.registry.list_tools()

    def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPToolResult:
        try:
            result = self.registry.call(name, arguments)
        except ToolRejection as exc:
            raise MCPClientError(exc.detail, code=exc.code, status_code=409) from exc
        return MCPToolResult(name=name, structured_content=result)
