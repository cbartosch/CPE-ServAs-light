from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from lpr_cpe_demo.assurance import (
    AssuranceEpisode,
    AssuranceEpisodeEvent,
    AssuranceOrigin,
    EpisodeStatus,
    InstallHandoffRequest,
    InstallHandoffResult,
    episode_id_for_install,
    episode_id_for_repair,
)
from lpr_cpe_demo.config import Settings, get_settings
from lpr_cpe_demo.domain import (
    ApprovalDecisionInput,
    ApprovalKind,
    ApprovalRequest,
    ApprovalStatus,
    CaseStatus,
    IncidentState,
    Severity,
    Stage,
    Technology,
    stable_id,
    utc_now,
)
from lpr_cpe_demo.llm import RCAAssistant, build_rca_assistant
from lpr_cpe_demo.mcp_client import HTTPMCPClient, InProcessMCPClient, MCPClient
from lpr_cpe_demo.mcp_server.store import EffectStore
from lpr_cpe_demo.mcp_server.tools import ToolRegistry
from lpr_cpe_demo.measurement import build_operations_projection
from lpr_cpe_demo.persistence import Repository
from lpr_cpe_demo.quarantine import (
    PostActionQuarantine,
    QuarantineHealth,
    QuarantineObservation,
    QuarantineObservationRequest,
    QuarantinePolicy,
    QuarantineStatus,
    QuarantineTransition,
    evaluate_quarantine_observation,
    observation_id_for,
)
from lpr_cpe_demo.workflow.engine import PortableWorkflowEngine, build_approval_token
from lpr_cpe_demo.workflow.scenarios import ScenarioCatalog


class IncidentNotFound(KeyError):
    pass


class ApprovalNotFound(KeyError):
    pass


class ApprovalConflict(RuntimeError):
    pass


class AuthorizationError(PermissionError):
    pass


ROLE_PERMISSIONS: dict[ApprovalKind, set[str]] = {
    ApprovalKind.RCA_REVIEW: {"l2_sme", "operations_supervisor"},
    ApprovalKind.REMOTE_ACTION: {"noc_analyst", "l2_sme", "operations_supervisor"},
    ApprovalKind.DISPATCH: {"dispatcher", "operations_supervisor"},
    ApprovalKind.HANDOVER: {"plant_supervisor", "operations_supervisor"},
    ApprovalKind.HIGH_BLAST_RADIUS: {"operations_supervisor"},
    ApprovalKind.EXCEPTIONAL_CLOSURE: {"operations_supervisor"},
}


