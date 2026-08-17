from __future__ import annotations

import os
import sys
from typing import Any

import httpx


API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")
TIMEOUT = float(os.getenv("SMOKE_TIMEOUT_SECONDS", "20"))


def _request(client: httpx.Client, method: str, path: str, **kwargs: Any) -> Any:
    response = client.request(method, f"{API_URL}{path}", **kwargs)
    response.raise_for_status()
    return response.json()


def _pending_approval(client: httpx.Client, incident_id: str) -> dict[str, Any]:
    approvals = _request(
        client,
        "GET",
        "/api/approvals",
        params={"status": "pending", "incident_id": incident_id},
    )
    if len(approvals) != 1:
        raise AssertionError(f"Expected one pending approval for {incident_id}, got {len(approvals)}")
    return dict(approvals[0])


def _approve(
    client: httpx.Client,
    incident_id: str,
    *,
    actor: str,
    reason: str,
) -> dict[str, Any]:
    approval = _pending_approval(client, incident_id)
    return _request(
        client,
        "POST",
        f"/api/approvals/{approval['approval_id']}/decision",
        json={
            "decision": "approve",
            "actor": actor,
            "role": "operations_supervisor",
            "reason": reason,
        },
    )


def _remote_success(client: httpx.Client) -> tuple[str, str]:
    incident = _request(
        client,
        "POST",
        "/api/scenarios/hfc_remote_success/start",
        json={"run_until_pause": True},
    )
    incident_id = incident["incident_id"]
    if incident.get("stage") != "waiting_approval":
        raise AssertionError(f"Expected waiting_approval, got {incident.get('stage')}")
    approval = _pending_approval(client, incident_id)
    completed = _approve(
        client,
        incident_id,
        actor="docker.smoke.remote",
        reason="Approve the reversible remote action in the live HTTP smoke test.",
    )
    if completed.get("status") != "closed":
        raise AssertionError(f"Expected closed incident, got {completed.get('status')}")
    if completed.get("verification_passed") is not True:
        raise AssertionError("Expected verification_passed=true")
    if len(completed.get("action_history", [])) != 1:
        raise AssertionError("Expected exactly one simulated remote action")
    return incident_id, str(approval["approval_id"])


def _failed_plant_then_mr_update(client: httpx.Client) -> str:
    incident = _request(
        client,
        "POST",
        "/api/scenarios/hfc_failed_plant_action_rerca/start",
        json={"run_until_pause": True},
    )
    incident_id = incident["incident_id"]
    after_first = _approve(
        client,
        incident_id,
        actor="docker.smoke.plant.1",
        reason="Approve the first Dirty Boots attempt to exercise failed verification and re-RCA.",
    )
    if after_first.get("stage") != "waiting_approval":
        raise AssertionError(
            "Expected a second approval after failed plant action and re-RCA, "
            f"got {after_first.get('stage')}/{after_first.get('status')}"
        )
    completed = _approve(
        client,
        incident_id,
        actor="docker.smoke.plant.2",
        reason="Approve the updated MR after new evidence and cross-domain re-RCA.",
    )
    if completed.get("status") != "closed":
        raise AssertionError(f"Expected plant scenario to close, got {completed.get('status')}")
    if completed.get("mr_attempts") != 2:
        raise AssertionError(f"Expected two MR attempts, got {completed.get('mr_attempts')}")
    mr_records = list(completed.get("mr_records", []))
    if len(mr_records) != 2 or len({item.get("mr_id") for item in mr_records}) != 1:
        raise AssertionError("Expected two revisions of one jTrack MR, not duplicate MR identifiers")
    if [item.get("outcome") for item in mr_records] != ["failed", "succeeded"]:
        raise AssertionError(f"Unexpected MR outcomes: {mr_records}")
    timeline = list(completed.get("timeline", []))
    if not any(item.get("event_type") == "return_to_rca" for item in timeline):
        raise AssertionError("Failed plant action did not record the mandatory return to RCA")
    return incident_id


def main() -> int:
    with httpx.Client(timeout=TIMEOUT) as client:
        _request(client, "GET", "/health")
        _request(client, "POST", "/api/reset", json={"confirm": "RESET DEMO"})

        remote_incident, approval_id = _remote_success(client)
        plant_incident = _failed_plant_then_mr_update(client)

        system = _request(client, "GET", "/api/system/status")
        if system.get("mcp_status") != "ok":
            raise AssertionError(f"Expected MCP status ok, got {system.get('mcp_status')}")

        print("API workflow smoke: PASS")
        print(
            f"remote_incident={remote_incident} approval={approval_id} "
            f"plant_incident={plant_incident} engine={system.get('workflow_engine_active')}"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"API workflow smoke: FAIL - {exc}", file=sys.stderr)
        raise
