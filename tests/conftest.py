from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from lpr_cpe_demo.config import Settings
from lpr_cpe_demo.domain import ApprovalDecisionInput, ApprovalKind, ApprovalStatus, IncidentState
from lpr_cpe_demo.workflow.service import WorkflowService


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        app_environment="test",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'demo.db'}",
        langgraph_postgres_dsn="",
        mcp_use_network=False,
        mcp_effect_db=str(tmp_path / "effects.db"),
        use_langgraph=False,
        workflow_engine="portable",
        model_provider="fake",
        mcp_approval_signing_secret="test-signing-secret",
        workflow_internal_token="test-workflow-internal-token",
        workflow_internal_actor="test.internal",
        workflow_internal_source="test-client",
        graph_max_steps=40,
        max_remote_attempts=2,
        max_field_visits=3,
        max_mr_attempts=2,
    )


@pytest.fixture()
def service(settings: Settings) -> Iterator[WorkflowService]:
    instance = WorkflowService(settings=settings)
    instance.reset()
    try:
        yield instance
    finally:
        instance.close()


def approve_until_terminal(service: WorkflowService, state: IncidentState) -> IncidentState:
    for _ in range(30):
        if state.status.value in {"closed", "escalated", "quarantined"}:
            return state
        approvals = service.list_approvals(
            status=ApprovalStatus.PENDING,
            incident_id=state.incident_id,
        )
        if approvals:
            approval = approvals[0]
            selected_domain = (
                state.rca_domain_deterministic
                if approval.kind == ApprovalKind.RCA_REVIEW
                else None
            )
            state = service.decide_approval(
                approval.approval_id,
                ApprovalDecisionInput(
                    decision="approve",
                    actor="test.operator",
                    role=approval.requested_role,
                    reason="Automated scenario approval",
                    selected_domain=selected_domain,
                ),
            )
        else:
            state = service.run_incident(state.incident_id)
    raise AssertionError("Scenario did not reach a terminal state within 30 decisions")
