"""End-to-end runtime smoke for P1 episodes and P2 quarantine controls."""

from __future__ import annotations

import argparse
import json
import urllib.request
from datetime import UTC, datetime, timedelta


def _request(base: str, method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{base.rstrip('/')}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base = args.workflow_url
    health = _request(base, "GET", "/health")
    policy = _request(base, "GET", "/api/assurance/quarantine-policy")
    if health.get("unified_assurance") != "p2" or not policy.get("enabled"):
        raise SystemExit("P2 is not enabled in the workflow API")

    state = _request(
        base,
        "POST",
        "/api/scenarios/hfc_remote_success/start",
        {"run_until_pause": True},
    )
    for _ in range(20):
        if state.get("stage") == "post_action_quarantine":
            break
        approvals = _request(
            base,
            "GET",
            f"/api/approvals?status=pending&incident_id={state['incident_id']}",
        )
        if approvals:
            approval = approvals[0]
            state = _request(
                base,
                "POST",
                f"/api/approvals/{approval['approval_id']}/decision",
                {
                    "decision": "approve",
                    "actor": "runtime.smoke",
                    "role": approval["requested_role"],
                    "reason": "P2 runtime smoke approval",
                },
            )
        else:
            state = _request(
                base,
                "POST",
                f"/api/incidents/{state['incident_id']}/run",
                {"one_step": False},
            )
    else:
        raise SystemExit("scenario did not enter post-action quarantine")

    quarantine_id = state["active_quarantine_id"]
    detail = _request(
        base,
        "GET",
        f"/api/assurance/quarantines/{quarantine_id}",
    )
    release_at = datetime.fromisoformat(
        detail["quarantine"]["minimum_release_at"].replace("Z", "+00:00")
    )
    first_at = datetime.now(UTC) + timedelta(seconds=1)
    _request(
        base,
        "POST",
        f"/api/assurance/quarantines/{quarantine_id}/observations",
        {
            "health": "healthy",
            "observed_at": first_at.isoformat(),
            "source": "runtime_smoke",
            "actor": "runtime.smoke",
            "idempotency_key": f"smoke-1-{quarantine_id}",
            "metrics": {"service_test": "pass"},
        },
    )
    final = _request(
        base,
        "POST",
        f"/api/assurance/quarantines/{quarantine_id}/observations",
        {
            "health": "healthy",
            "observed_at": (release_at + timedelta(seconds=1)).isoformat(),
            "source": "runtime_smoke",
            "actor": "runtime.smoke",
            "idempotency_key": f"smoke-2-{quarantine_id}",
            "metrics": {"service_test": "pass"},
        },
    )
    if final["incident"]["status"] != "closed":
        raise SystemExit("P2 quarantine did not release the incident")
    print(
        json.dumps(
            {
                "unified_assurance": "PASS",
                "post_action_quarantine": "PASS",
                "incident_id": state["incident_id"],
                "quarantine_id": quarantine_id,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
