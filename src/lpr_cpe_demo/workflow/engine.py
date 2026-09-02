from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from lpr_cpe_demo.config import Settings, get_settings
from lpr_cpe_demo.controls import (derive_action_key, derive_approval_id,
                                   fuse_and_gate)
from lpr_cpe_demo.domain import (
    ActionCandidate,
    ActionResult,
    ActionType,
    ApprovalKind,
    ApprovalRequest,
    ApprovalStatus,
    CaseStatus,
    EvidenceItem,
    FaultDomain,
    Hypothesis,
    IncidentState,
    PolicyDecision,
    PolicyVerdict,
    RCAProposal,
    Severity,
    Stage,
    stable_id,
    utc_now,
)
from lpr_cpe_demo.llm import RCAAssistant
from lpr_cpe_demo.mcp_client import MCPClient, MCPClientError
from lpr_cpe_demo.mcp_server.security import create_approval_token
from lpr_cpe_demo.persistence import Repository
from lpr_cpe_demo.quarantine import QuarantinePolicy, start_post_action_quarantine


class WorkflowError(RuntimeError):
    pass


class PortableWorkflowEngine:
    """A small deterministic runtime used for tests and as a fallback.

    The Docker profile selects the LangGraph wrapper, which delegates every graph step to this same
    implementation. This keeps process logic single-sourced while making the bundle testable in a restricted
    build environment that may not have LangGraph installed.
    """

    def __init__(
        self,
        *,
        repository: Repository,
        mcp: MCPClient,
        assistant: RCAAssistant,
        settings: Settings | None = None,
        telemetry_sink: Callable[[IncidentState], None] | None = None,
    ) -> None:
        self.repository = repository
        self.mcp = mcp
        self.assistant = assistant
        self.settings = settings or get_settings()
        # Optional dashboard instrumentation. run_one is the single choke point
        # every stage transition passes through, so one hook there captures the
        # whole flow. A sink failure must never fail an incident, so it is
        # swallowed and counted rather than raised. See telemetry.DATA_CONTRACT
        # for which panels this feeds and which still need a source system.
        self.telemetry_sink = telemetry_sink
        self.telemetry_failures = 0
        self._handlers: dict[Stage, Callable[[IncidentState], IncidentState]] = {
            Stage.NEW: self._receive,
            Stage.VALIDATE: self._validate,
            Stage.CORRELATE: self._correlate,
            Stage.EVIDENCE: self._assemble_evidence,
            Stage.DETERMINISTIC_RCA: self._deterministic_rca,
            Stage.LLM_RCA: self._llm_rca,
            Stage.FUSION: self._fusion,
            Stage.ACTION_RANKING: self._rank_actions,
            Stage.POLICY: self._policy,
            Stage.WAITING_APPROVAL: self._resume_approval,
            Stage.EXECUTE: self._execute,
            Stage.VERIFY: self._verify,
            Stage.FAILURE_REVIEW: self._failure_review,
            Stage.RECONCILE: self._reconcile,
        }

    def run_one(self, state: IncidentState) -> IncidentState:
        if state.stage in {
            Stage.CLOSED,
            Stage.ESCALATED,
            Stage.QUARANTINED,
            Stage.POST_ACTION_QUARANTINE,
        }:
            return state
        if state.stage == Stage.WAITING_APPROVAL and not state.approval_result:
            return state
        if state.total_steps >= self.settings.graph_max_steps:
            return self._escalate(state, "Total workflow step budget exhausted")
        handler = self._handlers.get(state.stage)
        if handler is None:
            return self._escalate(state, f"No handler for stage {state.stage.value}")
        state.total_steps += 1
        state.updated_at = utc_now()
        state = handler(state)
        self.repository.save_incident(state)
        self._emit_telemetry(state)
        return state

    def _emit_telemetry(self, state: IncidentState) -> None:
        if self.telemetry_sink is None:
            return
        try:
            self.telemetry_sink(state)
        except Exception:  # noqa: BLE001 - instrumentation must not break the flow
            self.telemetry_failures += 1

    def run_until_pause(self, state: IncidentState) -> IncidentState:
        while True:
            before = state.stage
            state = self.run_one(state)
            if state.stage in {
                Stage.CLOSED,
                Stage.ESCALATED,
                Stage.QUARANTINED,
                Stage.POST_ACTION_QUARANTINE,
            }:
                return state
            if state.stage == Stage.WAITING_APPROVAL and not state.approval_result:
                return state
            if state.stage == before and state.stage == Stage.WAITING_APPROVAL:
                return state

    def _receive(self, state: IncidentState) -> IncidentState:
        state.stage = Stage.VALIDATE
        state.append_event(
            event_type="signal_received",
            title="Signal received",
            detail=f"Received {state.source} signal for {state.technology.value} service.",
        )
        return state

    def _validate(self, state: IncidentState) -> IncidentState:
        if not bool(state.scenario_context.get("valid", True)):
            state.status = CaseStatus.QUARANTINED
            state.stage = Stage.QUARANTINED
            state.append_event(
                event_type="signal_quarantined",
                title="Signal quarantined",
                detail="The signal did not meet minimum quality or identity requirements.",
                severity=Severity.WARNING,
            )
            return state
        state.stage = Stage.CORRELATE
        state.append_event(
            event_type="signal_validated",
            title="Signal validated",
            detail="Signal quality and minimum identifiers passed deterministic checks.",
        )
        return state

    def _correlate(self, state: IncidentState) -> IncidentState:
        topology = self.mcp.call_tool(
            "get_topology", {"scenario_name": state.scenario_name}
        ).structured_content
        history = self.mcp.call_tool(
            "get_prior_incidents", {"scenario_name": state.scenario_name}
        ).structured_content
        state.topology = dict(topology.get("topology") or state.scenario_context.get("topology", {}))
        if history.get("common_cause"):
            state.parent_incident_id = str(history.get("parent_incident_id"))
            state.sla_mode = "inherits_parent"
            raw_parent_deadline = state.scenario_context.get("parent_sla_deadline")
            if raw_parent_deadline:
                state.parent_sla_deadline = datetime.fromisoformat(str(raw_parent_deadline))
            else:
                parent_hours = float(state.scenario_context.get("parent_sla_hours", 6.0))
                state.parent_sla_deadline = state.created_at + timedelta(hours=parent_hours)
            state.current_owner = "Plant/NOC"
            detail = (
                f"Associated with parent incident {state.parent_incident_id}; "
                f"the parent deadline {state.parent_sla_deadline.isoformat()} is authoritative "
                "while the child remains attached. The child's original clock is preserved."
            )
        else:
            detail = "No planned work, duplicate MR, or common-cause parent was found."
        state.stage = Stage.EVIDENCE
        state.append_event(
            event_type="correlation_complete",
            title="Correlation complete",
            detail=detail,
            metadata={"parent_incident_id": state.parent_incident_id},
        )
        return state

    def _assemble_evidence(self, state: IncidentState) -> IncidentState:
        cycle_index = state.diagnostic_cycles
        snapshot = self.mcp.call_tool(
            "get_nxt_snapshot",
            {"scenario_name": state.scenario_name, "cycle": cycle_index},
        ).structured_content
        existing_ids = {item.evidence_id for item in state.evidence}
        for index, raw in enumerate(snapshot.get("evidence", []), start=1):
            evidence_id = stable_id(
                state.incident_id,
                raw.get("kind"),
                cycle_index,
                index,
                prefix="evi",
            )
            if evidence_id in existing_ids:
                continue
            state.add_evidence(
                EvidenceItem(
                    evidence_id=evidence_id,
                    kind=str(raw.get("kind", "unknown")),
                    source=str(raw.get("source", "simulator")),
                    subject=str(raw.get("subject", state.incident_id)),
                    observed_at=utc_now(),
                    value=raw.get("value", raw.get("summary")),
                    quality=float(raw.get("quality", 1.0)),
                    summary=str(raw.get("summary", "Evidence item")),
                )
            )
        state.diagnostic_cycles += 1
        state.new_evidence_since_last_rca = True
        if state.diagnostic_cycles > self.settings.max_diagnostic_cycles:
            return self._escalate(state, "Diagnostic cycle budget exhausted")
        state.stage = Stage.DETERMINISTIC_RCA
        state.append_event(
            event_type="evidence_assembled",
            title="Evidence assembled",
            detail=f"Assembled {len(state.evidence)} evidence items for diagnostic cycle {state.diagnostic_cycles}.",
        )
        return state

    def _deterministic_rca(self, state: IncidentState) -> IncidentState:
        fixture = state.scenario_context
        cycles = list(fixture.get("deterministic_rca_by_cycle") or [])
        refs = [item.evidence_id for item in state.evidence]
        if cycles:
            raw = dict(cycles[min(max(state.diagnostic_cycles - 1, 0), len(cycles) - 1)])
            raw.update({"source": "deterministic", "evidence_refs": refs})
            proposal = RCAProposal.model_validate(raw)
        else:
            raw = dict(fixture.get("deterministic_rca") or {})
            if state.diagnostic_cycles > 1 and fixture.get("post_failure_rca"):
                raw = dict(fixture["post_failure_rca"])
            domain = FaultDomain(raw.get("domain", "unknown"))
            confidence = float(raw.get("confidence", 0.5))
            proposal = RCAProposal(
                source="deterministic",
                recommended_domain=domain,
                confidence=confidence,
                hypotheses=[
                    Hypothesis(
                        cause=str(raw.get("cause", "Unclassified fault")),
                        domain=domain,
                        probability=min(confidence, 1.0),
                        supporting_evidence=refs[:3],
                    )
                ],
                evidence_refs=refs,
                ruled_out=["duplicate incident", "planned maintenance"],
                missing_evidence=[],
                recommended_tests=["read-only service path validation"],
                concise_rationale=str(raw.get("cause", "Unclassified fault")),
            )
        state.deterministic_rca = proposal
        state.rca_domain_deterministic = proposal.recommended_domain
        state.stage = Stage.LLM_RCA
        state.append_event(
            event_type="deterministic_rca",
            title="Deterministic RCA completed",
            detail=f"Domain {proposal.recommended_domain.value}; confidence {proposal.confidence:.0%}.",
        )
        return state

    def _llm_rca(self, state: IncidentState) -> IncidentState:
        try:
            state.llm_rca = self.assistant.propose_rca(state)
        except Exception as exc:  # safe degradation; the model cannot block the deterministic path
            state.last_error = f"LLM assistant degraded: {exc}"
            state.llm_rca = state.deterministic_rca.model_copy(
                update={"source": "fallback", "concise_rationale": "Model unavailable; deterministic RCA copied."}
            ) if state.deterministic_rca else None
        state.rca_domain_llm = state.llm_rca.recommended_domain if state.llm_rca else FaultDomain.UNKNOWN
        state.stage = Stage.FUSION
        state.append_event(
            event_type="llm_rca",
            title="RCA assistant proposal completed",
            detail=(
                f"Domain {state.rca_domain_llm.value}; confidence {state.llm_rca.confidence:.0%}."
                if state.llm_rca
                else "No model proposal was available."
            ),
            actor="RCA assistant",
        )
        return state

    def _fusion(self, state: IncidentState) -> IncidentState:
        deterministic = state.deterministic_rca
        model = state.llm_rca
        if deterministic is None or model is None:
            return self._escalate(state, "RCA fusion inputs are incomplete")
        # v1.3: the rule lives in controls.fuse_and_gate so the engine and the
        # A/B harness in scripts/run_ab_matrix.py evaluate exactly the same logic.
        gate = fuse_and_gate(
            deterministic_domain=deterministic.recommended_domain.value,
            deterministic_confidence=deterministic.confidence,
            model_domain=model.recommended_domain.value,
            model_confidence=model.confidence,
            threshold=self.settings.rca_confidence_threshold,
        )
        state.domain_agreement = gate.domain_agreement
        confidence = gate.fused_confidence
        if gate.gate_reason == "low_confidence":
            state.gate_reason = "low_confidence"
            return self._prepare_approval(
                state,
                kind=ApprovalKind.RCA_REVIEW,
                action_type="rca_review",
                requested_role="l2_sme",
                proposal={
                    "deterministic": deterministic.model_dump(mode="json"),
                    "llm": model.model_dump(mode="json"),
                    "gate_reason": state.gate_reason,
                },
            )
        if gate.gate_reason == "domain_disagreement":
            state.gate_reason = "domain_disagreement"
            return self._prepare_approval(
                state,
                kind=ApprovalKind.RCA_REVIEW,
                action_type="rca_review",
                requested_role="l2_sme",
                proposal={
                    "deterministic": deterministic.model_dump(mode="json"),
                    "llm": model.model_dump(mode="json"),
                    "gate_reason": state.gate_reason,
                },
            )
        state.gate_reason = "none"
        state.approved_rca = deterministic
        state.new_evidence_since_last_rca = False
        state.stage = Stage.ACTION_RANKING
        state.append_event(
            event_type="rca_fused",
            title="RCA accepted",
            detail=f"Deterministic and model-assisted domains agree on {deterministic.recommended_domain.value}.",
        )
        return state

    def _rank_actions(self, state: IncidentState) -> IncidentState:
        cycles = list(state.scenario_context.get("action_by_cycle") or [])
        if cycles:
            raw_plan = cycles[min(max(state.diagnostic_cycles - 1, 0), len(cycles) - 1)]
            raw_best = dict(raw_plan.get("best") or {})
            if raw_best.get("action_type") == "escalate":
                return self._escalate(state, "Deterministic retry ceiling reached; human escalation required")
            selected = self._candidate_from_fixture(raw_best, rank=1, state=state)
            raw_next = raw_plan.get("next_best")
            next_best = (
                self._candidate_from_fixture(dict(raw_next), rank=2, state=state)
                if isinstance(raw_next, dict)
                else None
            )
            do_not_repeat = raw_plan.get("do_not_repeat")
        else:
            sequence = [ActionType(item) for item in state.scenario_context.get("action_sequence", [])]
            index = len(state.action_history)
            if index >= len(sequence):
                return self._escalate(state, "No unused action remains after the latest failed attempt")
            selected = self._candidate(sequence[index], rank=1, state=state)
            next_best = (
                self._candidate(sequence[index + 1], rank=2, state=state)
                if index + 1 < len(sequence)
                else None
            )
            do_not_repeat = "Return to RCA with new evidence; do not repeat the same action blindly."
        state.action_candidates = [selected] + ([next_best] if next_best else [])
        state.selected_action = selected
        state.next_best_action = next_best
        state.stage = Stage.POLICY
        try:
            explanation = self.assistant.explain_actions(
                state, [candidate.model_dump(mode="json") for candidate in state.action_candidates]
            )
        except Exception as exc:
            state.last_error = f"Action explanation degraded: {exc}"
            explanation = (
                f"Use {selected.label} first under the deterministic policy and scoring result."
                + (
                    f" If it fails or becomes ineligible, return to RCA before using {next_best.label}."
                    if next_best
                    else ""
                )
            )
        state.append_event(
            event_type="actions_ranked",
            title="Best and next-best action ranked",
            detail=explanation,
            actor="Resolution selector",
            metadata={"do_not_repeat": do_not_repeat},
        )
        return state

    def _policy(self, state: IncidentState) -> IncidentState:
        candidate = state.selected_action
        if candidate is None:
            return self._escalate(state, "No selected action exists")
        if len(state.evidence) == 0:
            state.policy_decision = PolicyDecision(
                verdict=PolicyVerdict.BLOCKED,
                reasons=["No evidence available"],
            )
            return self._escalate(state, "Policy blocked action because evidence is absent")
        kind, role = self._approval_for_action(candidate.action_type)
        state.policy_decision = PolicyDecision(
            verdict=PolicyVerdict.REQUIRES_APPROVAL,
            reasons=["Demo policy requires a named human for every side-effecting action"],
            approval_kind=kind,
            required_role=role,
        )
        return self._prepare_approval(
            state,
            kind=kind,
            action_type=candidate.action_type.value,
            requested_role=role,
            proposal={
                "best": candidate.model_dump(mode="json"),
                "next_best": state.next_best_action.model_dump(mode="json") if state.next_best_action else None,
                "policy": state.policy_decision.model_dump(mode="json"),
            },
        )

    def _resume_approval(self, state: IncidentState) -> IncidentState:
        result = state.approval_result or {}
        decision = result.get("decision")
        kind = result.get("kind")
        if decision == "request_more":
            state.pending_approval_id = None
            state.approval_result = None
            state.new_evidence_since_last_rca = True
            state.stage = Stage.EVIDENCE
            state.status = CaseStatus.OPEN
            state.append_event(
                event_type="approval_more_evidence",
                title="More evidence requested",
                detail=str(result.get("reason") or "Reviewer requested more evidence."),
                actor=str(result.get("actor") or "reviewer"),
            )
            return state
        if decision == "reject":
            return self._escalate(state, str(result.get("reason") or "Human reviewer rejected the proposal"))
        if decision not in {"approve", "override"}:
            return state

        if kind == ApprovalKind.RCA_REVIEW.value:
            selected_domain = result.get("selected_domain")
            base = state.deterministic_rca
            if selected_domain and base:
                chosen = FaultDomain(selected_domain)
                state.approved_rca = base.model_copy(
                    update={
                        "source": "human",
                        "recommended_domain": chosen,
                        "concise_rationale": str(result.get("reason") or "Human RCA decision"),
                    }
                )
            else:
                state.approved_rca = state.deterministic_rca
            state.pending_approval_id = None
            state.approval_result = None
            state.new_evidence_since_last_rca = False
            state.status = CaseStatus.OPEN
            state.stage = Stage.ACTION_RANKING
            state.append_event(
                event_type="rca_human_decision",
                title="Human RCA decision recorded",
                detail=f"Reviewer selected {state.approved_rca.recommended_domain.value if state.approved_rca else 'unknown'}.",
                actor=str(result.get("actor") or "reviewer"),
            )
            return state

        selected_option = result.get("selected_option")
        if decision == "override" and selected_option:
            try:
                override_type = ActionType(str(selected_option))
            except ValueError:
                return self._escalate(state, f"Unknown override action: {selected_option}")
            matching = next(
                (item for item in state.action_candidates if item.action_type == override_type),
                None,
            )
            if matching is None:
                return self._escalate(
                    state,
                    f"Override action {override_type.value} was not one of the reviewed candidates",
                )
            state.selected_action = matching
            original_action = str(result.get("original_action_type") or "")
            if original_action and original_action != override_type.value:
                # A human-selected alternative has a different risk/role/tool contract.
                # Return through policy and mint a new approval; never reuse a token
                # that authorised the original action.
                state.pending_approval_id = None
                state.approval_result = None
                state.status = CaseStatus.OPEN
                state.stage = Stage.POLICY
                state.append_event(
                    event_type="action_override_recheck",
                    title="Alternative action selected",
                    detail=(
                        f"Reviewer selected {override_type.value}; policy and approval "
                        "are being re-evaluated for the alternative action."
                    ),
                    actor=str(result.get("actor") or "reviewer"),
                )
                return state

        state.status = CaseStatus.OPEN
        state.stage = Stage.EXECUTE
        return state

    def _execute(self, state: IncidentState) -> IncidentState:
        candidate = state.selected_action
        approval = state.approval_result or {}
        if candidate is None:
            return self._escalate(state, "Execution reached without an action")
        if approval.get("decision") not in {"approve", "override"}:
            return self._escalate(state, "Execution reached without an approved decision")
        approval_id = str(approval.get("approval_id"))
        idempotency_key = str(approval.get("idempotency_key"))
        action_type = candidate.action_type
        state.pre_action_health = {
            "captured_at": utc_now().isoformat(),
            "verdict": "degraded",
            "evidence_refs": [item.evidence_id for item in state.evidence],
            "evidence_count": len(state.evidence),
            "diagnostic_cycle": state.diagnostic_cycles,
        }
        attempt = self._attempt_for(state, action_type)
        existing = self.repository.get_idempotent_result(idempotency_key)
        if existing is None:
            tool_name = self._tool_for_action(action_type)
            arguments: dict[str, Any] = {
                "incident_id": state.incident_id,
                "scenario_name": state.scenario_name,
                "action_type": action_type.value,
                "attempt": attempt,
                "idempotency_key": idempotency_key,
                "approval_token": approval["approval_token"],
                "delimiter": state.delimiter or self._default_delimiter(state),
                "owner": "Plant/OSP",
            }
            try:
                result = self.mcp.call_tool(tool_name, arguments).structured_content
            except MCPClientError as exc:
                state.last_error = f"{exc.code or 'MCP_ERROR'}: {exc}"
                return self._escalate(state, state.last_error)
            self.repository.save_idempotent_result(
                idempotency_key=idempotency_key,
                incident_id=state.incident_id,
                action_type=action_type.value,
                approval_id=approval_id,
                result=result,
            )
        else:
            result = dict(existing)
            result["replayed"] = True

        self._increment_attempt(state, action_type)
        action_result = ActionResult(
            action_type=action_type,
            action_id=str(result.get("action_id") or stable_id(idempotency_key, prefix="act")),
            outcome=str(result.get("outcome", "simulated")),
            summary=str(result.get("summary", "Simulated action completed")),
            idempotency_key=idempotency_key,
            replayed=bool(result.get("replayed", False)),
            work_order_id=result.get("work_order_id"),
            mr_id=result.get("mr_id"),
        )
        state.add_action_result(action_result)
        if result.get("work_order_id"):
            state.add_work_order(result)
        if result.get("mr_id"):
            state.add_mr_record(result)
        if result.get("field_findings", {}).get("delimiter"):
            state.delimiter = str(result["field_findings"]["delimiter"])
        state.pending_approval_id = None
        state.approval_result = None
        state.stage = Stage.VERIFY
        state.append_event(
            event_type="action_executed",
            title=f"{candidate.label} executed",
            detail=action_result.summary,
            actor="MCP action tool",
            metadata={"idempotency_key": idempotency_key, "replayed": action_result.replayed},
        )
        return state

    def _verify(self, state: IncidentState) -> IncidentState:
        last = state.action_history[-1] if state.action_history else None
        if last is None:
            return self._escalate(state, "Verification reached without an action result")
        verification_map = state.scenario_context.get("verification_by_action")
        if verification_map:
            action_type = last.action_type.value
            outcomes = list(verification_map.get(action_type, []))
            occurrences = sum(item.action_type == last.action_type for item in state.action_history)
            raw = outcomes[min(max(occurrences - 1, 0), len(outcomes) - 1)] if outcomes else {
                "passed": True,
                "summary": "Simulated post-action validation passed.",
            }
            passed = bool(raw.get("passed", False))
            summary = str(raw.get("summary") or "Post-action validation completed.")
            metadata = dict(raw)
        else:
            outcomes = list(state.scenario_context.get("verification_outcomes", []))
            index = max(len(state.action_history) - 1, 0)
            passed = bool(outcomes[min(index, len(outcomes) - 1)]) if outcomes else True
            summary = (
                f"Post-fix NXT and service tests remained stable for {self.settings.stability_window_minutes} minutes."
                if passed
                else "The original anomaly or customer impact remains after the action."
            )
            metadata = {"passed": passed}
        state.verification_passed = passed
        state.verification_summary = summary
        state.immediate_post_action_health = {
            "captured_at": utc_now().isoformat(),
            "verdict": "healthy" if passed else "degraded",
            "summary": summary,
            "evidence": metadata,
        }
        if passed:
            if self.settings.post_action_quarantine_enabled:
                last_action = state.action_history[-1]
                episode = self.repository.get_assurance_episode_by_incident(
                    state.incident_id
                )
                episode_id = (
                    episode.episode_id
                    if episode is not None
                    else stable_id("repair", state.incident_id, prefix="ase")
                )
                policy = QuarantinePolicy(
                    enabled=True,
                    duration_seconds=(
                        self.settings.post_action_quarantine_duration_seconds
                    ),
                    check_interval_seconds=(
                        self.settings.post_action_quarantine_check_interval_seconds
                    ),
                    required_healthy_checks=(
                        self.settings.post_action_quarantine_required_healthy_checks
                    ),
                    max_extensions=(
                        self.settings.post_action_quarantine_max_extensions
                    ),
                    lease_seconds=(
                        self.settings.post_action_quarantine_lease_seconds
                    ),
                )
                quarantine = self.repository.get_quarantine_by_action(
                    last_action.action_id
                )
                if quarantine is None:
                    quarantine = start_post_action_quarantine(
                        episode_id=episode_id,
                        incident_id=state.incident_id,
                        action_id=last_action.action_id,
                        action_type=last_action.action_type.value,
                        pre_action_health=state.pre_action_health or {},
                        immediate_post_action_health=(
                            state.immediate_post_action_health or {}
                        ),
                        policy=policy,
                        metadata={
                            "scenario_name": state.scenario_name,
                            "source": state.source,
                        },
                    )
                    self.repository.save_quarantine(quarantine)
                state.active_quarantine_id = quarantine.quarantine_id
                state.stage = Stage.POST_ACTION_QUARANTINE
                state.status = CaseStatus.QUARANTINED
                state.current_owner = "Assurance quarantine"
                state.append_event(
                    event_type="post_action_quarantine_started",
                    title="Post-action quarantine started",
                    detail=(
                        "Immediate restoration passed. Closure is blocked until "
                        "the stability window and repeated health checks pass."
                    ),
                    metadata={
                        "quarantine_id": quarantine.quarantine_id,
                        "minimum_release_at": (
                            quarantine.minimum_release_at.isoformat()
                        ),
                    },
                )
                return state
            state.stage = Stage.RECONCILE
            state.append_event(
                event_type="verification_passed",
                title="Restoration verified",
                detail=summary,
                metadata=metadata,
            )
            return state
        state.stage = Stage.FAILURE_REVIEW
        state.append_event(
            event_type="verification_failed",
            title="Restoration not verified",
            detail=summary,
            severity=Severity.WARNING,
            metadata=metadata,
        )
        return state

    def _failure_review(self, state: IncidentState) -> IncidentState:
        last = state.action_history[-1] if state.action_history else None
        if last and last.action_type == ActionType.DIRTY_BOOTS_MR:
            verification_map = state.scenario_context.get("verification_by_action", {})
            outcomes = list(verification_map.get(last.action_type.value, [])) if verification_map else []
            occurrences = sum(item.action_type == last.action_type for item in state.action_history)
            raw = outcomes[min(max(occurrences - 1, 0), len(outcomes) - 1)] if outcomes else {}
            legacy_reverse = bool(state.scenario_name == "pon_reverse_handover" and len(state.action_history) == 1)
            if raw.get("reverse_handover") or legacy_reverse:
                state.current_owner = "Clean Boots"
                state.append_event(
                    event_type="reverse_handover",
                    title="Dirty Boots returned the case to Clean Boots",
                    detail=(
                        "The plant domain is restored, but customer service remains degraded. "
                        "The same incident and SLA clock continue into a Clean Boots reassessment."
                    ),
                    severity=Severity.WARNING,
                )
        action_plans = list(
            state.scenario_context.get("action_by_cycle")
            or state.scenario_context.get("action_sequence")
            or []
        )
        # max_remote_attempts was declared in Settings, defaulted to 2, set in the
        # test fixtures, and never read by any code. Field visits and MR attempts
        # were enforced here; remote retries were bounded only by the global
        # graph_max_steps, so a scenario could re-run a remote action far past its
        # configured ceiling. Found by the v1.13.2 audit.
        if state.remote_attempts >= self.settings.max_remote_attempts:
            return self._escalate(state, "Remote attempt budget exhausted")
        if state.field_visits >= self.settings.max_field_visits:
            return self._escalate(state, "Field visit budget exhausted")
        if state.mr_attempts >= self.settings.max_mr_attempts:
            return self._escalate(state, "MR attempt budget exhausted")
        if len(state.action_history) >= len(action_plans):
            return self._escalate(state, "All configured scenario actions failed")

        evidence = EvidenceItem(
            evidence_id=stable_id(state.incident_id, "failed_action", len(state.action_history), prefix="evi"),
            kind="failed_action",
            source="post-action verification",
            subject=state.incident_id,
            observed_at=utc_now(),
            value={"action": last.action_type.value if last else "unknown"},
            quality=1.0,
            summary="The previous action did not produce stable restoration; RCA must be repeated.",
        )
        if all(item.evidence_id != evidence.evidence_id for item in state.evidence):
            state.add_evidence(evidence)
        state.new_evidence_since_last_rca = True
        state.stage = Stage.EVIDENCE
        state.append_event(
            event_type="return_to_rca",
            title="Returned to RCA",
            detail="The failed attempt was recorded and new evidence was added before selecting another action.",
        )
        return state

    def _reconcile(self, state: IncidentState) -> IncidentState:
        state.stage = Stage.CLOSED
        state.status = CaseStatus.CLOSED
        state.active_quarantine_id = None
        state.current_owner = "Closed"
        state.append_event(
            event_type="linked_records_closed",
            title="Incident closed",
            detail=(
                "NXT alarm, incident, work orders and jTrack MR were reconciled after stable validation."
            ),
        )
        return state

    def _prepare_approval(
        self,
        state: IncidentState,
        *,
        kind: ApprovalKind,
        action_type: str,
        requested_role: str,
        proposal: dict[str, Any],
    ) -> IncidentState:
        if action_type == "rca_review":
            attempt = max(state.diagnostic_cycles - 1, 0)
            delimiter_id = None
        else:
            try:
                action_enum = ActionType(action_type)
            except ValueError:
                attempt = len(state.action_history)
            else:
                attempt = self._attempt_for(state, action_enum)
            delimiter_id = (
                state.delimiter or self._default_delimiter(state)
                if action_type
                in {
                    ActionType.CLEAN_BOOTS.value,
                    ActionType.DIRTY_BOOTS_MR.value,
                    ActionType.JOINT_DISPATCH.value,
                    ActionType.PLANT_ACTION.value,
                }
                else None
            )
        approval_id = derive_approval_id(
            incident_id=state.incident_id,
            approval_kind=kind.value,
            action_type=action_type,
            attempt_index=attempt,
            delimiter_id=delimiter_id,
        )
        idempotency_key = derive_action_key(
            incident_id=state.incident_id,
            action_type=action_type,
            attempt_index=attempt,
            delimiter_id=delimiter_id,
        )
        existing = self.repository.get_approval(approval_id)
        approval = existing or ApprovalRequest(
            approval_id=approval_id,
            incident_id=state.incident_id,
            action_type=action_type,
            kind=kind,
            requested_role=requested_role,
            proposal=proposal,
            idempotency_key=idempotency_key,
            created_at=utc_now(),
            expires_at=utc_now() + timedelta(hours=4),
        )
        self.repository.save_approval(approval)
        state.pending_approval_id = approval.approval_id
        state.approval_result = None
        state.stage = Stage.WAITING_APPROVAL
        state.status = CaseStatus.WAITING
        state.append_event(
            event_type="approval_requested",
            title=f"{kind.value.replace('_', ' ').title()} approval required",
            detail=f"Waiting for role {requested_role}; approval {approval.approval_id}.",
            severity=Severity.WARNING,
            metadata={"approval_id": approval.approval_id, "kind": kind.value},
        )
        return state

    def _escalate(self, state: IncidentState, reason: str) -> IncidentState:
        state.stage = Stage.ESCALATED
        state.status = CaseStatus.ESCALATED
        state.current_owner = "L2/SME"
        state.gate_reason = "budget" if "budget" in reason.lower() else state.gate_reason
        state.last_error = reason
        state.append_event(
            event_type="escalated",
            title="Case escalated",
            detail=reason,
            severity=Severity.CRITICAL,
        )
        return state

    def _candidate_from_fixture(
        self,
        raw: dict[str, Any],
        *,
        rank: int,
        state: IncidentState,
    ) -> ActionCandidate:
        aliases = {
            "clean_boots_dispatch": ActionType.CLEAN_BOOTS.value,
            "create_mr": ActionType.DIRTY_BOOTS_MR.value,
            "plant_remediation": ActionType.PLANT_ACTION.value,
        }
        raw_action = str(raw["action_type"])
        action_type = ActionType(aliases.get(raw_action, raw_action))
        label_map = {
            ActionType.REMOTE_REPROVISION: "Remote reprovision",
            ActionType.REMOTE_REBOOT: "Remote reboot",
            ActionType.SELF_HELP: "Guided self-help",
            ActionType.CLEAN_BOOTS: "Clean Boots dispatch",
            ActionType.DIRTY_BOOTS_MR: "Dirty Boots / jTrack MR",
            ActionType.JOINT_DISPATCH: "Joint Clean/Dirty dispatch",
            ActionType.PLANT_ACTION: "Network / plant action",
            ActionType.MANUAL_REVIEW: "L2 / SME review",
            ActionType.MONITOR: "Monitor",
        }
        return ActionCandidate(
            rank=rank,
            action_type=action_type,
            label=str(raw.get("label") or label_map[action_type]),
            expected_success=float(raw.get("expected_success", 0.5)),
            estimated_minutes=int(raw.get("estimated_minutes", 60)),
            cost_class=str(raw.get("cost_class", "medium")),
            risk_class=str(raw.get("risk_class", "medium")),
            required_evidence=list(raw.get("required_evidence") or [item.evidence_id for item in state.evidence[:3]]),
            success_test=list(raw.get("success_test") or ["NXT stability", "service test"]),
            failure_trigger=str(raw.get("failure_trigger") or "Return to RCA with new evidence."),
            rationale=str(raw.get("rationale") or "Fixture-backed deterministic action recommendation."),
        )

    def _candidate(self, action_type: ActionType, *, rank: int, state: IncidentState) -> ActionCandidate:
        catalog: dict[ActionType, tuple[str, float, int, str, str]] = {
            ActionType.REMOTE_REPROVISION: ("Remote reprovision", 0.82, 10, "low", "low"),
            ActionType.REMOTE_REBOOT: ("Remote reboot", 0.70, 8, "low", "low"),
            ActionType.SELF_HELP: ("Guided self-help", 0.65, 20, "low", "low"),
            ActionType.CLEAN_BOOTS: ("Clean Boots dispatch", 0.86, 360, "medium", "medium"),
            ActionType.DIRTY_BOOTS_MR: ("Dirty Boots / jTrack MR", 0.88, 720, "high", "medium"),
            ActionType.JOINT_DISPATCH: ("Joint Clean/Dirty dispatch", 0.91, 480, "high", "medium"),
            ActionType.PLANT_ACTION: ("Network / plant action", 0.92, 240, "high", "high"),
            ActionType.MANUAL_REVIEW: ("L2 / SME review", 0.50, 60, "medium", "low"),
            ActionType.MONITOR: ("Monitor", 0.40, 60, "low", "low"),
        }
        label, success, minutes, cost, risk = catalog[action_type]
        return ActionCandidate(
            rank=rank,
            action_type=action_type,
            label=label,
            expected_success=success,
            estimated_minutes=minutes,
            cost_class=cost,
            risk_class=risk,
            required_evidence=[item.evidence_id for item in state.evidence[:3]],
            success_test=["NXT stability", "service test", "customer confirmation if needed"],
            failure_trigger="Return to RCA with new evidence; do not repeat blindly.",
            rationale=f"Recommended for approved domain {(state.approved_rca or state.deterministic_rca).recommended_domain.value if (state.approved_rca or state.deterministic_rca) else 'unknown'}.",
        )

    @staticmethod
    def _approval_for_action(action_type: ActionType) -> tuple[ApprovalKind, str]:
        if action_type in {ActionType.REMOTE_REBOOT, ActionType.REMOTE_REPROVISION, ActionType.SELF_HELP}:
            return ApprovalKind.REMOTE_ACTION, "noc_analyst"
        if action_type in {ActionType.CLEAN_BOOTS, ActionType.JOINT_DISPATCH}:
            return ApprovalKind.DISPATCH, "dispatcher"
        if action_type == ActionType.DIRTY_BOOTS_MR:
            return ApprovalKind.HANDOVER, "plant_supervisor"
        if action_type == ActionType.PLANT_ACTION:
            return ApprovalKind.HIGH_BLAST_RADIUS, "operations_supervisor"
        return ApprovalKind.RCA_REVIEW, "l2_sme"

    @staticmethod
    def _tool_for_action(action_type: ActionType) -> str:
        if action_type in {ActionType.REMOTE_REBOOT, ActionType.REMOTE_REPROVISION}:
            return "simulate_remote_action"
        if action_type == ActionType.SELF_HELP:
            return "simulate_self_help"
        if action_type == ActionType.CLEAN_BOOTS:
            return "create_clean_boots_work_order"
        if action_type == ActionType.DIRTY_BOOTS_MR:
            return "create_or_update_mr"
        if action_type == ActionType.JOINT_DISPATCH:
            return "simulate_joint_dispatch"
        if action_type == ActionType.PLANT_ACTION:
            return "simulate_plant_action"
        raise WorkflowError(f"No MCP tool for action {action_type.value}")

    @staticmethod
    def _attempt_for(state: IncidentState, action_type: ActionType) -> int:
        if action_type in {ActionType.REMOTE_REBOOT, ActionType.REMOTE_REPROVISION}:
            return state.remote_attempts + 1
        if action_type == ActionType.SELF_HELP:
            return state.self_help_attempts + 1
        if action_type in {ActionType.CLEAN_BOOTS, ActionType.JOINT_DISPATCH}:
            return state.field_visits + 1
        if action_type == ActionType.DIRTY_BOOTS_MR:
            return state.mr_attempts + 1
        return len(state.action_history) + 1

    @staticmethod
    def _increment_attempt(state: IncidentState, action_type: ActionType) -> None:
        if action_type in {ActionType.REMOTE_REBOOT, ActionType.REMOTE_REPROVISION}:
            state.remote_attempts += 1
        elif action_type == ActionType.SELF_HELP:
            state.self_help_attempts += 1
        elif action_type in {ActionType.CLEAN_BOOTS, ActionType.JOINT_DISPATCH}:
            state.field_visits += 1
        elif action_type == ActionType.DIRTY_BOOTS_MR:
            state.mr_attempts += 1

    @staticmethod
    def _default_delimiter(state: IncidentState) -> str:
        if state.technology.value == "HFC":
            return str(state.topology.get("tap", "unknown-tap"))
        return str(state.topology.get("odp", "unknown-odp"))


def build_approval_token(
    *,
    approval: ApprovalRequest,
    settings: Settings,
) -> str:
    claims = {
        "approval_id": approval.approval_id,
        "incident_id": approval.incident_id,
        "action_type": approval.action_type,
        "idempotency_key": approval.idempotency_key,
        "status": "approved",
        "exp": (datetime.now(UTC) + timedelta(minutes=30)).timestamp(),
    }
    return create_approval_token(claims, settings.mcp_approval_signing_secret)
