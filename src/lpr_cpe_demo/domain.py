from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from hashlib import sha256
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from lpr_cpe_demo.controls import authoritative_sla_deadline, sla_authority_label


def utc_now() -> datetime:
    return datetime.now(UTC)


def stable_id(*parts: object, prefix: str = "id") -> str:
    material = "|".join(str(part) for part in parts)
    return f"{prefix}-{sha256(material.encode('utf-8')).hexdigest()[:16]}"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, use_enum_values=False)


class Technology(StrEnum):
    HFC = "HFC"
    PON = "PON"


class Stage(StrEnum):
    NEW = "new"
    VALIDATE = "validate"
    CORRELATE = "correlate"
    EVIDENCE = "evidence"
    DETERMINISTIC_RCA = "deterministic_rca"
    LLM_RCA = "llm_rca"
    FUSION = "fusion"
    ACTION_RANKING = "action_ranking"
    POLICY = "policy"
    WAITING_APPROVAL = "waiting_approval"
    EXECUTE = "execute"
    VERIFY = "verify"
    POST_ACTION_QUARANTINE = "post_action_quarantine"
    FAILURE_REVIEW = "failure_review"
    RECONCILE = "reconcile"
    CLOSED = "closed"
    ESCALATED = "escalated"
    QUARANTINED = "quarantined"


class CaseStatus(StrEnum):
    OPEN = "open"
    WAITING = "waiting"
    CLOSED = "closed"
    ESCALATED = "escalated"
    QUARANTINED = "quarantined"


class FaultDomain(StrEnum):
    CPE = "cpe"
    WIFI_HOME = "wifi_or_home"
    PREMISE_WIRING = "premise_wiring"
    DROP = "drop"
    HFC_TAP = "hfc_tap"
    PON_ODP = "pon_odp"
    SHARED_NETWORK = "shared_network"
    PLANT = "plant"
    PROVISIONING = "provisioning"
    SERVICE_PLATFORM = "service_platform"
    POWER = "commercial_power"
    UNKNOWN = "unknown"


class ActionType(StrEnum):
    REMOTE_REPROVISION = "remote_reprovision"
    REMOTE_REBOOT = "remote_reboot"
    SELF_HELP = "self_help"
    CLEAN_BOOTS = "clean_boots"
    DIRTY_BOOTS_MR = "dirty_boots_mr"
    JOINT_DISPATCH = "joint_dispatch"
    PLANT_ACTION = "plant_action"
    MANUAL_REVIEW = "manual_review"
    MONITOR = "monitor"


class ApprovalKind(StrEnum):
    RCA_REVIEW = "rca_review"
    REMOTE_ACTION = "remote_action"
    DISPATCH = "dispatch"
    HANDOVER = "handover"
    HIGH_BLAST_RADIUS = "high_blast_radius"
    EXCEPTIONAL_CLOSURE = "exceptional_closure"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REQUEST_MORE = "request_more"
    CONSUMED = "consumed"
    EXPIRED = "expired"


class PolicyVerdict(StrEnum):
    ALLOWED = "allowed"
    REQUIRES_APPROVAL = "requires_approval"
    BLOCKED = "blocked"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class EvidenceItem(StrictModel):
    evidence_id: str
    kind: str
    source: str
    subject: str
    observed_at: datetime
    value: Any
    quality: float = Field(ge=0.0, le=1.0)
    summary: str


class Hypothesis(StrictModel):
    cause: str
    domain: FaultDomain
    probability: float = Field(ge=0.0, le=1.0)
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)


class RCAProposal(StrictModel):
    source: Literal["deterministic", "llm", "human", "fallback"]
    recommended_domain: FaultDomain
    confidence: float = Field(ge=0.0, le=1.0)
    hypotheses: list[Hypothesis]
    evidence_refs: list[str] = Field(default_factory=list)
    ruled_out: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    recommended_tests: list[str] = Field(default_factory=list)
    concise_rationale: str
    model_name: str | None = None
    prompt_version: str | None = None

    @model_validator(mode="after")
    def probabilities_are_bounded(self) -> "RCAProposal":
        if self.hypotheses and sum(item.probability for item in self.hypotheses) > 1.01:
            raise ValueError("RCA hypothesis probabilities must sum to no more than 1.01")
        return self


class ActionCandidate(StrictModel):
    rank: int = Field(ge=1)
    action_type: ActionType
    label: str
    expected_success: float = Field(ge=0.0, le=1.0)
    estimated_minutes: int = Field(ge=0)
    cost_class: Literal["low", "medium", "high"]
    risk_class: Literal["low", "medium", "high"]
    required_evidence: list[str] = Field(default_factory=list)
    success_test: list[str] = Field(default_factory=list)
    failure_trigger: str
    rationale: str


class PolicyDecision(StrictModel):
    verdict: PolicyVerdict
    reasons: list[str]
    policy_version: str = "demo-1.2"
    approval_kind: ApprovalKind | None = None
    required_role: str | None = None


class ApprovalRequest(StrictModel):
    approval_id: str
    incident_id: str
    action_type: str
    kind: ApprovalKind
    status: ApprovalStatus = ApprovalStatus.PENDING
    requested_role: str
    proposal: dict[str, Any]
    idempotency_key: str
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime = Field(default_factory=lambda: utc_now() + timedelta(hours=4))
    decided_by: str | None = None
    decision_reason: str | None = None
    selected_option: str | None = None
    decided_at: datetime | None = None
    consumed_at: datetime | None = None


class ActionResult(StrictModel):
    action_type: ActionType
    action_id: str
    outcome: Literal["succeeded", "failed", "simulated", "blocked"]
    summary: str
    idempotency_key: str
    replayed: bool = False
    evidence: list[EvidenceItem] = Field(default_factory=list)
    work_order_id: str | None = None
    mr_id: str | None = None


