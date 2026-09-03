from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from lpr_cpe_demo import __version__
from lpr_cpe_demo.assurance import InstallHandoffRequest
from lpr_cpe_demo.caddi import caddi_contract
from lpr_cpe_demo.config import Settings, get_settings
from lpr_cpe_demo.domain import ApprovalDecisionInput, ApprovalStatus, FaultDomain
from lpr_cpe_demo.measurement import measurement_contract
from lpr_cpe_demo.quarantine import (
    QuarantineConflictError,
    QuarantineObservationRequest,
    QuarantineStatus,
)
from lpr_cpe_demo.workflow.service import (
    ApprovalConflict,
    ApprovalNotFound,
    AuthorizationError,
    IncidentNotFound,
    WorkflowService,
)

LOGGER = logging.getLogger(__name__)


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


class RunDueQuarantineBody(BaseModel):
    limit: int = Field(default=20, ge=1, le=200)


class TrustedMutationPrincipal(BaseModel):
    actor: str
    source: str


def create_app(
    *,
    settings: Settings | None = None,
    service: WorkflowService | None = None,
) -> FastAPI:
    configured_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.workflow_service = service or WorkflowService(settings=configured_settings)
        scheduler_task: asyncio.Task[None] | None = None

        async def quarantine_scheduler() -> None:
            while True:
                try:
                    await asyncio.to_thread(
                        app.state.workflow_service.run_due_quarantine_jobs,
                        worker_id="api-quarantine-scheduler",
                        limit=20,
                    )
                except Exception:
                    # A transient scheduler failure must not stop the API process.
                    # Durable leases make the same work eligible after expiry.
                    LOGGER.exception("Post-action quarantine scheduler iteration failed")
                await asyncio.sleep(
                    configured_settings.post_action_quarantine_worker_interval_seconds
                )

        if (
            configured_settings.post_action_quarantine_enabled
            and configured_settings.post_action_quarantine_scheduler_enabled
        ):
            scheduler_task = asyncio.create_task(quarantine_scheduler())
        try:
            yield
        finally:
            if scheduler_task is not None:
                scheduler_task.cancel()
                try:
                    await scheduler_task
                except asyncio.CancelledError:
                    LOGGER.debug("Post-action quarantine scheduler stopped")
            app.state.workflow_service.close()

    app = FastAPI(
        title="LPR CPE Service Assurance Demo API",
        version=__version__,
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

    def require_trusted_mutation_principal(
        request: Request,
    ) -> TrustedMutationPrincipal:
        configured_token = configured_settings.workflow_internal_token.strip()
        if not configured_token:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="WORKFLOW_INTERNAL_TOKEN_NOT_CONFIGURED",
            )
        supplied_token = request.headers.get("X-LPR-Internal-Token", "")
        if not supplied_token or not secrets.compare_digest(
            supplied_token,
            configured_token,
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="TRUSTED_MUTATION_AUTH_REQUIRED",
            )
        return TrustedMutationPrincipal(
            actor=configured_settings.workflow_internal_actor,
            source=configured_settings.workflow_internal_source,
        )

    @app.get("/api/integrations/caddi", tags=["integrations"])
    @app.get("/api/integrations/caddi", tags=["integrations"], deprecated=True)
    @app.get("/api/integrations/cadi", tags=["integrations"], deprecated=True)
    def caddi_integration() -> dict[str, Any]:
        return caddi_contract()

    @app.get("/health", tags=["system"])
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "mode": configured_settings.application_mode,
            "version": __version__,
            "measurement_schema": "1.0",
            "unified_assurance": "p2",
            "post_action_quarantine": configured_settings.post_action_quarantine_enabled,
        }

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

    @app.post("/api/assurance/install-handoffs", tags=["assurance"])
    def create_install_handoff(
        body: InstallHandoffRequest,
        _principal: TrustedMutationPrincipal = Depends(
            require_trusted_mutation_principal
        ),
        workflow: WorkflowService = Depends(get_service),
    ) -> dict[str, Any]:
        try:
            return workflow.create_install_handoff(body).model_dump(mode="json")
        except ApprovalConflict as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    @app.get("/api/assurance/episodes", tags=["assurance"])
    def list_assurance_episodes(
        limit: int = Query(default=200, ge=1, le=5000),
        workflow: WorkflowService = Depends(get_service),
    ) -> list[dict[str, Any]]:
        return [
            episode.model_dump(mode="json")
            for episode in workflow.list_assurance_episodes(limit=limit)
        ]

    @app.get("/api/assurance/episodes/{episode_id}", tags=["assurance"])
    def get_assurance_episode(
        episode_id: str,
        workflow: WorkflowService = Depends(get_service),
    ) -> dict[str, Any]:
        try:
            return workflow.get_assurance_episode(episode_id)
        except IncidentNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=episode_id) from exc

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

    @app.get("/api/assurance/quarantine-policy", tags=["assurance"])
    def quarantine_policy(
        workflow: WorkflowService = Depends(get_service),
    ) -> dict[str, Any]:
        return workflow.quarantine_policy().model_dump(mode="json")

    @app.get("/api/assurance/quarantines", tags=["assurance"])
    def list_quarantines(
        quarantine_status: QuarantineStatus | None = Query(
            default=None,
            alias="status",
        ),
        incident_id: str | None = None,
        limit: int = Query(default=200, ge=1, le=5000),
        workflow: WorkflowService = Depends(get_service),
    ) -> list[dict[str, Any]]:
        return [
            item.model_dump(mode="json")
            for item in workflow.list_quarantines(
                status=quarantine_status,
                incident_id=incident_id,
                limit=limit,
            )
        ]

    @app.get(
        "/api/assurance/quarantines/{quarantine_id}",
        tags=["assurance"],
    )
    def get_quarantine(
        quarantine_id: str,
        workflow: WorkflowService = Depends(get_service),
    ) -> dict[str, Any]:
        try:
            return workflow.get_quarantine(quarantine_id)
        except IncidentNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=quarantine_id,
            ) from exc

    @app.post(
        "/api/assurance/quarantines/{quarantine_id}/observations",
        tags=["assurance"],
    )
    def record_quarantine_observation(
        quarantine_id: str,
        body: QuarantineObservationRequest,
        principal: TrustedMutationPrincipal = Depends(
            require_trusted_mutation_principal
        ),
        workflow: WorkflowService = Depends(get_service),
    ) -> dict[str, Any]:
        try:
            return workflow.record_quarantine_observation(
                quarantine_id,
                body,
                actor=principal.actor,
                source=f"{principal.source}:quarantine-observation",
            )
        except IncidentNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=quarantine_id,
            ) from exc
        except QuarantineConflictError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

    @app.post("/api/assurance/quarantine-jobs/run-due", tags=["assurance"])
    def run_due_quarantine_jobs(
        body: RunDueQuarantineBody,
        principal: TrustedMutationPrincipal = Depends(
            require_trusted_mutation_principal
        ),
        workflow: WorkflowService = Depends(get_service),
    ) -> dict[str, Any]:
        results = workflow.run_due_quarantine_jobs(
            worker_id=f"{principal.actor}:quarantine-scheduler",
            limit=body.limit,
        )
        return {"processed": len(results), "results": results}

    @app.get("/api/measurement-contract", tags=["monitoring"])
    def shared_measurement_contract() -> dict[str, Any]:
        return measurement_contract()

    @app.get("/api/operations-projection", tags=["monitoring"])
    @app.get("/api/measurement-projection", tags=["monitoring"])
    def operations_projection(
        workflow: WorkflowService = Depends(get_service),
    ) -> dict[str, Any]:
        return workflow.measurement_projection()

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