class WorkflowService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        repository: Repository | None = None,
        mcp: MCPClient | None = None,
        assistant: RCAAssistant | None = None,
        catalog: ScenarioCatalog | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or Repository(self.settings)
        self.repository.setup()
        self.catalog = catalog or ScenarioCatalog(settings=self.settings)
        if mcp is not None:
            self.mcp = mcp
        elif self.settings.mcp_use_network:
            self.mcp = HTTPMCPClient(self.settings)
        else:
            registry = ToolRegistry(
                settings=self.settings,
                catalog=self.catalog,
                store=EffectStore(self.settings.mcp_effect_db),
            )
            self.mcp = InProcessMCPClient(registry)
        self.mcp.verify_compatibility()
        self.assistant = assistant or build_rca_assistant(self.settings)
        self.portable = PortableWorkflowEngine(
            repository=self.repository,
            mcp=self.mcp,
            assistant=self.assistant,
            settings=self.settings,
        )
        if self.settings.use_langgraph or self.settings.workflow_engine == "langgraph":
            try:
                from lpr_cpe_demo.workflow.langgraph_runtime import LangGraphWorkflowEngine

                self.engine: Any = LangGraphWorkflowEngine(self.portable, self.settings)
            except Exception:
                if not self.settings.langgraph_fallback_allowed:
                    raise
                # Explicit development fallback only; the System page exposes the active engine.
                self.engine = self.portable
        else:
            self.engine = self.portable

    def list_scenarios(self) -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in self.catalog.list()]

    def _new_incident(
        self,
        *,
        scenario_name: str,
        title: str | None = None,
        source: str | None = None,
        priority: str | None = None,
        context_updates: dict[str, Any] | None = None,
        incident_id: str | None = None,
    ) -> IncidentState:
        fixture = dict(self.catalog.get(scenario_name))
        if context_updates:
            fixture.update(context_updates)
        resolved_incident_id = incident_id or f"INC-{uuid4().hex[:10].upper()}"
        resolved_priority = priority or str(fixture.get("priority", "P2"))
        now = utc_now()
        return IncidentState(
            incident_id=resolved_incident_id,
            scenario_name=scenario_name,
            title=title or str(fixture["label"]),
            technology=Technology(fixture["technology"]),
            priority=resolved_priority,
            source=source or str(fixture.get("source", "auto_detect")),
            created_at=now,
            updated_at=now,
            sla_deadline=now + timedelta(hours=4 if resolved_priority == "P1" else 8),
            scenario_context=fixture,
        )

    @staticmethod
    def _episode_status(state: IncidentState) -> EpisodeStatus:
        if state.status == CaseStatus.CLOSED:
            return EpisodeStatus.CLOSED
        if state.status == CaseStatus.ESCALATED:
            return EpisodeStatus.ESCALATED
        if state.status == CaseStatus.QUARANTINED:
            return EpisodeStatus.QUARANTINED
        if state.status == CaseStatus.WAITING:
            return EpisodeStatus.WAITING
        return EpisodeStatus.ACTIVE

    def _sync_episode(self, state: IncidentState) -> AssuranceEpisode:
        episode = self.repository.get_assurance_episode_by_incident(state.incident_id)
        if episode is None:
            episode = AssuranceEpisode(
                episode_id=episode_id_for_repair(state.incident_id),
                origin=AssuranceOrigin.REPAIR,
                source_key=f"repair:{state.incident_id}",
                incident_id=state.incident_id,
                technology=state.technology.value,
                title=state.title,
                status=self._episode_status(state),
                workflow_stage=state.stage.value,
                metadata={"scenario_name": state.scenario_name},
            )
        else:
            episode.status = self._episode_status(state)
            episode.workflow_stage = state.stage.value
            episode.title = state.title
        return self.repository.save_assurance_episode(episode)

    def _record_episode_event(
        self,
        episode: AssuranceEpisode,
        event_type: str,
        *,
        actor: str = "workflow",
        payload: dict[str, Any] | None = None,
    ) -> None:
        event = AssuranceEpisodeEvent(
            event_id=stable_id(
                episode.episode_id,
                event_type,
                episode.workflow_stage,
                json.dumps(payload or {}, sort_keys=True, default=str),
                prefix="asevt",
            ),
            episode_id=episode.episode_id,
            incident_id=episode.incident_id,
            event_type=event_type,
            actor=actor,
            payload=payload or {},
        )
        self.repository.append_assurance_event(event)

    def start_scenario(self, name: str, *, run_until_pause: bool = True) -> IncidentState:
        state = self._new_incident(scenario_name=name)
        self.repository.save_incident(state)
        episode = self._sync_episode(state)
        self._record_episode_event(episode, "repair_episode_created")
        if run_until_pause:
            state = self.engine.run_until_pause(state)
            self._sync_episode(state)
        return state

    def create_install_handoff(
        self,
        request: InstallHandoffRequest,
    ) -> InstallHandoffResult:
        if request.production_write:
            raise ApprovalConflict("PRODUCTION_WRITE_NOT_PERMITTED")
        existing = self.repository.get_assurance_episode_by_source(request.source_key)
        if existing is not None:
            incident = self.get_incident(existing.incident_id)
            return InstallHandoffResult(
                created=False,
                episode=existing,
                incident=incident.model_dump(mode="json"),
            )

        scenario_name = (
            "pon_odp_handover" if request.technology == "PON" else "hfc_remote_fail_clean_success"
        )
        state = self._new_incident(
            scenario_name=scenario_name,
            title=request.title,
            source="install_assurance",
            priority=request.priority,
            incident_id=stable_id(
                request.source_key,
                prefix="inc",
            ).upper(),
            context_updates={
                "install_run_id": request.run_id,
                "install_watch_id": request.watch_id,
                "install_episode_id": request.install_episode_id,
                "service_id": request.service_id,
                "device_id": request.device_id,
                "install_handoff_reason": request.reason,
                "install_source_summary": request.source_summary,
                "install_source_evidence": request.evidence,
            },
        )
        self.repository.save_incident(state)
        episode = AssuranceEpisode(
            episode_id=episode_id_for_install(request),
            origin=AssuranceOrigin.INSTALL,
            source_key=request.source_key,
            incident_id=state.incident_id,
            install_run_id=request.run_id,
            install_watch_id=request.watch_id,
            install_episode_id=request.install_episode_id,
            service_id=request.service_id,
            device_id=request.device_id,
            technology=request.technology,
            status=EpisodeStatus.ACTIVE,
            workflow_stage=state.stage.value,
            title=state.title,
            metadata={
                "handoff_reason": request.reason,
                "source_summary": request.source_summary,
            },
        )
        self.repository.save_assurance_episode(episode)
        self._record_episode_event(
            episode,
            "install_handoff_claimed",
            actor="digital_twin_api",
            payload={
                "run_id": request.run_id,
                "watch_id": request.watch_id,
                "install_episode_id": request.install_episode_id,
            },
        )
        state = self.engine.run_until_pause(state)
        episode = self._sync_episode(state)
        self._record_episode_event(episode, "repair_workflow_started")
        return InstallHandoffResult(
            created=True,
            episode=episode,
            incident=state.model_dump(mode="json"),
        )

    def list_assurance_episodes(self, limit: int = 200) -> list[AssuranceEpisode]:
        return self.repository.list_assurance_episodes(limit=limit)

    def get_assurance_episode(self, episode_id: str) -> dict[str, Any]:
        episode = self.repository.get_assurance_episode(episode_id)
        if episode is None:
            raise IncidentNotFound(episode_id)
        return {
            "episode": episode.model_dump(mode="json"),
            "events": [
                event.model_dump(mode="json")
                for event in self.repository.list_assurance_events(episode_id)
            ],
            "incident": self.get_incident(episode.incident_id).model_dump(mode="json"),
        }

    def get_incident(self, incident_id: str) -> IncidentState:
        state = self.repository.get_incident(incident_id)
        if state is None:
            raise IncidentNotFound(incident_id)
        return state

    def list_incidents(self) -> list[IncidentState]:
        return self.repository.list_incidents()

    def run_incident(self, incident_id: str, *, one_step: bool = False) -> IncidentState:
        state = self.get_incident(incident_id)
        state = self.engine.run_one(state) if one_step else self.engine.run_until_pause(state)
        self._sync_episode(state)
        return state

    def list_approvals(
        self,
        *,
        status: ApprovalStatus | None = None,
        incident_id: str | None = None,
    ) -> list[ApprovalRequest]:
        return self.repository.list_approvals(status=status, incident_id=incident_id)

    def decide_approval(
        self,
        approval_id: str,
        decision: ApprovalDecisionInput,
    ) -> IncidentState:
        approval = self.repository.get_approval(approval_id)
        if approval is None:
            raise ApprovalNotFound(approval_id)
        if approval.status == ApprovalStatus.CONSUMED:
            raise ApprovalConflict("APPROVAL_ALREADY_CONSUMED")
        if approval.status != ApprovalStatus.PENDING:
            raise ApprovalConflict(f"APPROVAL_NOT_PENDING:{approval.status.value}")
        allowed = ROLE_PERMISSIONS.get(approval.kind, set())
        if decision.role not in allowed:
            raise AuthorizationError(
                f"Role {decision.role} cannot decide {approval.kind.value}; allowed roles: {sorted(allowed)}"
            )
        if decision.decision in {"reject", "override", "request_more"} and not decision.reason.strip():
            raise ApprovalConflict("DECISION_REASON_REQUIRED")

        mapping = {
            "approve": ApprovalStatus.APPROVED,
            "override": ApprovalStatus.APPROVED,
            "reject": ApprovalStatus.REJECTED,
            "request_more": ApprovalStatus.REQUEST_MORE,
        }
        approval.status = mapping[decision.decision]
        approval.decided_by = decision.actor
        approval.decision_reason = decision.reason
        approval.selected_option = decision.selected_option
        approval.decided_at = datetime.now(UTC)
        self.repository.save_approval(approval)

        state = self.get_incident(approval.incident_id)
        if state.pending_approval_id != approval_id:
            raise ApprovalConflict("APPROVAL_INCIDENT_STATE_MISMATCH")
        result: dict[str, Any] = {
            "approval_id": approval.approval_id,
            "idempotency_key": approval.idempotency_key,
            "kind": approval.kind.value,
            "decision": decision.decision,
            "actor": decision.actor,
            "role": decision.role,
            "reason": decision.reason,
            "selected_option": decision.selected_option,
            "selected_domain": decision.selected_domain.value if decision.selected_domain else None,
            "original_action_type": approval.action_type,
        }
        if decision.decision in {"approve", "override"} and approval.kind != ApprovalKind.RCA_REVIEW:
            result["approval_token"] = build_approval_token(
                approval=approval,
                settings=self.settings,
            )
        before_actions = len(state.action_history)
        if hasattr(self.engine, "resume"):
            state = self.engine.resume(state.incident_id, result)
        else:
            state.approval_result = result
            state.status = CaseStatus.OPEN
            self.repository.save_incident(state)
            state = self.engine.run_until_pause(state)
        alternative_selected = (
            decision.decision == "override"
            and bool(decision.selected_option)
            and decision.selected_option != approval.action_type
        )
        if approval.kind != ApprovalKind.RCA_REVIEW and (
            len(state.action_history) > before_actions or alternative_selected
        ):
            # The original approval is consumed when its action executes or when
            # the reviewer selects a different action that must receive a fresh
            # policy decision and approval token.
            approval.status = ApprovalStatus.CONSUMED
            approval.consumed_at = datetime.now(UTC)
            self.repository.save_approval(approval)
        elif approval.kind == ApprovalKind.RCA_REVIEW and decision.decision in {"approve", "override"}:
            approval.status = ApprovalStatus.CONSUMED
            approval.consumed_at = datetime.now(UTC)
            self.repository.save_approval(approval)
        self._sync_episode(state)
        return state

    def quarantine_policy(self) -> QuarantinePolicy:
        return QuarantinePolicy(
            enabled=self.settings.post_action_quarantine_enabled,
            duration_seconds=self.settings.post_action_quarantine_duration_seconds,
            check_interval_seconds=(
                self.settings.post_action_quarantine_check_interval_seconds
            ),
            required_healthy_checks=(
                self.settings.post_action_quarantine_required_healthy_checks
            ),
            max_extensions=self.settings.post_action_quarantine_max_extensions,
            lease_seconds=self.settings.post_action_quarantine_lease_seconds,
        )

    def list_quarantines(
        self,
        *,
        status: QuarantineStatus | None = None,
        incident_id: str | None = None,
        limit: int = 200,
    ) -> list[PostActionQuarantine]:
        return self.repository.list_quarantines(
            status=status,
            incident_id=incident_id,
            limit=limit,
        )

    def get_quarantine(self, quarantine_id: str) -> dict[str, Any]:
        quarantine = self.repository.get_quarantine(quarantine_id)
        if quarantine is None:
            raise IncidentNotFound(quarantine_id)
        return {
            "quarantine": quarantine.model_dump(mode="json"),
            "observations": [
                item.model_dump(mode="json")
                for item in self.repository.list_quarantine_observations(
                    quarantine_id
                )
            ],
            "incident": self.get_incident(
                quarantine.incident_id
            ).model_dump(mode="json"),
        }

    def record_quarantine_observation(
        self,
        quarantine_id: str,
        request: QuarantineObservationRequest,
    ) -> dict[str, Any]:
        existing = self.repository.get_quarantine_observation_by_key(
            request.idempotency_key
        )
        if existing is not None:
            return {
                "created": False,
                "observation": existing.model_dump(mode="json"),
                **self.get_quarantine(existing.quarantine_id),
            }

        quarantine = self.repository.get_quarantine(quarantine_id)
        if quarantine is None:
            raise IncidentNotFound(quarantine_id)
        quarantine, transition = evaluate_quarantine_observation(
            quarantine,
            request,
        )
        observation = QuarantineObservation(
            observation_id=observation_id_for(
                quarantine_id,
                request.idempotency_key,
            ),
            quarantine_id=quarantine_id,
            incident_id=quarantine.incident_id,
            observed_at=request.observed_at,
            health=request.health,
            source=request.source,
            actor=request.actor,
            idempotency_key=request.idempotency_key,
            metrics=request.metrics,
            transition=transition,
        )
        self.repository.append_quarantine_observation(observation)
        self.repository.save_quarantine(quarantine)

        state = self.get_incident(quarantine.incident_id)
        if transition in {
            QuarantineTransition.CONTINUE,
            QuarantineTransition.EXTEND,
        }:
            state.stage = Stage.POST_ACTION_QUARANTINE
            state.status = CaseStatus.QUARANTINED
            state.current_owner = "Assurance quarantine"
            state.append_event(
                event_type=(
                    "post_action_quarantine_extended"
                    if transition == QuarantineTransition.EXTEND
                    else "post_action_health_observed"
                ),
                title=(
                    "Post-action quarantine extended"
                    if transition == QuarantineTransition.EXTEND
                    else "Post-action health observed"
                ),
                detail=(
                    f"Health={request.health.value}; closure remains blocked."
                ),
                metadata={
                    "quarantine_id": quarantine_id,
                    "observation_id": observation.observation_id,
                },
            )
            self.repository.save_incident(state)
        elif transition == QuarantineTransition.RELEASE:
            state.stage = Stage.RECONCILE
            state.status = CaseStatus.OPEN
            state.current_owner = "Assurance reconciliation"
            state.append_event(
                event_type="post_action_quarantine_released",
                title="Post-action quarantine released",
                detail=(
                    "The minimum duration and repeated healthy-check policy "
                    "passed; linked records may now close."
                ),
                metadata={"quarantine_id": quarantine_id},
            )
            self.repository.save_incident(state)
            state = self.engine.run_until_pause(state)
        elif transition == QuarantineTransition.REOPEN:
            state.stage = Stage.FAILURE_REVIEW
            state.status = CaseStatus.OPEN
            state.current_owner = "RCA / recovery"
            state.active_quarantine_id = None
            state.verification_passed = False
            state.append_event(
                event_type="post_action_quarantine_reopened",
                title="Service degraded during quarantine",
                detail=(
                    "The case returned to failure review on the same incident "
                    "before any repeat action."
                ),
                severity=Severity.WARNING,
                metadata={"quarantine_id": quarantine_id},
            )
            self.repository.save_incident(state)
        elif transition == QuarantineTransition.ESCALATE:
            state.stage = Stage.ESCALATED
            state.status = CaseStatus.ESCALATED
            state.current_owner = "L2/SME"
            state.active_quarantine_id = None
            state.last_error = "Quarantine health remained unknown after extension budget"
            state.append_event(
                event_type="post_action_quarantine_escalated",
                title="Quarantine escalated",
                detail=state.last_error,
                severity=Severity.CRITICAL,
                metadata={"quarantine_id": quarantine_id},
            )
            self.repository.save_incident(state)

        episode = self._sync_episode(state)
        self._record_episode_event(
            episode,
            f"quarantine_{transition.value}",
            actor=request.actor,
            payload={
                "quarantine_id": quarantine_id,
                "observation_id": observation.observation_id,
                "health": request.health.value,
            },
        )
        return {
            "created": True,
            "observation": observation.model_dump(mode="json"),
            "quarantine": quarantine.model_dump(mode="json"),
            "incident": state.model_dump(mode="json"),
        }

    def run_due_quarantine_jobs(
        self,
        *,
        now: datetime | None = None,
        worker_id: str = "workflow-api",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        observed_at = now or utc_now()
        claimed = self.repository.claim_due_quarantines(
            now=observed_at,
            worker_id=worker_id,
            lease_seconds=self.settings.post_action_quarantine_lease_seconds,
            limit=limit,
        )
        results: list[dict[str, Any]] = []
        for quarantine in claimed:
            state = self.get_incident(quarantine.incident_id)
            raw_sequence = list(
                state.scenario_context.get("quarantine_health_sequence") or []
            )
            observed_count = len(
                self.repository.list_quarantine_observations(
                    quarantine.quarantine_id
                )
            )
            raw_health = (
                str(raw_sequence[min(observed_count, len(raw_sequence) - 1)])
                if raw_sequence
                else QuarantineHealth.HEALTHY.value
            )
            request = QuarantineObservationRequest(
                health=QuarantineHealth(raw_health),
                observed_at=observed_at,
                source="scheduled_health_check",
                actor=worker_id,
                idempotency_key=stable_id(
                    quarantine.quarantine_id,
                    quarantine.next_check_at.isoformat(),
                    prefix="qjob",
                ),
                metrics={
                    "simulated": True,
                    "source": "NXT and service-test adapter",
                },
            )
            results.append(
                self.record_quarantine_observation(
                    quarantine.quarantine_id,
                    request,
                )
            )
        return results

    def measurement_projection(self) -> dict[str, Any]:
        """Return live workflow records using the shared dashboard metric contract."""

        return build_operations_projection(
            self.list_incidents(),
            self.list_approvals(),
        )

    def dashboard(self) -> dict[str, Any]:
        summary = self.repository.summary()
        incidents = self.list_incidents()
        summary.update(
            {
                "total": len(incidents),
                "remote_attempts": sum(item.remote_attempts for item in incidents),
                "field_visits": sum(item.field_visits for item in incidents),
                "mr_attempts": sum(item.mr_attempts for item in incidents),
                "returned_to_rca": sum(item.diagnostic_cycles > 1 for item in incidents),
                "domain_disagreements": sum(item.domain_agreement == "disagree" for item in incidents),
            }
        )
        return summary

    def system_status(self) -> dict[str, Any]:
        try:
            tools = self.mcp.list_tools()
            mcp_status = "ok"
        except Exception as exc:
            tools = []
            mcp_status = f"error: {exc}"
        return {
            "application_mode": self.settings.application_mode,
            "production_writes_enabled": self.settings.production_writes_enabled,
            "writes_permitted": self.settings.writes_permitted,
            "workflow_engine_requested": (
                "langgraph" if (self.settings.use_langgraph or self.settings.workflow_engine == "langgraph") else "portable"
            ),
            "workflow_engine_active": type(self.engine).__name__,
            "model_provider": self.settings.model_provider,
            "model_name": self.settings.model_name,
            "model_assistant_active": type(self.assistant).__name__,
            "model_fallback_allowed": self.settings.model_fallback_allowed,
            "mcp_status": mcp_status,
            "mcp_profile": self.settings.mcp_profile,
            "mcp_protocol_version": self.settings.mcp_protocol_version,
            "mcp_implementation": "custom_strict_stateless_http",
            "mcp_tools": tools,
            "unified_assurance": "p2",
            "post_action_quarantine": self.quarantine_policy().model_dump(
                mode="json"
            ),
        }

    def close(self) -> None:
        close = getattr(self.engine, "close", None)
        if callable(close):
            close()
        self.repository.close()

    def reset(self) -> None:
        self.repository.reset()
