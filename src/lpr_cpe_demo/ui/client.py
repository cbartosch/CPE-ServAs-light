from __future__ import annotations

import os
from typing import Any

import httpx


class APIError(RuntimeError):
    pass


class DemoAPI:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("API_URL", "http://localhost:8000")).rstrip("/")

    def _request(
        self,
        method: str,
        path: str,
        *,
        user: str = "demo.operator",
        role: str = "operations_supervisor",
        **kwargs: Any,
    ) -> Any:
        headers = dict(kwargs.pop("headers", {}))
        headers.update({"X-Demo-User": user, "X-Demo-Role": role})
        try:
            response = httpx.request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                timeout=20.0,
                **kwargs,
            )
        except httpx.HTTPError as exc:
            raise APIError(f"API unavailable: {exc}") from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise APIError(f"{response.status_code}: {detail}")
        if not response.content:
            return None
        return response.json()

    def get(self, path: str) -> Any:
        return self._request("GET", path)

    def post(self, path: str, payload: dict[str, Any] | None = None, **identity: str) -> Any:
        return self._request("POST", path, json=payload, **identity)

    def scenarios(self) -> list[dict[str, Any]]:
        return list(self.get("/api/scenarios"))

    def start(self, scenario_name: str) -> dict[str, Any]:
        return dict(self.post(f"/api/scenarios/{scenario_name}/start", {"run_until_pause": True}))

    def incidents(self) -> list[dict[str, Any]]:
        return list(self.get("/api/incidents"))

    def incident(self, incident_id: str) -> dict[str, Any]:
        return dict(self.get(f"/api/incidents/{incident_id}"))

    def approvals(self, status: str = "pending") -> list[dict[str, Any]]:
        return list(self.get(f"/api/approvals?status={status}"))

    def decide(
        self,
        approval_id: str,
        payload: dict[str, Any],
        *,
        user: str,
        role: str,
    ) -> dict[str, Any]:
        return dict(
            self.post(
                f"/api/approvals/{approval_id}/decision",
                payload,
                user=user,
                role=role,
            )
        )
