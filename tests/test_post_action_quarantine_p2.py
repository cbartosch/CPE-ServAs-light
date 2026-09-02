from __future__ import annotations

from datetime import timedelta

from lpr_cpe_demo.domain import (
    ApprovalDecisionInput,
    ApprovalStatus,
    CaseStatus,
    Stage,
)
from lpr_cpe_demo.quarantine import (
    QuarantineHealth,
    QuarantineObservationRequest,
    QuarantineStatus,
    QuarantineTransition,
)
from lpr_cpe_demo.workflow.service import WorkflowService


def _p2_service(settings) -> WorkflowService:
    configured = settings.model_copy(
        update={
            "post_action_quarantine_enabled": True,
            "post_action_quarantine_scheduler_enabled": False,
            "post_action_quarantine_duration_seconds": 60,
            "post_action_quarantine_check_interval_seconds": 10,
            "post_action_quarantine_required_healthy_checks": 2,
            "post_action_quarantine_max_extensions": 1,
            "post_action_quarantine_lease_seconds": 30,
        }
    )
    service = WorkflowService(settings=configured)
    service.reset()
    return service


def _approve_to_quarantine(service: WorkflowService, scenario: str = "hfc_remote_success"):
    state = service.start_scenario(scenario)
    for _ in range(20):
        if state.stage == Stage.POST_ACTION_QUARANTINE:
            return state
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
                    actor="p2.test",
                    role=approval.requested_role,
                    reason="P2 test approval",
                ),
            )
        else:
            state = service.run_incident(state.incident_id)
    raise AssertionError("workflow did not enter post-action quarantine")


def test_successful_action_enters_quarantine_instead_of_closing(settings) -> None:
    service = _p2_service(settings)
    try:
        state = _approve_to_quarantine(service)
        assert state.status == CaseStatus.QUARANTINED
        assert state.stage == Stage.POST_ACTION_QUARANTINE
        assert state.active_quarantine_id
        assert service.list_quarantines()[0].status == QuarantineStatus.ACTIVE
        assert state.pre_action_health
        assert state.immediate_post_action_health["verdict"] == "healthy"
    finally:
        service.close()


def test_repeated_healthy_checks_release_and_close(settings) -> None:
    service = _p2_service(settings)
    try:
        _approve_to_quarantine(service)
        quarantine = service.list_quarantines()[0]
        first_time = quarantine.started_at + timedelta(seconds=10)
        first = service.record_quarantine_observation(
            quarantine.quarantine_id,
            QuarantineObservationRequest(
                health=QuarantineHealth.HEALTHY,
                observed_at=first_time,
                idempotency_key="healthy-1",
            ),
        )
        assert first["observation"]["transition"] == QuarantineTransition.CONTINUE.value
        assert first["incident"]["stage"] == Stage.POST_ACTION_QUARANTINE.value

        release_time = quarantine.minimum_release_at + timedelta(seconds=1)
        second = service.record_quarantine_observation(
            quarantine.quarantine_id,
            QuarantineObservationRequest(
                health=QuarantineHealth.HEALTHY,
                observed_at=release_time,
                idempotency_key="healthy-2",
            ),
        )
        assert second["observation"]["transition"] == QuarantineTransition.RELEASE.value
        assert second["incident"]["status"] == CaseStatus.CLOSED.value
        assert second["incident"]["stage"] == Stage.CLOSED.value
        saved = service.repository.get_quarantine(quarantine.quarantine_id)
        assert saved is not None
        assert saved.status == QuarantineStatus.RELEASED
    finally:
        service.close()


def test_degraded_quarantine_reopens_same_incident(settings) -> None:
    service = _p2_service(settings)
    try:
        state = _approve_to_quarantine(service)
        quarantine = service.list_quarantines()[0]
        result = service.record_quarantine_observation(
            quarantine.quarantine_id,
            QuarantineObservationRequest(
                health=QuarantineHealth.DEGRADED,
                idempotency_key="degraded-1",
            ),
        )
        assert result["observation"]["transition"] == QuarantineTransition.REOPEN.value
        assert result["incident"]["incident_id"] == state.incident_id
        assert result["incident"]["stage"] == Stage.FAILURE_REVIEW.value
        assert result["incident"]["status"] == CaseStatus.OPEN.value
    finally:
        service.close()


def test_unknown_health_extends_then_escalates(settings) -> None:
    service = _p2_service(settings)
    try:
        _approve_to_quarantine(service)
        quarantine = service.list_quarantines()[0]
        first = service.record_quarantine_observation(
            quarantine.quarantine_id,
            QuarantineObservationRequest(
                health=QuarantineHealth.UNKNOWN,
                idempotency_key="unknown-1",
            ),
        )
        assert first["observation"]["transition"] == QuarantineTransition.EXTEND.value

        second = service.record_quarantine_observation(
            quarantine.quarantine_id,
            QuarantineObservationRequest(
                health=QuarantineHealth.UNKNOWN,
                idempotency_key="unknown-2",
            ),
        )
        assert second["observation"]["transition"] == QuarantineTransition.ESCALATE.value
        assert second["incident"]["status"] == CaseStatus.ESCALATED.value
    finally:
        service.close()


def test_observation_idempotency_does_not_double_count(settings) -> None:
    service = _p2_service(settings)
    try:
        _approve_to_quarantine(service)
        quarantine = service.list_quarantines()[0]
        request = QuarantineObservationRequest(
            health=QuarantineHealth.HEALTHY,
            idempotency_key="same-observation",
        )
        first = service.record_quarantine_observation(quarantine.quarantine_id, request)
        second = service.record_quarantine_observation(quarantine.quarantine_id, request)
        assert first["created"] is True
        assert second["created"] is False
        assert len(service.repository.list_quarantine_observations(quarantine.quarantine_id)) == 1
    finally:
        service.close()


def test_quarantine_api_exposes_policy_and_observations(settings) -> None:
    from fastapi.testclient import TestClient

    from lpr_cpe_demo.api.main import create_app

    service = _p2_service(settings)
    state = _approve_to_quarantine(service)
    quarantine_id = state.active_quarantine_id
    assert quarantine_id
    app = create_app(settings=service.settings, service=service)
    with TestClient(app) as client:
        policy = client.get("/api/assurance/quarantine-policy")
        assert policy.status_code == 200
        assert policy.json()["enabled"] is True

        listing = client.get("/api/assurance/quarantines")
        assert listing.status_code == 200
        assert listing.json()[0]["quarantine_id"] == quarantine_id

        response = client.post(
            f"/api/assurance/quarantines/{quarantine_id}/observations",
            json={
                "health": "healthy",
                "source": "test",
                "actor": "test.operator",
                "idempotency_key": "api-health-1",
                "metrics": {"packet_loss_pct": 0.0},
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["observation"]["health"] == "healthy"


def test_due_job_claim_is_persistent_and_processes_one_check(settings) -> None:
    service = _p2_service(settings)
    try:
        _approve_to_quarantine(service)
        quarantine = service.list_quarantines()[0]
        due = quarantine.started_at + timedelta(seconds=20)
        quarantine.next_check_at = due
        service.repository.save_quarantine(quarantine)

        results = service.run_due_quarantine_jobs(
            now=due,
            worker_id="p2.scheduler.test",
        )
        assert len(results) == 1
        assert results[0]["observation"]["source"] == "scheduled_health_check"
        assert len(
            service.repository.list_quarantine_observations(
                quarantine.quarantine_id
            )
        ) == 1
    finally:
        service.close()
