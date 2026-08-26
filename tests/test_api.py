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


def test_api_exposes_dvsum_caddi_integration_contract(service: WorkflowService) -> None:
    app = create_app(settings=service.settings, service=service)
    with TestClient(app) as client:
        canonical = client.get("/api/integrations/caddi")
        legacy = client.get("/api/integrations/cadi")
        assert canonical.status_code == 200
        assert legacy.status_code == 200
        assert canonical.json() == legacy.json()
        body = canonical.json()
        assert body["integration_status"] == "contract_only"
        assert body["live_connection"] is False
        assert body["product_scope"] == "Call Center and Network Operations"
        assert body["declared_lpr_deployment_scope"] == "Call Center via Genesys"
        assert body["owner_scope"] == "Call Center via Genesys (declared LPR deployment)"
        assert body["layer"] == "DvSum CADDI"
        schema = client.get("/openapi.json").json()
        assert schema["paths"]["/api/integrations/cadi"]["get"]["deprecated"] is True
        assert "deprecated" not in schema["paths"]["/api/integrations/caddi"]["get"]
