from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote_plus

from lpr_cpe_demo.config import Settings
from lpr_cpe_demo.domain import ApprovalDecisionInput, ApprovalStatus
from lpr_cpe_demo.workflow.service import WorkflowService


def build_settings() -> Settings:
    user = quote_plus(os.getenv("POSTGRES_USER", "lpr"))
    password = quote_plus(os.getenv("POSTGRES_PASSWORD", "lpr_demo_change_me"))
    database = quote_plus(os.getenv("POSTGRES_DB", "lpr_cpe_demo"))
    host = os.getenv("POSTGRES_HOST", "postgres")
    read_model_dsn = f"postgresql+psycopg://{user}:{password}@{host}:5432/{database}"
    checkpoint_dsn = f"postgresql://{user}:{password}@{host}:5432/{database}"
    effect_path = Path("/tmp/lpr-cpe-postgres-resume-effects.db")
    effect_path.unlink(missing_ok=True)
    return Settings(
        _env_file=None,
        app_environment="test",
        database_url=read_model_dsn,
        langgraph_postgres_dsn=checkpoint_dsn,
        mcp_use_network=False,
        mcp_effect_db=str(effect_path),
        use_langgraph=True,
        workflow_engine="langgraph",
        langgraph_fallback_allowed=False,
        model_provider="fake",
        mcp_approval_signing_secret="postgres-resume-smoke-secret",
    )


def main() -> int:
    settings = build_settings()

    first = WorkflowService(settings=settings)
    try:
        paused = first.start_scenario("hfc_remote_success")
        approvals = first.list_approvals(
            status=ApprovalStatus.PENDING,
            incident_id=paused.incident_id,
        )
        if len(approvals) != 1:
            raise RuntimeError("Expected one approval before process restart")
        incident_id = paused.incident_id
        approval_id = approvals[0].approval_id
        role = approvals[0].requested_role
    finally:
        first.close()

    second = WorkflowService(settings=settings)
    try:
        recovered = second.get_incident(incident_id)
        if recovered.pending_approval_id != approval_id:
            raise RuntimeError("Read model did not retain the pending approval")
        completed = second.decide_approval(
            approval_id,
            ApprovalDecisionInput(
                decision="approve",
                actor="postgres.resume.smoke",
                role=role,
                reason="Approved after recreating the workflow service.",
            ),
        )
        if completed.status.value != "closed":
            raise RuntimeError(
                f"Expected closed incident after resume, got {completed.status.value}/{completed.stage.value}"
            )
        if len(completed.action_history) != 1:
            raise RuntimeError("Restart/resume produced a duplicate or missing action history record")
        if len({event.event_id for event in completed.timeline}) != len(completed.timeline):
            raise RuntimeError("Restart/resume produced duplicate timeline event identifiers")
    finally:
        second.close()

    print("PostgreSQL checkpoint restart/resume check: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