class TimelineEvent(StrictModel):
    event_id: str
    incident_id: str
    timestamp: datetime = Field(default_factory=utc_now)
    stage: Stage
    event_type: str
    title: str
    detail: str
    actor: str = "workflow"
    severity: Severity = Severity.INFO
    metadata: dict[str, Any] = Field(default_factory=dict)


class IncidentState(StrictModel):
    incident_id: str
    scenario_name: str
    title: str
    technology: Technology
    priority: str = "P2"
    source: str = "auto_detect"
    status: CaseStatus = CaseStatus.OPEN
    stage: Stage = Stage.NEW
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    sla_deadline: datetime = Field(default_factory=lambda: utc_now() + timedelta(hours=8))
    parent_incident_id: str | None = None
    parent_sla_deadline: datetime | None = None
    sla_mode: Literal["own", "inherits_parent", "paused"] = "own"
    topology: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    deterministic_rca: RCAProposal | None = None
    llm_rca: RCAProposal | None = None
    approved_rca: RCAProposal | None = None
    rca_domain_deterministic: FaultDomain | None = None
    rca_domain_llm: FaultDomain | None = None
    domain_agreement: Literal["agree", "disagree", "unknown"] = "unknown"
    gate_reason: Literal[
        "low_confidence", "domain_disagreement", "policy", "none", "budget"
    ] = "none"
    action_candidates: list[ActionCandidate] = Field(default_factory=list)
    selected_action: ActionCandidate | None = None
    next_best_action: ActionCandidate | None = None
    policy_decision: PolicyDecision | None = None
    pending_approval_id: str | None = None
    approval_result: dict[str, Any] | None = None
    action_history: list[ActionResult] = Field(default_factory=list)
    remote_attempts: int = 0
    self_help_attempts: int = 0
    field_visits: int = 0
    mr_attempts: int = 0
    diagnostic_cycles: int = 0
    total_steps: int = 0
    new_evidence_since_last_rca: bool = True
    verification_passed: bool | None = None
    verification_summary: str | None = None
    pre_action_health: dict[str, Any] | None = None
    immediate_post_action_health: dict[str, Any] | None = None
    active_quarantine_id: str | None = None
    current_owner: str = "NOC"
    delimiter: str | None = None
    work_orders: list[dict[str, Any]] = Field(default_factory=list)
    mr_records: list[dict[str, Any]] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    audit: list[dict[str, Any]] = Field(default_factory=list)
    scenario_context: dict[str, Any] = Field(default_factory=dict)
    last_error: str | None = None

    @property
    def effective_sla_deadline(self) -> datetime:
        return authoritative_sla_deadline(
            own_deadline=self.sla_deadline,
            sla_mode=self.sla_mode,
            parent_deadline=self.parent_sla_deadline,
        )

    @property
    def sla_authority(self) -> str:
        return sla_authority_label(
            sla_mode=self.sla_mode,
            parent_incident_id=self.parent_incident_id,
        )

    def add_evidence(self, item: EvidenceItem) -> None:
        """Append evidence once, keyed by its deterministic evidence ID."""

        if any(existing.evidence_id == item.evidence_id for existing in self.evidence):
            return
        self.evidence.append(item)

    def add_action_result(self, item: ActionResult) -> None:
        """Append an action once, keyed by the idempotency key that caused it."""

        if any(existing.idempotency_key == item.idempotency_key for existing in self.action_history):
            return
        self.action_history.append(item)

    @staticmethod
    def _revision_fingerprint(record: dict[str, Any]) -> str:
        payload = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)
        return sha256(payload.encode("utf-8")).hexdigest()

    def add_work_order(self, record: dict[str, Any]) -> None:
        """Append each work-order revision once; preserve later status revisions."""

        fingerprint = self._revision_fingerprint(record)
        if any(self._revision_fingerprint(item) == fingerprint for item in self.work_orders):
            return
        self.work_orders.append(record)

    def add_mr_record(self, record: dict[str, Any]) -> None:
        """Append each MR revision once; preserve later status revisions."""

        fingerprint = self._revision_fingerprint(record)
        if any(self._revision_fingerprint(item) == fingerprint for item in self.mr_records):
            return
        self.mr_records.append(record)

    def append_event(
        self,
        *,
        event_type: str,
        title: str,
        detail: str,
        actor: str = "workflow",
        severity: Severity = Severity.INFO,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Append a replay-safe timeline event.

        LangGraph may re-run a node after an interrupt or process failure. The event
        identity therefore depends only on durable state and event content, never on
        the current list length or a random identifier.
        """

        key = stable_id(
            self.incident_id,
            self.stage.value,
            event_type,
            self.total_steps,
            title,
            detail,
            prefix="evt",
        )
        if any(existing.event_id == key for existing in self.timeline):
            return
        self.timeline.append(
            TimelineEvent(
                event_id=key,
                incident_id=self.incident_id,
                stage=self.stage,
                event_type=event_type,
                title=title,
                detail=detail,
                actor=actor,
                severity=severity,
                metadata=metadata or {},
            )
        )


class ScenarioSummary(StrictModel):
    name: str
    label: str
    description: str
    technology: Technology
    expected_path: list[str]


class ApprovalDecisionInput(StrictModel):
    decision: Literal["approve", "reject", "request_more", "override"]
    actor: str
    role: str
    reason: str = ""
    selected_option: str | None = None
    selected_domain: FaultDomain | None = None



class MCPToolResult(StrictModel):
    name: str
    structured_content: dict[str, Any]
    is_error: bool = False
    error_code: str | None = None
