#!/usr/bin/env python3
"""Verify the running UI container is wired to both application APIs."""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

from lpr_cpe_demo import __version__


class SmokeFailure(RuntimeError):
    pass


def _request_json(
    base_url: str,
    path: str,
    *,
    username: str | None = None,
    password: str | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
) -> tuple[int, Any]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        headers=dict(headers or {}),
    )
    if username is not None and password is not None:
        token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
        request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            payload = json.loads(body) if body else None
        except json.JSONDecodeError:
            payload = body.decode("utf-8", errors="replace")
        return exc.code, payload
    except OSError as exc:
        raise SmokeFailure(f"request failed for {path}: {exc}") from exc


def _require_status(label: str, status: int, expected: int = 200) -> None:
    if status != expected:
        raise SmokeFailure(f"{label} returned HTTP {status}; expected {expected}")


def main() -> int:
    api_url = os.getenv("API_URL", "http://api:8000").rstrip("/")
    dt_api_url = os.getenv("DT_API_URL", "http://digital-twin-api:8001").rstrip("/")
    expected_release = os.getenv("LPR_APP_RELEASE", __version__).strip()

    if expected_release != __version__:
        raise SmokeFailure(
            f"stale application image: expected {expected_release}, loaded {__version__}"
        )
    if api_url in {"http://localhost:8000", "http://127.0.0.1:8000"}:
        raise SmokeFailure("UI container API_URL points to itself instead of the api service")
    if dt_api_url in {"http://localhost:8001", "http://127.0.0.1:8001"}:
        raise SmokeFailure(
            "UI container DT_API_URL points to itself instead of digital-twin-api"
        )

    status, health = _request_json(api_url, "/health")
    _require_status("workflow API health", status)
    if not isinstance(health, dict) or health.get("status") != "ok":
        raise SmokeFailure(f"unexpected workflow API health payload: {health!r}")
    if health.get("version") != expected_release:
        raise SmokeFailure(
            "stale workflow API image: "
            f"expected {expected_release}, loaded {health.get('version')}"
        )

    status, scenarios = _request_json(
        api_url,
        "/api/scenarios",
        headers={
            "X-Demo-User": "runtime.smoke",
            "X-Demo-Role": "operations_supervisor",
        },
    )
    _require_status("workflow scenario list", status)
    if not isinstance(scenarios, list) or not scenarios:
        raise SmokeFailure("workflow API returned no scenarios")

    status, dt_health = _request_json(dt_api_url, "/health")
    _require_status("Digital Twin health", status)
    if not isinstance(dt_health, dict) or dt_health.get("status") != "ok":
        raise SmokeFailure(f"unexpected Digital Twin health payload: {dt_health!r}")

    username = os.getenv("DT_USER", "demo")
    password = os.getenv("DT_PASSWORD", "CHANGE_ME")
    status, active = _request_json(
        dt_api_url,
        "/api/active-run",
        username=username,
        password=password,
    )
    if status == 404:
        print("Digital Twin: no active run; projection check skipped")
    else:
        _require_status("Digital Twin active run", status)
        if not isinstance(active, dict) or not active.get("run_id"):
            raise SmokeFailure(f"unexpected active-run payload: {active!r}")
        status, projection = _request_json(
            dt_api_url,
            "/api/executive-projection",
            username=username,
            password=password,
            timeout=60.0,
        )
        _require_status("Digital Twin executive projection", status)
        if not isinstance(projection, dict) or projection.get("run_id") != active["run_id"]:
            raise SmokeFailure("executive projection does not match the active run")

    print(f"Application release: {__version__}")
    print(f"Workflow API: {api_url}")
    print(f"Digital Twin API: {dt_api_url}")
    print("Runtime connectivity smoke: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SmokeFailure as exc:
        print(f"Runtime connectivity smoke: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
