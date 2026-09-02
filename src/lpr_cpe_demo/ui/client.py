from __future__ import annotations

from typing import Any

DEFAULT_REQUEST_TIMEOUT_SECONDS = 30.0
DEFAULT_SCENARIO_TIMEOUT_SECONDS = 240.0


class APIError(RuntimeError):
    pass


def _timeout_from_env(name: str, default: float) -> float:
    import os

    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


class DemoAPI:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        request_timeout: float | None = None,
        scenario_timeout: float | None = None,
    ) -> None:
        import os

        self.base_url = (base_url or os.getenv("API_URL", "http://localhost:8000")).rstrip(
            "/"
        )
        self.request_timeout = request_timeout or _timeout_from_env(
            "API_TIMEOUT_SECONDS",
            DEFAULT_REQUEST_TIMEOUT_SECONDS,
        )
        self.scenario_timeout = scenario_timeout or _timeout_from_env(
            "API_SCENARIO_TIMEOUT_SECONDS",
            DEFAULT_SCENARIO_TIMEOUT_SECONDS,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        user: str = "demo.operator",
        role: str = "operations_supervisor",
        timeout: float | None = None,
        **kwargs: Any,
    ) -> Any:
        import httpx

        headers = dict(kwargs.pop("headers", {}))
        headers.update({"X-Demo-User": user, "X-Demo-Role": role})
        effective_timeout = timeout or self.request_timeout
        try:
            response = httpx.request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                timeout=effective_timeout,
                **kwargs,
            )
        except httpx.TimeoutException as exc:
            raise APIError(
                f"API request timed out after {effective_timeout:g} seconds: "
                f"{method.upper()} {path}"
            ) from exc
        except httpx.HTTPError as exc:
            raise APIError(f"API unavailable: {exc}") from exc
        if response.status_code >= 400:
            try:
                payload = response.json()
                detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
            except ValueError:
                detail = response.text
            raise APIError(f"{response.status_code}: {detail}")
        if not response.content:
            return None
        return response.json()

    def get(self, path: str) -> Any:
        return self._request("GET", path)

    def post(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
        **identity: str,
    ) -> Any:
        return self._request(
            "POST",
            path,
            json=payload,
            timeout=timeout,
            **identity,
        )

    def scenarios(self) -> list[dict[str, Any]]:
        return list(self.get("/api/scenarios"))

    def start(self, scenario_name: str) -> dict[str, Any]:
        return dict(
            self.post(
                f"/api/scenarios/{scenario_name}/start",
                {"run_until_pause": True},
                timeout=self.scenario_timeout,
            )
        )

    def incidents(self) -> list[dict[str, Any]]:
        return list(self.get("/api/incidents"))

    def assurance_episodes(self) -> list[dict[str, Any]]:
        return list(self.get("/api/assurance/episodes"))

    def quarantines(self, status: str | None = None) -> list[dict[str, Any]]:
        suffix = f"?status={status}" if status else ""
        return list(self.get(f"/api/assurance/quarantines{suffix}"))

    def quarantine_policy(self) -> dict[str, Any]:
        return dict(self.get("/api/assurance/quarantine-policy"))

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
        import os

        self.base_url = (
            base_url or os.getenv("DT_API_URL", "http://localhost:8001")
        ).rstrip("/")
        self.username = username or os.getenv("DT_USER", "demo")
        self.password = password or os.getenv("DT_PASSWORD", "CHANGE_ME")

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        import httpx

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
                payload = response.json()
                detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
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

    def dispatch_cost_projection(self, run_id: str | None = None) -> dict[str, Any]:
        path = (
            f"/api/runs/{run_id}/dispatch-cost-projection"
            if run_id
            else "/api/dispatch-cost-projection"
        )
        return dict(self.get(path))

    def dispatch_cost_contract(self) -> dict[str, Any]:
        return dict(self.get("/api/dispatch-cost-contract"))

    def activate(self, run_id: str) -> dict[str, Any]:
        return dict(self.put("/api/active-run", {"run_id": run_id}))

    def runs(self) -> list[dict[str, Any]]:
        return list(self.get("/api/runs"))
