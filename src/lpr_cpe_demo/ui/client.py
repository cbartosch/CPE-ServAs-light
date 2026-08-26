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


class DigitalTwinAPI:
    """Read the Digital Twin API with the demo's explicit Basic Auth boundary."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self.base_url = (
            base_url or os.getenv("DT_API_URL", "http://localhost:8001")
        ).rstrip("/")
        self.username = username or os.getenv("DT_USER", "demo")
        self.password = password or os.getenv("DT_PASSWORD", "CHANGE_ME")

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = httpx.request(
                method,
                f"{self.base_url}{path}",
                auth=(self.username, self.password),
                timeout=120.0,
                **kwargs,
            )
        except httpx.HTTPError as exc:
            raise APIError(f"Digital Twin API unavailable: {exc}") from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise APIError(f"Digital Twin {response.status_code}: {detail}")
        return response.json() if response.content else None

    def get(self, path: str) -> Any:
        return self._request("GET", path)

    def put(self, path: str, payload: dict[str, Any]) -> Any:
        return self._request("PUT", path, json=payload)

    def active_run(self) -> dict[str, Any]:
        return dict(self.get("/api/active-run"))

    def active_projection(self) -> dict[str, Any]:
        return dict(self.get("/api/executive-projection"))

    def projection(self, run_id: str) -> dict[str, Any]:
        return dict(self.get(f"/api/runs/{run_id}/executive-projection"))

    def activate(self, run_id: str) -> dict[str, Any]:
        return dict(self.put("/api/active-run", {"run_id": run_id}))

    def runs(self) -> list[dict[str, Any]]:
        return list(self.get("/api/runs"))
