from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.engine import make_url

from lpr_cpe_demo.domain import (
    ApprovalDecisionInput,
    ApprovalStatus,
    CaseStatus,
    Stage,
    utc_now,
)
from lpr_cpe_demo.quarantine import (
    QuarantineHealth,
    QuarantineLeaseError,
    QuarantineObservationConflictError,
    QuarantineObservationRequest,
    QuarantineObservationTimeError,
    QuarantineObservationTooEarlyError,
    QuarantineStatus,
    QuarantineTerminalStateError,
    QuarantineTransition,
    as_utc,
)
from lpr_cpe_demo.workflow.service import WorkflowService

ACTOR = "p2.test"
SOURCE = "p2-test-adapter"


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
            "post_action_quarantine_max_measurement_clock_skew_seconds": 300,
        }
    )
    service = WorkflowService(settings=configured)
    service.reset()
    return service


def _approve_to_quarantine(
    service: WorkflowService,
    scenario: str = "hfc_remote_success",
):
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
                    actor=ACTOR,
                    role=approval.requested_role,
                    reason="P2 test approval",
                ),
            )
        else:
            state = service.run_incident(state.incident_id)
    raise AssertionError("workflow did not enter post-action quarantine")


def _record(
    service: WorkflowService,
    quarantine_id: str,
    request: QuarantineObservationRequest,
    *,
    received_at,
    lease_owner: str | None = None,
    lease_token: str | None = None,
):
    return service.record_quarantine_observation(
        quarantine_id,
        request,
        actor=ACTOR if lease_owner is None else lease_owner,
        source=SOURCE if lease_owner is None else "scheduled_health_check",
        received_at=received_at,
        lease_owner=lease_owner,
        lease_token=lease_token,
    )


def _healthy_request(key: str, at) -> QuarantineObservationRequest:
    return QuarantineObservationRequest(
        health=QuarantineHealth.HEALTHY,
        observed_at=at,
        idempotency_key=key,
    )


def _release_quarantine(service: WorkflowService, quarantine_id: str):
    quarantine = service.repository.get_quarantine(quarantine_id)
    assert quarantine is not None
    first_at = as_utc(quarantine.next_check_at)
    _record(
        service,
        quarantine_id,
        _healthy_request("healthy-1", first_at),
        received_at=first_at,
    )
    quarantine = service.repository.get_quarantine(quarantine_id)
    assert quarantine is not None
    second_at = max(
        as_utc(quarantine.next_check_at),
        as_utc(quarantine.minimum_release_at) + timedelta(seconds=1),
    )
    return _record(
        service,
        quarantine_id,
        _healthy_request("healthy-2", second_at),
        received_at=second_at,
    )


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


def test_repeated_server_timed_healthy_checks_release_and_close(settings) -> None:
    service = _p2_service(settings)
    try:
        state = _approve_to_quarantine(service)
        final = _release_quarantine(service, state.active_quarantine_id)
        assert final["observation"]["transition"] == QuarantineTransition.RELEASE.value
        assert final["incident"]["status"] == CaseStatus.CLOSED.value
        assert final["incident"]["stage"] == Stage.CLOSED.value
        saved = service.repository.get_quarantine(state.active_quarantine_id)
        assert saved is not None
        assert saved.status == QuarantineStatus.RELEASED
        assert final["observation"]["received_at"] == final["quarantine"]["completed_at"]
    finally:
        service.close()


