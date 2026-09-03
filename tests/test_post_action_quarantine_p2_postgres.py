"""PostgreSQL-specific P2 reliability and concurrency gates.

These tests are skipped unless ``P2_TEST_POSTGRES_URL`` names a disposable
PostgreSQL database. Each test creates and drops an isolated schema.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from lpr_cpe_demo.domain import (
    ApprovalDecisionInput,
    ApprovalStatus,
    CaseStatus,
    Stage,
)
from lpr_cpe_demo.quarantine import (
    QuarantineHealth,
    QuarantineLeaseError,
    QuarantineObservationConflictError,
    QuarantineObservationRequest,
    QuarantineObservationTooEarlyError,
    QuarantineStatus,
    QuarantineTerminalStateError,
    QuarantineTransition,
    as_utc,
)
from lpr_cpe_demo.persistence import Repository
from lpr_cpe_demo.workflow.service import WorkflowService

pytestmark = pytest.mark.postgres

ACTOR = "p2.postgres.test"
SOURCE = "p2-postgres-adapter"


@pytest.fixture()
def postgres_service(settings):
    """Return a P2 service backed by a fresh PostgreSQL schema."""

    database_url = os.getenv("P2_TEST_POSTGRES_URL", "").strip()
    if not database_url:
        pytest.skip("P2_TEST_POSTGRES_URL is not configured")
    pytest.importorskip("psycopg")

    schema = f"p2_rc3_{uuid4().hex}"
    admin_engine = create_engine(database_url, future=True)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    scoped_url = make_url(database_url).update_query_dict(
        {"options": f"-csearch_path={schema}"}
    )
    configured = settings.model_copy(
        update={
            "database_url": scoped_url.render_as_string(hide_password=False),
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
    try:
        yield service
    finally:
        service.close()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


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
                    reason="PostgreSQL P2 reliability test",
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


def _healthy(key: str, observed_at) -> QuarantineObservationRequest:
    return QuarantineObservationRequest(
        health=QuarantineHealth.HEALTHY,
        observed_at=observed_at,
        idempotency_key=key,
    )


def _release(service: WorkflowService, quarantine_id: str):
    quarantine = service.repository.get_quarantine(quarantine_id)
    assert quarantine is not None
    first_at = as_utc(quarantine.next_check_at)
    _record(
        service,
        quarantine_id,
        _healthy("pg-release-1", first_at),
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
        _healthy("pg-release-2", second_at),
        received_at=second_at,
    )


def test_postgres_interruption_rolls_back_complete_transition(
    postgres_service,
    monkeypatch,
) -> None:
    service = postgres_service
    state = _approve_to_quarantine(service)
    quarantine = service.repository.get_quarantine(state.active_quarantine_id)
    assert quarantine is not None
    received_at = as_utc(quarantine.started_at) + timedelta(seconds=1)

    def fail_before_commit(_session, _mutation):
        raise RuntimeError("postgres interruption probe")

    monkeypatch.setattr(
        service.repository,
        "_before_quarantine_commit",
        fail_before_commit,
    )
    with pytest.raises(RuntimeError, match="postgres interruption probe"):
        _record(
            service,
            quarantine.quarantine_id,
            QuarantineObservationRequest(
                health=QuarantineHealth.DEGRADED,
                observed_at=received_at,
                idempotency_key="pg-rollback",
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


def test_postgres_concurrent_same_key_converges(postgres_service) -> None:
    service = postgres_service
    state = _approve_to_quarantine(service)
    quarantine = service.repository.get_quarantine(state.active_quarantine_id)
    assert quarantine is not None
    workers = 24
    barrier = threading.Barrier(workers)
    received_at = as_utc(quarantine.started_at) + timedelta(seconds=1)
    request = QuarantineObservationRequest(
        health=QuarantineHealth.DEGRADED,
        observed_at=received_at,
        idempotency_key="pg-parallel-replay",
    )

    def invoke():
        barrier.wait(timeout=20)
        return _record(
            service,
            quarantine.quarantine_id,
            request,
            received_at=received_at,
        )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(invoke) for _ in range(workers)]
        results = [future.result(timeout=60) for future in futures]

    assert sum(result["created"] for result in results) == 1
    observations = service.repository.list_quarantine_observations(
        quarantine.quarantine_id
    )
    assert len(observations) == 1
    assert service.repository.get_quarantine(quarantine.quarantine_id).status == (
        QuarantineStatus.REOPENED
    )


def test_postgres_row_lock_serializes_distinct_checks(
    postgres_service,
    monkeypatch,
) -> None:
    service = postgres_service
    state = _approve_to_quarantine(service)
    quarantine = service.repository.get_quarantine(state.active_quarantine_id)
    assert quarantine is not None
    first_at = as_utc(quarantine.next_check_at)
    second_at = first_at + timedelta(seconds=quarantine.check_interval_seconds)
    entered = threading.Event()
    release = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def block_first_commit(_session, _mutation):
        nonlocal calls
        with calls_lock:
            calls += 1
            first = calls == 1
        if first:
            entered.set()
            assert release.wait(timeout=20)

    monkeypatch.setattr(
        service.repository,
        "_before_quarantine_commit",
        block_first_commit,
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            _record,
            service,
            quarantine.quarantine_id,
            _healthy("pg-serialized-1", first_at),
            received_at=first_at,
        )
        assert entered.wait(timeout=20)
        second = pool.submit(
            _record,
            service,
            quarantine.quarantine_id,
            _healthy("pg-serialized-2", second_at),
            received_at=second_at,
        )
        release.set()
        first.result(timeout=30)
        second.result(timeout=30)

    stored = service.repository.get_quarantine(quarantine.quarantine_id)
    assert stored is not None
    assert stored.healthy_checks == 2
    assert len(service.repository.list_quarantine_observations(stored.quarantine_id)) == 2


def test_postgres_lease_token_supports_expiry_takeover(postgres_service) -> None:
    service = postgres_service
    state = _approve_to_quarantine(service)
    quarantine = service.repository.get_quarantine(state.active_quarantine_id)
    assert quarantine is not None
    due = as_utc(quarantine.next_check_at)
    first = service.repository.claim_due_quarantines(
        now=due,
        worker_id="pg-worker-a",
        lease_seconds=30,
        limit=1,
    )
    assert len(first) == 1
    assert first[0].lease_token
    assert service.repository.claim_due_quarantines(
        now=due + timedelta(seconds=1),
        worker_id="pg-worker-b",
        lease_seconds=30,
        limit=1,
    ) == []

    takeover_at = due + timedelta(seconds=31)
    second = service.repository.claim_due_quarantines(
        now=takeover_at,
        worker_id="pg-worker-b",
        lease_seconds=30,
        limit=1,
    )
    assert len(second) == 1
    assert second[0].lease_token != first[0].lease_token
    request = _healthy("pg-lease-slot", takeover_at)
    with pytest.raises(QuarantineLeaseError, match="LEASE_LOST"):
        _record(
            service,
            quarantine.quarantine_id,
            request,
            received_at=takeover_at,
            lease_owner="pg-worker-a",
            lease_token=first[0].lease_token,
        )
    accepted = _record(
        service,
        quarantine.quarantine_id,
        request,
        received_at=takeover_at,
        lease_owner="pg-worker-b",
        lease_token=second[0].lease_token,
    )
    assert accepted["created"] is True
    assert accepted["observation"]["lease_token"] == second[0].lease_token


def test_postgres_replay_is_scoped_and_fingerprinted(postgres_service) -> None:
    service = postgres_service
    first_state = _approve_to_quarantine(service)
    second_state = _approve_to_quarantine(service, "hfc_self_help_success")
    quarantines = [
        service.repository.get_quarantine(first_state.active_quarantine_id),
        service.repository.get_quarantine(second_state.active_quarantine_id),
    ]
    assert all(quarantines)

    for quarantine in quarantines:
        assert quarantine is not None
        received_at = as_utc(quarantine.started_at) + timedelta(seconds=1)
        result = _record(
            service,
            quarantine.quarantine_id,
            QuarantineObservationRequest(
                health=QuarantineHealth.DEGRADED,
                observed_at=received_at,
                idempotency_key="pg-shared-key",
            ),
            received_at=received_at,
        )
        assert result["created"] is True

    first = quarantines[0]
    assert first is not None
    received_at = as_utc(first.started_at) + timedelta(seconds=1)
    with pytest.raises(
        QuarantineObservationConflictError,
        match="IDEMPOTENCY_PAYLOAD_CONFLICT",
    ):
        _record(
            service,
            first.quarantine_id,
            QuarantineObservationRequest(
                health=QuarantineHealth.UNKNOWN,
                observed_at=received_at,
                idempotency_key="pg-shared-key",
            ),
            received_at=received_at + timedelta(seconds=1),
        )


def test_postgres_server_time_and_terminal_state_are_enforced(
    postgres_service,
) -> None:
    service = postgres_service
    state = _approve_to_quarantine(service)
    quarantine = service.repository.get_quarantine(state.active_quarantine_id)
    assert quarantine is not None
    receipt_at = as_utc(quarantine.next_check_at)
    future_measurement = as_utc(quarantine.minimum_release_at) + timedelta(seconds=1)
    first = _record(
        service,
        quarantine.quarantine_id,
        _healthy("pg-future-measurement", future_measurement),
        received_at=receipt_at,
    )
    assert first["observation"]["transition"] == QuarantineTransition.CONTINUE.value
    with pytest.raises(QuarantineObservationTooEarlyError, match="TOO_EARLY"):
        _record(
            service,
            quarantine.quarantine_id,
            _healthy(
                "pg-immediate-second",
                future_measurement + timedelta(seconds=1),
            ),
            received_at=receipt_at + timedelta(seconds=1),
        )

    final = _release(service, quarantine.quarantine_id)
    assert final["incident"]["status"] == CaseStatus.CLOSED.value
    replay = _record(
        service,
        quarantine.quarantine_id,
        _healthy("pg-release-2", final["observation"]["observed_at"]),
        received_at=as_utc(final["observation"]["received_at"]) + timedelta(seconds=1),
    )
    assert replay["created"] is False
    with pytest.raises(QuarantineTerminalStateError, match="QUARANTINE_TERMINAL"):
        _record(
            service,
            quarantine.quarantine_id,
            QuarantineObservationRequest(
                health=QuarantineHealth.DEGRADED,
                observed_at=as_utc(final["observation"]["received_at"]),
                idempotency_key="pg-late-degraded",
            ),
            received_at=as_utc(final["observation"]["received_at"]),
        )


def test_postgres_setup_removes_rc2_global_unique_index(settings) -> None:
    """An upgraded RC2 database must permit one adapter key per quarantine."""

    database_url = os.getenv("P2_TEST_POSTGRES_URL", "").strip()
    if not database_url:
        pytest.skip("P2_TEST_POSTGRES_URL is not configured")
    pytest.importorskip("psycopg")

    schema = f"p2_rc2_migration_{uuid4().hex}"
    admin_engine = create_engine(database_url, future=True)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    scoped_url = make_url(database_url).update_query_dict(
        {"options": f"-csearch_path={schema}"}
    )
    scoped_database_url = scoped_url.render_as_string(hide_password=False)
    legacy_engine = create_engine(scoped_database_url, future=True)
    now = datetime.now(UTC)
    try:
        with legacy_engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE assurance_quarantine_observation (
                        observation_id VARCHAR(100) PRIMARY KEY,
                        quarantine_id VARCHAR(100) NOT NULL,
                        incident_id VARCHAR(80) NOT NULL,
                        observed_at TIMESTAMPTZ NOT NULL,
                        health VARCHAR(32) NOT NULL,
                        source VARCHAR(120) NOT NULL,
                        actor VARCHAR(120) NOT NULL,
                        idempotency_key VARCHAR(160) NOT NULL,
                        metrics_json JSON NOT NULL,
                        transition VARCHAR(32) NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX "
                    "ix_assurance_quarantine_observation_idempotency_key "
                    "ON assurance_quarantine_observation (idempotency_key)"
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO assurance_quarantine_observation (
                        observation_id, quarantine_id, incident_id, observed_at,
                        health, source, actor, idempotency_key, metrics_json,
                        transition, created_at
                    ) VALUES (
                        'qobs-old', 'quar-old', 'INC-OLD', :observed_at,
                        'healthy', 'legacy-adapter', 'legacy-worker',
                        'shared-adapter-key', CAST(:metrics AS JSON),
                        'continue', :created_at
                    )
                    """
                ),
                {
                    "observed_at": now,
                    "created_at": now,
                    "metrics": '{"legacy": true}',
                },
            )

        configured = settings.model_copy(
            update={"database_url": scoped_database_url}
        )
        repository = Repository(settings=configured)
        repository.setup()
        try:
            inspector = inspect(repository.engine)
            constraints = inspector.get_unique_constraints(
                "assurance_quarantine_observation"
            )
            indexes = inspector.get_indexes(
                "assurance_quarantine_observation"
            )
            assert any(
                constraint.get("column_names")
                == ["quarantine_id", "idempotency_key"]
                for constraint in constraints
            )
            assert not any(
                index.get("unique")
                and index.get("column_names") == ["idempotency_key"]
                for index in indexes
            )

            migrated = repository.get_quarantine_observation_by_key(
                "quar-old",
                "shared-adapter-key",
            )
            assert migrated is not None
            assert migrated.request_fingerprint
            assert migrated.received_at == migrated.created_at

            with repository.engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO assurance_quarantine_observation (
                            observation_id, quarantine_id, incident_id,
                            observed_at, received_at, health, source, actor,
                            idempotency_key, request_fingerprint, lease_token,
                            metrics_json, transition, created_at
                        ) VALUES (
                            'qobs-new', 'quar-new', 'INC-NEW', :observed_at,
                            :received_at, 'healthy', 'new-adapter',
                            'new-worker', 'shared-adapter-key',
                            :request_fingerprint, NULL, CAST(:metrics AS JSON),
                            'continue', :created_at
                        )
                        """
                    ),
                    {
                        "observed_at": now + timedelta(seconds=10),
                        "received_at": now + timedelta(seconds=10),
                        "request_fingerprint": "a" * 64,
                        "metrics": '{"legacy": false}',
                        "created_at": now + timedelta(seconds=10),
                    },
                )
                count = connection.scalar(
                    text(
                        "SELECT count(*) FROM "
                        "assurance_quarantine_observation "
                        "WHERE idempotency_key = 'shared-adapter-key'"
                    )
                )
            assert count == 2
        finally:
            repository.close()
    finally:
        legacy_engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()
