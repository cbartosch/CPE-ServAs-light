from __future__ import annotations

from lpr_cpe_demo.domain import (
    ApprovalDecisionInput,
    ApprovalKind,
    ApprovalStatus,
    CaseStatus,
    Stage,
)
from lpr_cpe_demo.workflow.service import WorkflowService

from .conftest import approve_until_terminal


def test_remote_success_closes_without_field_visit(service: WorkflowService) -> None:
    state = service.start_scenario("hfc_remote_success")
    state = approve_until_terminal(service, state)

    assert state.status == CaseStatus.CLOSED
    assert state.remote_attempts == 1
    assert state.field_visits == 0
    assert state.mr_attempts == 0
    assert state.verification_passed is True
    assert [item.action_type.value for item in state.action_history] == ["remote_reprovision"]


def test_high_confidence_domain_disagreement_forces_human_rca(service: WorkflowService) -> None:
    state = service.start_scenario("rca_disagreement_gate")
    approval = service.list_approvals(
        status=ApprovalStatus.PENDING,
        incident_id=state.incident_id,
    )[0]

    assert state.stage == Stage.WAITING_APPROVAL
    assert state.domain_agreement == "disagree"
    assert state.gate_reason == "domain_disagreement"
    assert approval.kind == ApprovalKind.RCA_REVIEW
    assert approval.proposal["gate_reason"] == "domain_disagreement"


def test_remote_failure_returns_to_rca_then_clean_boots_closes(service: WorkflowService) -> None:
    state = service.start_scenario("hfc_remote_fail_clean_success")
    state = approve_until_terminal(service, state)

    assert state.status == CaseStatus.CLOSED
    assert state.remote_attempts == 1
    assert state.field_visits == 1
    assert state.diagnostic_cycles >= 2
    assert [item.action_type.value for item in state.action_history] == [
        "remote_reprovision",
        "clean_boots",
    ]
    assert any(item.event_type == "return_to_rca" for item in state.timeline)


def test_pon_odp_handover_creates_one_mr_and_keeps_one_incident(service: WorkflowService) -> None:
    state = service.start_scenario("pon_odp_handover")
    original_id = state.incident_id
    original_sla = state.sla_deadline
    state = approve_until_terminal(service, state)

    assert state.status == CaseStatus.CLOSED
    assert state.incident_id == original_id
    assert state.sla_deadline == original_sla
    assert state.delimiter == "ODP-UTU-04-02"
    assert state.field_visits == 1
    assert state.mr_attempts == 1
    assert len(state.mr_records) == 1
    assert state.mr_records[0]["mr_id"].startswith("mr-")


def test_reverse_handover_returns_to_clean_boots_on_same_case(service: WorkflowService) -> None:
    state = service.start_scenario("pon_reverse_handover")
    incident_id = state.incident_id
    state = approve_until_terminal(service, state)

    assert state.status == CaseStatus.CLOSED
    assert state.incident_id == incident_id
    assert [item.action_type.value for item in state.action_history] == [
        "dirty_boots_mr",
        "clean_boots",
    ]
    assert state.mr_attempts == 1
    assert state.field_visits == 1
    assert state.diagnostic_cycles >= 2


def test_bounded_remote_failures_escalate_instead_of_looping(service: WorkflowService) -> None:
    state = service.start_scenario("bounded_remote_failure")
    state = approve_until_terminal(service, state)

    assert state.status == CaseStatus.ESCALATED
    assert state.stage == Stage.ESCALATED
    assert state.remote_attempts == 2
    assert len(state.action_history) == 2
    assert "exhausted" in (state.last_error or "").lower() or "failed" in (state.last_error or "").lower()


def test_common_cause_inherits_parent_sla_authority(service: WorkflowService) -> None:
    state = service.start_scenario("hfc_common_cause")

    assert state.parent_incident_id == "PARENT-HFC-NODE-17"
    assert state.sla_mode == "inherits_parent"
    assert state.parent_sla_deadline is not None
    assert state.effective_sla_deadline == state.parent_sla_deadline
    assert state.sla_authority == "parent PARENT-HFC-NODE-17"
    assert state.current_owner == "Plant/NOC"

    state = approve_until_terminal(service, state)
    assert state.status == CaseStatus.CLOSED
    assert state.field_visits == 0


def test_action_override_requires_fresh_policy_and_approval(service: WorkflowService) -> None:
    state = service.start_scenario("hfc_remote_fail_clean_success")
    first = service.list_approvals(
        status=ApprovalStatus.PENDING, incident_id=state.incident_id
    )[0]
    assert first.action_type == "remote_reprovision"

    state = service.decide_approval(
        first.approval_id,
        ApprovalDecisionInput(
            decision="override",
            actor="operations.supervisor",
            role="operations_supervisor",
            reason="Choose the reviewed Clean Boots alternative.",
            selected_option="clean_boots",
        ),
    )

    assert state.stage == Stage.WAITING_APPROVAL
    assert state.action_history == []
    refreshed = service.list_approvals(
        status=ApprovalStatus.PENDING, incident_id=state.incident_id
    )
    assert len(refreshed) == 1
    assert refreshed[0].action_type == "clean_boots"
    assert refreshed[0].approval_id != first.approval_id
    assert service.repository.get_approval(first.approval_id).status == ApprovalStatus.CONSUMED


def test_failed_plant_action_returns_to_rca_and_updates_same_mr(
    service: WorkflowService,
) -> None:
    state = service.start_scenario("hfc_failed_plant_action_rerca")
    incident_id = state.incident_id
    original_sla = state.sla_deadline
    state = approve_until_terminal(service, state)

    assert state.status == CaseStatus.CLOSED
    assert state.incident_id == incident_id
    assert state.sla_deadline == original_sla
    assert state.mr_attempts == 2
    assert [item.action_type.value for item in state.action_history] == [
        "dirty_boots_mr",
        "dirty_boots_mr",
    ]
    assert len(state.mr_records) == 2
    assert len({item["mr_id"] for item in state.mr_records}) == 1
    assert [item["outcome"] for item in state.mr_records] == ["failed", "succeeded"]
    assert any(item.event_type == "return_to_rca" for item in state.timeline)
