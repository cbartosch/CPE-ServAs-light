from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from lpr_cpe_demo.api.main import create_app
from lpr_cpe_demo.assurance import (
    AssuranceEpisode,
    AssuranceOrigin,
    EpisodeStatus,
    InstallHandoffRequest,
    InstallHandoffState,
    episode_id_for_install,
)
from lpr_cpe_demo.domain import stable_id
from lpr_cpe_demo.workflow.service import ApprovalConflict, WorkflowService


def _handoff(**updates: object) -> InstallHandoffRequest:
    values: dict[str, object] = {
        "run_id": "RUN-20260902-P1",
        "watch_id": "IAW-0123456789ABCDEF",
        "install_episode_id": "IAE-0123456789AB",
        "service_id": "SVC-100",
        "device_id": "CPE-100",
        "technology": "HFC",
        "reason": "Persistent RED install health after baseline acceptance.",
        "evidence": [{"kind": "install_health", "health": "RED"}],
        "source_summary": {"health_state": "RED"},
        "production_write": False,
    }
    values.update(updates)
    return InstallHandoffRequest.model_validate(values)


def test_normal_repair_is_projected_into_shared_episode(
    service: WorkflowService,
) -> None:
    state = service.start_scenario("hfc_remote_success")

    episodes = service.list_assurance_episodes()
    assert len(episodes) == 1
    assert episodes[0].origin == AssuranceOrigin.REPAIR
    assert episodes[0].incident_id == state.incident_id
    assert episodes[0].source_key == f"repair:{state.incident_id}"


def test_install_handoff_creates_one_canonical_repair_episode(
    service: WorkflowService,
) -> None:
    first = service.create_install_handoff(_handoff())
    second = service.create_install_handoff(_handoff())

    assert first.created is True
    assert second.created is False
    assert first.episode.episode_id == second.episode.episode_id
    assert first.episode.incident_id == second.episode.incident_id
    assert first.episode.origin == AssuranceOrigin.INSTALL
    assert first.episode.install_watch_id == "IAW-0123456789ABCDEF"
    assert len(service.list_assurance_episodes()) == 1

    detail = service.get_assurance_episode(first.episode.episode_id)
    event_types = [row["event_type"] for row in detail["events"]]
    assert "install_handoff_claimed" in event_types
    assert "repair_workflow_started" in event_types


def test_install_handoff_rejects_production_write(
    service: WorkflowService,
) -> None:
    request = _handoff(production_write=True)

    try:
        service.create_install_handoff(request)
    except RuntimeError as exc:
        assert "PRODUCTION_WRITE_NOT_PERMITTED" in str(exc)
    else:
        raise AssertionError("production write handoff was not rejected")


