from __future__ import annotations

from fastapi.testclient import TestClient

from lpr_cpe_demo.api.main import create_app
from lpr_cpe_demo.assurance import AssuranceOrigin, InstallHandoffRequest
from lpr_cpe_demo.workflow.service import WorkflowService


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


def test_assurance_api_exposes_handoff_and_episode_read_model(
    service: WorkflowService,
    settings,
) -> None:
    app = create_app(settings=settings, service=service)
    with TestClient(app) as client:
        response = client.post(
            "/api/assurance/install-handoffs",
            json=_handoff().model_dump(mode="json"),
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
