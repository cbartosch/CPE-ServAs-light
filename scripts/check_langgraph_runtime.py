from __future__ import annotations

import tempfile
from pathlib import Path

from lpr_cpe_demo.config import Settings
from lpr_cpe_demo.domain import ApprovalDecisionInput, ApprovalStatus
from lpr_cpe_demo.workflow.service import WorkflowService


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="lpr-cpe-langgraph-") as temp_dir:
        root = Path(temp_dir)
        settings = Settings(
            _env_file=None,
            app_environment="test",
            database_url=f"sqlite+pysqlite:///{root / 'langgraph.db'}",
            langgraph_postgres_dsn="",
            mcp_use_network=False,
            mcp_effect_db=str(root / "effects.db"),
            use_langgraph=True,
            workflow_engine="langgraph",
            langgraph_fallback_allowed=False,
            model_provider="fake",
            mcp_approval_signing_secret="langgraph-runtime-smoke-secret",
        )
        service = WorkflowService(settings=settings)
        try:
            state = service.start_scenario("hfc_remote_success")
            if type(service.engine).__name__ != "LangGraphWorkflowEngine":
                raise RuntimeError("LangGraph engine was not activated")
            approvals = service.list_approvals(
                status=ApprovalStatus.PENDING,
                incident_id=state.incident_id,
            )
            if len(approvals) != 1:
                raise RuntimeError("Expected exactly one pending remote-action approval")
            approval = approvals[0]
            state = service.decide_approval(
                approval.approval_id,
                ApprovalDecisionInput(
                    decision="approve",
                    actor="langgraph.smoke",
                    role=approval.requested_role,
                    reason="Approved by LangGraph runtime smoke test.",
                ),
            )
            if state.status.value != "closed":
                raise RuntimeError(f"Expected closed incident, got {state.status.value}/{state.stage.value}")
            if state.remote_attempts != 1 or state.field_visits != 0:
                raise RuntimeError("Unexpected action counters in LangGraph runtime smoke test")
        finally:
            service.close()
    print("LangGraph interrupt/resume runtime check: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