def test_install_handoff_resumes_after_workflow_start_failure(
    service: WorkflowService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = service.engine.run_until_pause

    def fail_before_workflow(_state):
        raise RuntimeError("injected workflow startup failure")

    monkeypatch.setattr(service.engine, "run_until_pause", fail_before_workflow)
    with pytest.raises(RuntimeError, match="injected workflow startup failure"):
        service.create_install_handoff(_handoff())

    claim = service.repository.get_install_handoff_claim(_handoff().source_key)
    assert claim is not None
    assert claim.state == InstallHandoffState.FAILED_RETRYABLE
    assert claim.attempt_count == 1
    assert service.get_incident(claim.incident_id).stage.value == "new"

    monkeypatch.setattr(service.engine, "run_until_pause", original)
    retry = service.create_install_handoff(_handoff())

    assert retry.created is False
    assert retry.incident["stage"] != "new"
    claim = service.repository.get_install_handoff_claim(_handoff().source_key)
    assert claim is not None
    assert claim.state == InstallHandoffState.WORKFLOW_STARTED
    assert claim.attempt_count == 2
    detail = service.get_assurance_episode(retry.episode.episode_id)
    assert [event["event_type"] for event in detail["events"]].count(
        "repair_workflow_started"
    ) == 1


def test_install_handoff_claim_rolls_back_as_one_unit(
    service: WorkflowService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = service.repository._insert_do_nothing

    def fail_after_claim(session, row_type, values):
        inserted = original(session, row_type, values)
        if row_type.__name__ == "IncidentRow":
            raise RuntimeError("injected canonical-row failure")
        return inserted

    monkeypatch.setattr(service.repository, "_insert_do_nothing", fail_after_claim)
    with pytest.raises(RuntimeError, match="canonical-row failure"):
        service.create_install_handoff(_handoff())

    source_key = _handoff().source_key
    assert service.repository.get_install_handoff_claim(source_key) is None
    assert service.repository.get_assurance_episode_by_source(source_key) is None
    assert service.list_incidents() == []

    monkeypatch.setattr(service.repository, "_insert_do_nothing", original)
    result = service.create_install_handoff(_handoff())
    assert result.created is True


def test_install_handoff_adopts_and_resumes_a_pre_fix_partial_claim(
    service: WorkflowService,
) -> None:
    request = _handoff()
    incident_id = stable_id(request.source_key, prefix="inc").upper()
    state = service._new_incident(
        scenario_name="hfc_remote_fail_clean_success",
        title=request.title,
        source="install_assurance",
        priority=request.priority,
        incident_id=incident_id,
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
    episode = AssuranceEpisode(
        episode_id=episode_id_for_install(request),
        origin=AssuranceOrigin.INSTALL,
        source_key=request.source_key,
        incident_id=incident_id,
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
    service.repository.save_incident(state)
    service.repository.save_assurance_episode(episode)

    resumed = service.create_install_handoff(request)

    assert resumed.created is False
    assert resumed.episode.episode_id == episode.episode_id
    assert resumed.incident["stage"] != "new"
    claim = service.repository.get_install_handoff_claim(request.source_key)
    assert claim is not None
    assert claim.state == InstallHandoffState.WORKFLOW_STARTED


def test_install_handoff_parallel_retries_converge(
    service: WorkflowService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workers = 32
    barrier = threading.Barrier(workers)
    engine_calls = 0
    counter_lock = threading.Lock()
    original = service.engine.run_until_pause

    def counted_run(state):
        nonlocal engine_calls
        with counter_lock:
            engine_calls += 1
        time.sleep(0.05)
        return original(state)

    monkeypatch.setattr(service.engine, "run_until_pause", counted_run)

    def invoke():
        barrier.wait(timeout=10)
        return service.create_install_handoff(_handoff())

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = [future.result() for future in [pool.submit(invoke) for _ in range(workers)]]

    assert sum(result.created for result in results) == 1
    assert len({result.episode.episode_id for result in results}) == 1
    assert len({result.episode.incident_id for result in results}) == 1
    assert engine_calls == 1
    assert len(service.list_assurance_episodes()) == 1
    assert len(service.list_incidents()) == 1

    claim = service.repository.get_install_handoff_claim(_handoff().source_key)
    assert claim is not None
    assert claim.state == InstallHandoffState.WORKFLOW_STARTED
    assert claim.attempt_count == 1
    events = service.repository.list_assurance_events(results[0].episode.episode_id)
    assert [event.event_type for event in events].count("install_handoff_claimed") == 1
    assert [event.event_type for event in events].count("repair_workflow_started") == 1


def test_install_handoff_renews_lease_during_a_long_workflow(
    service: WorkflowService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    original = service.engine.run_until_pause
    service.settings.install_handoff_lease_seconds = 3

    def blocked_run(state):
        entered.set()
        assert release.wait(timeout=10)
        return original(state)

    monkeypatch.setattr(service.engine, "run_until_pause", blocked_run)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.create_install_handoff, _handoff())
        assert entered.wait(timeout=10)
        first = service.repository.get_install_handoff_claim(_handoff().source_key)
        assert first is not None
        assert first.lease_until is not None

        time.sleep(1.2)
        renewed = service.repository.get_install_handoff_claim(_handoff().source_key)
        assert renewed is not None
        assert renewed.lease_until is not None
        assert renewed.lease_until > first.lease_until

        release.set()
        result = future.result(timeout=10)

    assert result.created is True
    claim = service.repository.get_install_handoff_claim(_handoff().source_key)
    assert claim is not None
    assert claim.state == InstallHandoffState.WORKFLOW_STARTED
    assert claim.lease_owner is None
    assert claim.lease_until is None


def test_install_handoff_rejects_conflicting_replay(
    service: WorkflowService,
) -> None:
    service.create_install_handoff(_handoff())

    with pytest.raises(ApprovalConflict, match="SOURCE_PAYLOAD_CONFLICT"):
        service.create_install_handoff(_handoff(device_id="CPE-DIFFERENT"))


def test_assurance_api_exposes_handoff_and_episode_read_model(
    service: WorkflowService,
    settings,
) -> None:
    app = create_app(settings=settings, service=service)
    with TestClient(app) as client:
        unauthenticated = client.post(
            "/api/assurance/install-handoffs",
            json=_handoff().model_dump(mode="json"),
        )
        assert unauthenticated.status_code == 401

        response = client.post(
            "/api/assurance/install-handoffs",
            json=_handoff().model_dump(mode="json"),
            headers={"X-LPR-Internal-Token": settings.workflow_internal_token},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["created"] is True
        episode_id = payload["episode"]["episode_id"]

        listing = client.get("/api/assurance/episodes")
        assert listing.status_code == 200
        assert [row["episode_id"] for row in listing.json()] == [episode_id]

        detail = client.get(f"/api/assurance/episodes/{episode_id}")
        assert detail.status_code == 200
        assert detail.json()["episode"]["origin"] == "install"
