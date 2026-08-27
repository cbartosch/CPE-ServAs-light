from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from lpr_cpe_demo.config import Settings, get_settings
from lpr_cpe_demo.domain import (
    ApprovalDecisionInput,
    ApprovalKind,
    ApprovalRequest,
    ApprovalStatus,
    CaseStatus,
    IncidentState,
    Technology,
    utc_now,
)
from lpr_cpe_demo.llm import RCAAssistant, build_rca_assistant
from lpr_cpe_demo.measurement import build_operations_projection
from lpr_cpe_demo.mcp_client import HTTPMCPClient, InProcessMCPClient, MCPClient
from lpr_cpe_demo.mcp_server.store import EffectStore
from lpr_cpe_demo.mcp_server.tools import ToolRegistry
from lpr_cpe_demo.persistence import Repository
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

    def start_scenario(self, name: str, *, run_until_pause: bool = True) -> IncidentState:
        fixture = self.catalog.get(name)
        incident_id = f"INC-{uuid4().hex[:10].upper()}"
        state = IncidentState(
            incident_id=incident_id,
            scenario_name=name,
            title=str(fixture["label"]),
            technology=Technology(fixture["technology"]),
            priority=str(fixture.get("priority", "P2")),
            source=str(fixture.get("source", "auto_detect")),
            created_at=utc_now(),
            updated_at=utc_now(),
            sla_deadline=utc_now() + timedelta(hours=4 if fixture.get("priority") == "P1" else 8),
            scenario_context=fixture,
        )
        self.repository.save_incident(state)
        if run_until_pause:
            state = self.engine.run_until_pause(state)
        return state

    def get_incident(self, incident_id: str) -> IncidentState:
        state = self.repository.get_incident(incident_id)
        if state is None:
            raise IncidentNotFound(incident_id)
        return state

    def list_incidents(self) -> list[IncidentState]:
        return self.repository.list_incidents()

    def run_incident(self, incident_id: str, *, one_step: bool = False) -> IncidentState:
        state = self.get_incident(incident_id)
        return self.engine.run_one(state) if one_step else self.engine.run_until_pause(state)

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
        return state

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
        }

    def close(self) -> None:
        close = getattr(self.engine, "close", None)
        if callable(close):
            close()
        self.repository.close()

    def reset(self) -> None:
        self.repository.reset()
