from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from lpr_cpe_demo.config import Settings, get_settings
from lpr_cpe_demo.domain import ApprovalDecisionInput, ApprovalStatus, FaultDomain
from lpr_cpe_demo.workflow.service import (
    ApprovalConflict,
    ApprovalNotFound,
    AuthorizationError,
    IncidentNotFound,
    WorkflowService,
)


class StartScenarioBody(BaseModel):
    run_until_pause: bool = True


class RunIncidentBody(BaseModel):
    one_step: bool = False


class ApprovalDecisionBody(BaseModel):
    decision: str = Field(pattern="^(approve|reject|request_more|override)$")
    actor: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=80)
    reason: str = Field(default="", max_length=1000)
    selected_option: str | None = None
    selected_domain: FaultDomain | None = None


class ResetBody(BaseModel):
    confirm: str


def create_app(
    *,
    settings: Settings | None = None,
    service: WorkflowService | None = None,
) -> FastAPI:
    configured_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.workflow_service = service or WorkflowService(settings=configured_settings)
        try:
            yield
        finally:
            app.state.workflow_service.close()

    app = FastAPI(
        title="LPR CPE Service Assurance Demo API",
        version="1.2.0",
        description=(
            "Simulation-only API for deterministic and LLM-assisted CPE incident resolution, "
            "human approvals, Clean/Dirty Boots handover, and jTrack MR workflow."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    def get_service(request: Request) -> WorkflowService:
        return request.app.state.workflow_service

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": configured_settings.application_mode}

    @app.get("/ready", tags=["system"])
    def ready(workflow: WorkflowService = Depends(get_service)) -> dict[str, Any]:
        return {"status": "ready", "system": workflow.system_status()}

    @app.get("/api/scenarios", tags=["scenarios"])
    def list_scenarios(workflow: WorkflowService = Depends(get_service)) -> list[dict[str, Any]]:
        return workflow.list_scenarios()

    @app.post("/api/scenarios/{scenario_name}/start", tags=["scenarios"])
    def start_scenario(
        scenario_name: str,
        body: StartScenarioBody,
        workflow: WorkflowService = Depends(get_service),
    ) -> dict[str, Any]:
        try:
            state = workflow.start_scenario(scenario_name, run_until_pause=body.run_until_pause)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return state.model_dump(mode="json")

    @app.get("/api/incidents", tags=["incidents"])
    def list_incidents(workflow: WorkflowService = Depends(get_service)) -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in workflow.list_incidents()]

    @app.get("/api/incidents/{incident_id}", tags=["incidents"])
    def get_incident(
        incident_id: str,
        workflow: WorkflowService = Depends(get_service),
    ) -> dict[str, Any]:
        try:
            return workflow.get_incident(incident_id).model_dump(mode="json")
        except IncidentNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=incident_id) from exc

    @app.get("/api/incidents/{incident_id}/timeline", tags=["incidents"])
    def get_timeline(
        incident_id: str,
        workflow: WorkflowService = Depends(get_service),
    ) -> list[dict[str, Any]]:
        try:
            incident = workflow.get_incident(incident_id)
        except IncidentNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=incident_id) from exc
        return [item.model_dump(mode="json") for item in incident.timeline]

    @app.post("/api/incidents/{incident_id}/run", tags=["incidents"])
    def run_incident(
        incident_id: str,
        body: RunIncidentBody,
        workflow: WorkflowService = Depends(get_service),
    ) -> dict[str, Any]:
        try:
            state = workflow.run_incident(incident_id, one_step=body.one_step)
        except IncidentNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=incident_id) from exc
        return state.model_dump(mode="json")

    @app.get("/api/approvals", tags=["approvals"])
    def list_approvals(
        approval_status: ApprovalStatus | None = Query(default=None, alias="status"),
        incident_id: str | None = None,
        workflow: WorkflowService = Depends(get_service),
    ) -> list[dict[str, Any]]:
        return [
            item.model_dump(mode="json")
            for item in workflow.list_approvals(status=approval_status, incident_id=incident_id)
        ]

    @app.post("/api/approvals/{approval_id}/decision", tags=["approvals"])
    def decide_approval(
        approval_id: str,
        body: ApprovalDecisionBody,
        workflow: WorkflowService = Depends(get_service),
    ) -> dict[str, Any]:
        try:
            decision = ApprovalDecisionInput(
                decision=body.decision,
                actor=body.actor,
                role=body.role,
                reason=body.reason,
                selected_option=body.selected_option,
                selected_domain=body.selected_domain,
            )
            state = workflow.decide_approval(approval_id, decision)
        except ApprovalNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=approval_id) from exc
        except AuthorizationError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        except ApprovalConflict as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        return state.model_dump(mode="json")

    @app.get("/api/dashboard", tags=["monitoring"])
    def dashboard(workflow: WorkflowService = Depends(get_service)) -> dict[str, Any]:
        return workflow.dashboard()

    @app.get("/api/system/status", tags=["system"])
    def system_status(workflow: WorkflowService = Depends(get_service)) -> dict[str, Any]:
        return workflow.system_status()

    @app.post("/api/reset", tags=["system"])
    def reset_demo(
        body: ResetBody,
        workflow: WorkflowService = Depends(get_service),
    ) -> dict[str, str]:
        if body.confirm != "RESET DEMO":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Set confirm to 'RESET DEMO'.",
            )
        workflow.reset()
        return {"status": "reset"}

    return app


app = create_app()
