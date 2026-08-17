from __future__ import annotations

import tempfile
from pathlib import Path

from lpr_cpe_demo.config import Settings
from lpr_cpe_demo.domain import ApprovalDecisionInput, ApprovalKind, ApprovalStatus
from lpr_cpe_demo.workflow.service import WorkflowService


def run_case(service: WorkflowService, scenario_name: str) -> dict[str, object]:
    state = service.start_scenario(scenario_name)
    for _ in range(40):
        if state.status.value in {"closed", "escalated", "quarantined"}:
            break
        approvals = service.list_approvals(
            status=ApprovalStatus.PENDING,
            incident_id=state.incident_id,
        )
        if approvals:
            approval = approvals[0]
            state = service.decide_approval(
                approval.approval_id,
                ApprovalDecisionInput(
                    decision="approve",
                    actor="scenario.matrix",
                    role=approval.requested_role,
                    reason="Approved by deterministic bundle scenario matrix.",
                    selected_domain=(
                        state.rca_domain_deterministic
                        if approval.kind == ApprovalKind.RCA_REVIEW
                        else None
                    ),
                ),
            )
        else:
            state = service.run_incident(state.incident_id)
    else:
        raise RuntimeError(f"{scenario_name} did not reach a terminal state")
    return {
        "scenario": scenario_name,
        "status": state.status.value,
        "actions": [item.action_type.value for item in state.action_history],
        "remote": state.remote_attempts,
        "field": state.field_visits,
        "mr": state.mr_attempts,
        "cycles": state.diagnostic_cycles,
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="lpr-cpe-matrix-") as temp_dir:
        root = Path(temp_dir)
        settings = Settings(
            _env_file=None,
            app_environment="test",
            database_url=f"sqlite+pysqlite:///{root / 'matrix.db'}",
            langgraph_postgres_dsn="",
            mcp_use_network=False,
            mcp_effect_db=str(root / "effects.db"),
            use_langgraph=False,
            workflow_engine="portable",
            model_provider="fake",
            mcp_approval_signing_secret="scenario-matrix-secret",
        )
        service = WorkflowService(settings=settings)
        try:
            rows = [run_case(service, item["name"]) for item in service.list_scenarios()]
        finally:
            service.close()
    print("Scenario matrix: PASS")
    for row in rows:
        print(
            f"- {row['scenario']}: {row['status']} | actions={row['actions']} | "
            f"remote={row['remote']} field={row['field']} mr={row['mr']} cycles={row['cycles']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
