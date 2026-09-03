"""End-to-end runtime smoke for protected P1/P2 assurance mutations.

The default smoke deliberately sends an immediate degraded observation. That
transition is valid at once and therefore proves the quarantine/reopen control
without defeating or waiting through the configured stability duration.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from datetime import UTC, datetime


def _request(
    base: str,
    method: str,
    path: str,
    body: dict | None = None,
    *,
    internal_token: str | None = None,
):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if internal_token:
        headers["X-LPR-Internal-Token"] = internal_token
    request = urllib.request.Request(
        f"{base.rstrip('/')}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--internal-token",
        default=os.getenv("WORKFLOW_INTERNAL_TOKEN", ""),
        help="Protected workflow mutation token; defaults to WORKFLOW_INTERNAL_TOKEN.",
    )
    args = parser.parse_args()
    if not args.internal_token:
        raise SystemExit(
            "WORKFLOW_INTERNAL_TOKEN or --internal-token is required for P2 smoke"
        )

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
    path = f"/api/assurance/quarantines/{quarantine_id}/observations"
    try:
        _request(
            base,
            "POST",
            path,
            {"health": "degraded", "idempotency_key": "unauthenticated-smoke"},
        )
    except urllib.error.HTTPError as exc:
        if exc.code != 401:
            raise
    else:
        raise SystemExit("protected P2 mutation unexpectedly accepted no token")

    result = _request(
        base,
        "POST",
        path,
        {
            "health": "degraded",
            "observed_at": datetime.now(UTC).isoformat(),
            "idempotency_key": f"runtime-reopen-{quarantine_id}",
            "metrics": {"service_test": "degraded-smoke"},
        },
        internal_token=args.internal_token,
    )
    observation = result["observation"]
    incident = result["incident"]
    if observation["transition"] != "reopen":
        raise SystemExit("P2 smoke did not reopen on degraded health")
    if incident["incident_id"] != state["incident_id"]:
        raise SystemExit("P2 smoke changed the canonical incident identity")
    if incident["stage"] != "failure_review" or incident["status"] != "open":
        raise SystemExit("P2 smoke did not return the incident to failure review")
    if observation["actor"] in {"runtime.smoke", "forged"}:
        raise SystemExit("P2 mutation actor was not derived from trusted identity")

    print(
        json.dumps(
            {
                "authenticated_mutation": "PASS",
                "canonical_incident_reopen": "PASS",
                "incident_id": state["incident_id"],
                "quarantine_id": quarantine_id,
                "server_received_at": observation["received_at"],
                "unified_assurance": "PASS",
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
