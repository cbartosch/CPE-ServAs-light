from __future__ import annotations

from fastapi.testclient import TestClient

from lpr_cpe_demo.api.main import create_app
from lpr_cpe_demo.domain import ApprovalStatus
from lpr_cpe_demo.workflow.service import WorkflowService


def test_api_scenario_to_human_decision(service: WorkflowService) -> None:
    app = create_app(settings=service.settings, service=service)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        scenarios = client.get("/api/scenarios").json()
        assert any(item["name"] == "rca_disagreement_gate" for item in scenarios)

        response = client.post(
            "/api/scenarios/rca_disagreement_gate/start",
            json={"run_until_pause": True},
        )
        assert response.status_code == 200
        incident = response.json()
        assert incident["stage"] == "waiting_approval"
        assert incident["gate_reason"] == "domain_disagreement"

        approvals = client.get(
            "/api/approvals",
            params={"status": ApprovalStatus.PENDING.value, "incident_id": incident["incident_id"]},
        ).json()
        assert len(approvals) == 1
        approval = approvals[0]

        decision = client.post(
            f"/api/approvals/{approval['approval_id']}/decision",
            json={
                "decision": "approve",
                "actor": "api.tester",
                "role": "l2_sme",
                "reason": "Approved deterministic responsibility domain.",
                "selected_domain": "drop",
            },
        )
        assert decision.status_code == 200
        assert decision.json()["stage"] == "waiting_approval"


def test_api_rejects_wrong_approval_role(service: WorkflowService) -> None:
    app = create_app(settings=service.settings, service=service)
    with TestClient(app) as client:
        incident = client.post(
            "/api/scenarios/hfc_remote_success/start",
            json={"run_until_pause": True},
        ).json()
        approval = client.get(
            "/api/approvals",
            params={"status": "pending", "incident_id": incident["incident_id"]},
        ).json()[0]
        response = client.post(
            f"/api/approvals/{approval['approval_id']}/decision",
            json={
                "decision": "approve",
                "actor": "unauthorized.user",
                "role": "viewer",
                "reason": "",
            },
        )
        assert response.status_code == 403