def test_degraded_quarantine_reopens_same_incident_immediately(settings) -> None:
    service = _p2_service(settings)
    try:
        state = _approve_to_quarantine(service)
        quarantine = service.list_quarantines()[0]
        received_at = as_utc(quarantine.started_at) + timedelta(seconds=1)
        result = _record(
            service,
            quarantine.quarantine_id,
            QuarantineObservationRequest(
                health=QuarantineHealth.DEGRADED,
                observed_at=received_at,
                idempotency_key="degraded-1",
            ),
            received_at=received_at,
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
        state = _approve_to_quarantine(service)
        quarantine = service.repository.get_quarantine(state.active_quarantine_id)
        assert quarantine is not None
        first_at = as_utc(quarantine.next_check_at)
        first = _record(
            service,
            quarantine.quarantine_id,
            QuarantineObservationRequest(
                health=QuarantineHealth.UNKNOWN,
                observed_at=first_at,
                idempotency_key="unknown-1",
            ),
            received_at=first_at,
        )
        assert first["observation"]["transition"] == QuarantineTransition.EXTEND.value

        quarantine = service.repository.get_quarantine(quarantine.quarantine_id)
        assert quarantine is not None
        second_at = as_utc(quarantine.next_check_at)
        second = _record(
            service,
            quarantine.quarantine_id,
            QuarantineObservationRequest(
                health=QuarantineHealth.UNKNOWN,
                observed_at=second_at,
                idempotency_key="unknown-2",
            ),
            received_at=second_at,
        )
        assert second["observation"]["transition"] == QuarantineTransition.ESCALATE.value
        assert second["incident"]["status"] == CaseStatus.ESCALATED.value
    finally:
        service.close()


def test_observation_idempotency_does_not_double_count(settings) -> None:
    service = _p2_service(settings)
    try:
        state = _approve_to_quarantine(service)
        quarantine = service.repository.get_quarantine(state.active_quarantine_id)
        assert quarantine is not None
        received_at = as_utc(quarantine.next_check_at)
        request = _healthy_request("same-observation", received_at)
        first = _record(
            service,
            quarantine.quarantine_id,
            request,
            received_at=received_at,
        )
        second = _record(
            service,
            quarantine.quarantine_id,
            request,
            received_at=received_at + timedelta(seconds=1),
        )
        assert first["created"] is True
        assert second["created"] is False
        assert len(
            service.repository.list_quarantine_observations(quarantine.quarantine_id)
        ) == 1
        assert service.repository.get_quarantine(quarantine.quarantine_id).healthy_checks == 1
    finally:
        service.close()


def test_changed_payload_under_same_scoped_key_is_rejected(settings) -> None:
    service = _p2_service(settings)
    try:
        state = _approve_to_quarantine(service)
        quarantine = service.repository.get_quarantine(state.active_quarantine_id)
        assert quarantine is not None
        received_at = as_utc(quarantine.next_check_at)
        _record(
            service,
            quarantine.quarantine_id,
            _healthy_request("same-key", received_at),
            received_at=received_at,
        )
        with pytest.raises(
            QuarantineObservationConflictError,
            match="IDEMPOTENCY_PAYLOAD_CONFLICT",
        ):
            _record(
                service,
                quarantine.quarantine_id,
                QuarantineObservationRequest(
                    health=QuarantineHealth.UNKNOWN,
                    observed_at=received_at,
                    idempotency_key="same-key",
                ),
                received_at=received_at + timedelta(seconds=10),
            )
    finally:
        service.close()


def test_same_idempotency_key_is_independent_across_quarantines(settings) -> None:
    service = _p2_service(settings)
    try:
        first_state = _approve_to_quarantine(service)
        second_state = _approve_to_quarantine(service, "hfc_self_help_success")
        first = service.repository.get_quarantine(first_state.active_quarantine_id)
        second = service.repository.get_quarantine(second_state.active_quarantine_id)
        assert first is not None and second is not None
        for quarantine in (first, second):
            received_at = as_utc(quarantine.started_at) + timedelta(seconds=1)
            result = _record(
                service,
                quarantine.quarantine_id,
                QuarantineObservationRequest(
                    health=QuarantineHealth.DEGRADED,
                    observed_at=received_at,
                    idempotency_key="shared-resource-local-key",
                ),
                received_at=received_at,
            )
            assert result["created"] is True
        assert len(service.repository.list_quarantine_observations(first.quarantine_id)) == 1
        assert len(service.repository.list_quarantine_observations(second.quarantine_id)) == 1
    finally:
        service.close()


def test_terminal_quarantine_rejects_new_key_but_allows_exact_replay(settings) -> None:
    service = _p2_service(settings)
    try:
        state = _approve_to_quarantine(service)
        final = _release_quarantine(service, state.active_quarantine_id)
        release_at = final["observation"]["observed_at"]
        replay = _record(
            service,
            state.active_quarantine_id,
            _healthy_request("healthy-2", release_at),
            received_at=as_utc(utc_now()),
        )
        assert replay["created"] is False
        with pytest.raises(QuarantineTerminalStateError, match="QUARANTINE_TERMINAL"):
            _record(
                service,
                state.active_quarantine_id,
                QuarantineObservationRequest(
                    health=QuarantineHealth.DEGRADED,
                    observed_at=as_utc(utc_now()),
                    idempotency_key="late-degraded",
                ),
                received_at=as_utc(utc_now()),
            )
        incident = service.get_incident(state.incident_id)
        assert incident.stage == Stage.CLOSED
        assert incident.status == CaseStatus.CLOSED
        assert incident.active_quarantine_id is None
    finally:
        service.close()


def test_future_measurement_cannot_bypass_server_release_time(settings) -> None:
    service = _p2_service(settings)
    try:
        state = _approve_to_quarantine(service)
        quarantine = service.repository.get_quarantine(state.active_quarantine_id)
        assert quarantine is not None
        receipt_time = as_utc(quarantine.next_check_at)
        future_measurement = as_utc(quarantine.minimum_release_at) + timedelta(seconds=1)
        result = _record(
            service,
            quarantine.quarantine_id,
            _healthy_request("future-measurement", future_measurement),
            received_at=receipt_time,
        )
        assert result["observation"]["transition"] == QuarantineTransition.CONTINUE.value
        assert result["quarantine"]["status"] == QuarantineStatus.ACTIVE.value
        with pytest.raises(
            QuarantineObservationTooEarlyError,
            match="OBSERVATION_TOO_EARLY",
        ):
            _record(
                service,
                quarantine.quarantine_id,
                _healthy_request(
                    "immediate-second",
                    future_measurement + timedelta(seconds=1),
                ),
                received_at=receipt_time + timedelta(seconds=1),
            )
    finally:
        service.close()


def test_external_measurement_clock_skew_is_bounded(settings) -> None:
    service = _p2_service(settings)
    try:
        state = _approve_to_quarantine(service)
        quarantine = service.repository.get_quarantine(state.active_quarantine_id)
        assert quarantine is not None
        received_at = as_utc(quarantine.next_check_at)
        with pytest.raises(
            QuarantineObservationTimeError,
            match="MEASUREMENT_CLOCK_SKEW",
        ):
            _record(
                service,
                quarantine.quarantine_id,
                _healthy_request(
                    "far-future",
                    received_at + timedelta(seconds=301),
                ),
                received_at=received_at,
            )
    finally:
        service.close()


def test_complete_observation_transition_rolls_back_on_interruption(
    settings,
    monkeypatch,
) -> None:
    service = _p2_service(settings)
    try:
        state = _approve_to_quarantine(service)
        quarantine = service.repository.get_quarantine(state.active_quarantine_id)
        assert quarantine is not None
        episode_before = service.repository.get_assurance_episode(quarantine.episode_id)
        events_before = service.repository.list_assurance_events(quarantine.episode_id)
        received_at = as_utc(quarantine.started_at) + timedelta(seconds=1)

        def fail_before_commit(_session, _mutation):
            raise RuntimeError("injected P2 transaction interruption")

        monkeypatch.setattr(
            service.repository,
            "_before_quarantine_commit",
            fail_before_commit,
        )
        with pytest.raises(RuntimeError, match="P2 transaction interruption"):
            _record(
                service,
                quarantine.quarantine_id,
                QuarantineObservationRequest(
                    health=QuarantineHealth.DEGRADED,
                    observed_at=received_at,
                    idempotency_key="rollback-observation",
                ),
                received_at=received_at,
            )

        stored = service.repository.get_quarantine(quarantine.quarantine_id)
        assert stored is not None
        assert stored.status == QuarantineStatus.ACTIVE
        assert stored.version == quarantine.version
        assert service.repository.list_quarantine_observations(quarantine.quarantine_id) == []
        incident = service.get_incident(state.incident_id)
        assert incident.stage == Stage.POST_ACTION_QUARANTINE
        assert incident.status == CaseStatus.QUARANTINED
        assert service.repository.get_assurance_episode(quarantine.episode_id) == episode_before
        assert service.repository.list_assurance_events(quarantine.episode_id) == events_before

        monkeypatch.undo()
        retry = _record(
            service,
            quarantine.quarantine_id,
            QuarantineObservationRequest(
                health=QuarantineHealth.DEGRADED,
                observed_at=received_at,
                idempotency_key="rollback-observation",
            ),
            received_at=received_at,
        )
        assert retry["created"] is True
        assert retry["incident"]["stage"] == Stage.FAILURE_REVIEW.value
    finally:
        service.close()


def test_parallel_same_key_converges_without_integrity_errors(settings) -> None:
    service = _p2_service(settings)
    try:
        state = _approve_to_quarantine(service)
        quarantine = service.repository.get_quarantine(state.active_quarantine_id)
        assert quarantine is not None
        workers = 32
        barrier = threading.Barrier(workers)
        received_at = as_utc(quarantine.started_at) + timedelta(seconds=1)
        request = QuarantineObservationRequest(
            health=QuarantineHealth.DEGRADED,
            observed_at=received_at,
            idempotency_key="parallel-same-key",
        )

        def invoke():
            barrier.wait(timeout=10)
            return _record(
                service,
                quarantine.quarantine_id,
                request,
                received_at=received_at,
            )

        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = [future.result() for future in [pool.submit(invoke) for _ in range(workers)]]

        assert sum(result["created"] for result in results) == 1
        assert len(
            service.repository.list_quarantine_observations(quarantine.quarantine_id)
        ) == 1
        assert service.repository.get_quarantine(quarantine.quarantine_id).status == (
            QuarantineStatus.REOPENED
        )
    finally:
        service.close()


def test_concurrent_distinct_checks_are_serialized_without_lost_count(
    settings,
    monkeypatch,
) -> None:
    service = _p2_service(settings)
    try:
        state = _approve_to_quarantine(service)
        quarantine = service.repository.get_quarantine(state.active_quarantine_id)
        assert quarantine is not None
        first_at = as_utc(quarantine.next_check_at)
        second_at = first_at + timedelta(seconds=quarantine.check_interval_seconds)
        entered = threading.Event()
        release = threading.Event()
        original = service._validate_quarantine_observation

        def blocked_validate(quarantine, request, **kwargs):
            if request.idempotency_key == "serialized-1":
                entered.set()
                assert release.wait(timeout=10)
            return original(quarantine, request, **kwargs)

        monkeypatch.setattr(service, "_validate_quarantine_observation", blocked_validate)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(
                _record,
                service,
                quarantine.quarantine_id,
                _healthy_request("serialized-1", first_at),
                received_at=first_at,
            )
            assert entered.wait(timeout=10)
            second = pool.submit(
                _record,
                service,
                quarantine.quarantine_id,
                _healthy_request("serialized-2", second_at),
                received_at=second_at,
            )
            release.set()
            first.result(timeout=10)
            second.result(timeout=10)

        stored = service.repository.get_quarantine(quarantine.quarantine_id)
        assert stored is not None
        assert stored.healthy_checks == 2
        assert len(service.repository.list_quarantine_observations(stored.quarantine_id)) == 2
    finally:
        service.close()


def test_scheduler_lease_token_rejects_stale_owner_and_supports_takeover(settings) -> None:
    service = _p2_service(settings)
    try:
        state = _approve_to_quarantine(service)
        quarantine = service.repository.get_quarantine(state.active_quarantine_id)
        assert quarantine is not None
        due = as_utc(quarantine.next_check_at)
        first_claim = service.repository.claim_due_quarantines(
            now=due,
            worker_id="worker-a",
            lease_seconds=30,
            limit=1,
        )
        assert len(first_claim) == 1
        assert first_claim[0].lease_token
        assert service.repository.claim_due_quarantines(
            now=due + timedelta(seconds=1),
            worker_id="worker-b",
            lease_seconds=30,
            limit=1,
        ) == []

        takeover_time = due + timedelta(seconds=31)
        second_claim = service.repository.claim_due_quarantines(
            now=takeover_time,
            worker_id="worker-b",
            lease_seconds=30,
            limit=1,
        )
        assert len(second_claim) == 1
        assert second_claim[0].lease_token != first_claim[0].lease_token

        stale_request = _healthy_request("lease-slot", takeover_time)
        with pytest.raises(QuarantineLeaseError, match="LEASE_LOST"):
            service.record_quarantine_observation(
                quarantine.quarantine_id,
                stale_request,
                actor="worker-a",
                source="scheduled_health_check",
                received_at=takeover_time,
                lease_owner="worker-a",
                lease_token=first_claim[0].lease_token,
            )
        accepted = service.record_quarantine_observation(
            quarantine.quarantine_id,
            stale_request,
            actor="worker-b",
            source="scheduled_health_check",
            received_at=takeover_time,
            lease_owner="worker-b",
            lease_token=second_claim[0].lease_token,
        )
        assert accepted["created"] is True
        assert accepted["observation"]["lease_token"] == second_claim[0].lease_token
    finally:
        service.close()


def test_quarantine_api_requires_token_and_derives_identity(settings) -> None:
    from fastapi.testclient import TestClient

    from lpr_cpe_demo.api.main import create_app

    service = _p2_service(settings)
    state = _approve_to_quarantine(service)
    quarantine_id = state.active_quarantine_id
    assert quarantine_id
    quarantine = service.repository.get_quarantine(quarantine_id)
    assert quarantine is not None
    quarantine.next_check_at = as_utc(utc_now()) - timedelta(seconds=1)
    service.repository.save_quarantine(quarantine)
    app = create_app(settings=service.settings, service=service)
    headers = {"X-LPR-Internal-Token": service.settings.workflow_internal_token}
    with TestClient(app) as client:
        policy = client.get("/api/assurance/quarantine-policy")
        assert policy.status_code == 200
        assert policy.json()["enabled"] is True

        unauthenticated = client.post(
            f"/api/assurance/quarantines/{quarantine_id}/observations",
            json={"health": "healthy", "idempotency_key": "unauthenticated"},
        )
        assert unauthenticated.status_code == 401

        forged_identity = client.post(
            f"/api/assurance/quarantines/{quarantine_id}/observations",
            headers=headers,
            json={
                "health": "healthy",
                "source": "forged",
                "actor": "forged",
                "idempotency_key": "forged-identity",
            },
        )
        assert forged_identity.status_code == 422

        response = client.post(
            f"/api/assurance/quarantines/{quarantine_id}/observations",
            headers=headers,
            json={
                "health": "healthy",
                "idempotency_key": "api-health-1",
                "metrics": {"packet_loss_pct": 0.0},
            },
        )
        assert response.status_code == 200, response.text
        observation = response.json()["observation"]
        assert observation["actor"] == service.settings.workflow_internal_actor
        assert observation["source"].startswith(
            service.settings.workflow_internal_source
        )

        assert client.post(
            "/api/assurance/quarantine-jobs/run-due",
            json={"limit": 1},
        ).status_code == 401
        assert client.post(
            "/api/assurance/quarantine-jobs/run-due",
            headers=headers,
            json={"limit": 1},
        ).status_code == 200


def test_due_job_claim_is_token_bound_and_processes_one_check(settings) -> None:
    service = _p2_service(settings)
    try:
        state = _approve_to_quarantine(service)
        quarantine = service.repository.get_quarantine(state.active_quarantine_id)
        assert quarantine is not None
        due = as_utc(quarantine.next_check_at)
        results = service.run_due_quarantine_jobs(
            now=due,
            worker_id="p2.scheduler.test",
        )
        assert len(results) == 1
        assert results[0]["observation"]["source"] == "scheduled_health_check"
        assert results[0]["observation"]["actor"] == "p2.scheduler.test"
        assert results[0]["observation"]["lease_token"]
        stored = service.repository.get_quarantine(quarantine.quarantine_id)
        assert stored is not None
        assert stored.lease_owner is None
        assert stored.lease_token is None
        assert stored.lease_until is None
    finally:
        service.close()



def test_sqlite_setup_migrates_rc2_observation_schema(settings) -> None:
    service = _p2_service(settings)
    state = _approve_to_quarantine(service)
    quarantine = service.repository.get_quarantine(state.active_quarantine_id)
    assert quarantine is not None
    received_at = as_utc(quarantine.started_at) + timedelta(seconds=1)
    original = _record(
        service,
        quarantine.quarantine_id,
        QuarantineObservationRequest(
            health=QuarantineHealth.DEGRADED,
            observed_at=received_at,
            idempotency_key="legacy-global-key",
            metrics={"legacy": True},
        ),
        received_at=received_at,
    )["observation"]
    service.close()

    database = make_url(settings.database_url).database
    assert database is not None
    database_path = Path(database)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "DROP INDEX IF EXISTS ix_assurance_quarantine_lease_token"
        )
        connection.execute(
            "ALTER TABLE assurance_quarantine DROP COLUMN lease_token"
        )
        connection.execute(
            "ALTER TABLE assurance_quarantine DROP COLUMN version"
        )
        connection.execute(
            """
            CREATE TABLE assurance_quarantine_observation_rc2 (
                observation_id VARCHAR(100) NOT NULL PRIMARY KEY,
                quarantine_id VARCHAR(100) NOT NULL,
                incident_id VARCHAR(80) NOT NULL,
                observed_at DATETIME NOT NULL,
                health VARCHAR(32) NOT NULL,
                source VARCHAR(120) NOT NULL,
                actor VARCHAR(120) NOT NULL,
                idempotency_key VARCHAR(160) NOT NULL UNIQUE,
                metrics_json JSON NOT NULL,
                transition VARCHAR(32) NOT NULL,
                created_at DATETIME NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO assurance_quarantine_observation_rc2 (
                observation_id, quarantine_id, incident_id, observed_at,
                health, source, actor, idempotency_key, metrics_json,
                transition, created_at
            )
            SELECT observation_id, quarantine_id, incident_id, observed_at,
                   health, source, actor, idempotency_key, metrics_json,
                   transition, created_at
            FROM assurance_quarantine_observation
            """
        )
        connection.execute("DROP TABLE assurance_quarantine_observation")
        connection.execute(
            "ALTER TABLE assurance_quarantine_observation_rc2 "
            "RENAME TO assurance_quarantine_observation"
        )

    migrated = WorkflowService(settings=service.settings)
    try:
        columns = {
            column["name"]
            for column in inspect(migrated.repository.engine).get_columns(
                "assurance_quarantine_observation"
            )
        }
        assert {"received_at", "request_fingerprint", "lease_token"} <= columns
        quarantine_columns = {
            column["name"]
            for column in inspect(migrated.repository.engine).get_columns(
                "assurance_quarantine"
            )
        }
        assert {"version", "lease_token"} <= quarantine_columns
        constraints = inspect(
            migrated.repository.engine
        ).get_unique_constraints("assurance_quarantine_observation")
        assert any(
            constraint.get("column_names")
            == ["quarantine_id", "idempotency_key"]
            for constraint in constraints
        )
        assert not any(
            constraint.get("column_names") == ["idempotency_key"]
            for constraint in constraints
        )
        stored = migrated.repository.get_quarantine_observation_by_key(
            quarantine.quarantine_id,
            "legacy-global-key",
        )
        assert stored is not None
        assert stored.observation_id == original["observation_id"]
        assert stored.request_fingerprint
        assert stored.received_at
    finally:
        migrated.close()
