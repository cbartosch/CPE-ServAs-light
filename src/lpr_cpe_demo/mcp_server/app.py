from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from lpr_cpe_demo.config import Settings, get_settings
from lpr_cpe_demo.mcp_server.tools import ToolRegistry, ToolRejection


def create_app(
    *,
    settings: Settings | None = None,
    registry: ToolRegistry | None = None,
) -> FastAPI:
    configured_settings = settings or get_settings()
    configured_registry = registry or ToolRegistry(settings=configured_settings)
    app = FastAPI(title="LPR CPE MCP Simulation Server", version="1.2.0")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "mcp-sim",
            "protocol_profile": configured_settings.mcp_profile,
            "protocol_version": configured_settings.mcp_protocol_version,
            "implementation": "custom_strict_stateless_http",
            "stateless": True,
            "tools": len(configured_registry.list_tools()),
            "runtime_versions": _runtime_versions(),
        }

    @app.get("/tools")
    def tools() -> dict[str, Any]:
        return {"tools": configured_registry.list_tools()}

    @app.post("/mcp")
    async def mcp_endpoint(
        request: Request,
        mcp_protocol_version: str | None = Header(default=None, alias="Mcp-Protocol-Version"),
        mcp_method: str | None = Header(default=None, alias="Mcp-Method"),
        mcp_name: str | None = Header(default=None, alias="Mcp-Name"),
    ) -> JSONResponse:
        payload = await request.json()
        request_id = payload.get("id")
        method = payload.get("method")

        if configured_settings.mcp_strict_version:
            if mcp_protocol_version != configured_settings.mcp_protocol_version:
                return _error(
                    request_id,
                    -32001,
                    "UnsupportedProtocolVersionError",
                    {"supported": [configured_settings.mcp_protocol_version]},
                    status_code=400,
                )
            if not mcp_method or mcp_method != method:
                return _error(
                    request_id,
                    -32600,
                    "Mcp-Method header does not match JSON-RPC method",
                    status_code=400,
                )
            if not mcp_name:
                return _error(request_id, -32600, "Mcp-Name header is required", status_code=400)

        if payload.get("jsonrpc") != "2.0":
            return _error(request_id, -32600, "Invalid JSON-RPC version", status_code=400)

        try:
            if method == "tools/list":
                result = {"tools": configured_registry.list_tools()}
            elif method == "tools/call":
                params = payload.get("params") or {}
                name = params.get("name")
                arguments = params.get("arguments") or {}
                if not isinstance(name, str):
                    raise ToolRejection("TOOL_NAME_REQUIRED")
                structured = configured_registry.call(name, arguments)
                result = {
                    "content": [{"type": "text", "text": _summary_text(name, structured)}],
                    "structuredContent": structured,
                    "isError": False,
                }
            else:
                return _error(request_id, -32601, f"Method not found: {method}", status_code=404)
        except ToolRejection as exc:
            return _error(
                request_id,
                -32010,
                exc.detail,
                {"code": exc.code},
                status_code=409,
            )
        except KeyError as exc:
            return _error(request_id, -32602, f"Missing argument: {exc}", status_code=422)
        except Exception as exc:  # pragma: no cover - defensive outer boundary
            return _error(
                request_id,
                -32603,
                "Internal MCP tool error",
                {"detail": str(exc)},
                status_code=500,
            )

        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})

    return app


def _runtime_versions() -> dict[str, str]:
    packages = ("fastapi", "uvicorn", "mcp", "pydantic", "pydantic-settings", "python-dotenv")
    result: dict[str, str] = {}
    for package in packages:
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            result[package] = "not-installed"
    return result


def _summary_text(name: str, result: dict[str, Any]) -> str:
    return str(result.get("summary") or f"{name} completed")


def _error(
    request_id: Any,
    code: int,
    message: str,
    data: dict[str, Any] | None = None,
    *,
    status_code: int,
) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    if data:
        error["data"] = data
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "error": error},
        status_code=status_code,
    )


app = create_app()
