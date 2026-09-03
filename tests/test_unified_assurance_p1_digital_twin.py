from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from lpr_cpe_demo.digital_twin import install_assurance
from lpr_cpe_demo.digital_twin.install_assurance import (
    build_install_handoff_request,
    read_install_handoff_receipt,
    write_install_handoff_receipt,
)
from lpr_cpe_demo.digital_twin.storage import write_jsonl_gz

WATCH_ID = "IAW-0123456789ABCDEF"
EPISODE_ID = "IAE-0123456789AB"


def _watch(root: Path, *, health: str = "RED") -> Path:
    run = root / "RUN-20260902-0123456789ABCDEF0123"
    watch = run / "install_assurance" / WATCH_ID
    watch.mkdir(parents=True)
    summary = {
        "watch_id": WATCH_ID,
        "parent_run_id": run.name,
        "production_writes": False,
    }
    (watch / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    write_jsonl_gz(
        watch / "episodes.jsonl.gz",
        [
            {
                "episode_id": EPISODE_ID,
                "service_id": "SVC-100",
                "device_id": "CPE-100",
                "technology": "HFC",
                "health_state": health,
                "lifecycle_state": "PROMOTED_TO_INCIDENT" if health == "RED" else "ACTIVE",
                "incident_id": "INSTALL-INC-100" if health == "RED" else None,
                "delimiter_id": "TAP-100",
                "last_observation_at": "2026-09-02T12:00:00+00:00",
            }
        ],
    )
    write_jsonl_gz(
        watch / "observations.jsonl.gz",
        [{"episode_id": EPISODE_ID, "health_state": health}],
    )
    write_jsonl_gz(
        watch / "actions.jsonl.gz",
        [{"episode_id": EPISODE_ID, "action_type": "collect_evidence"}],
    )
    for name in ("contacts", "incidents", "caddi_contexts"):
        write_jsonl_gz(watch / f"{name}.jsonl.gz", [])
    return run


def test_install_watch_builds_canonical_p1_handoff(tmp_path: Path) -> None:
    run = _watch(tmp_path)
    payload = build_install_handoff_request(run, WATCH_ID, EPISODE_ID)

    assert payload["run_id"] == run.name
    assert payload["watch_id"] == WATCH_ID
    assert payload["install_episode_id"] == EPISODE_ID
    assert payload["service_id"] == "SVC-100"
    assert payload["production_write"] is False
    assert payload["source_summary"]["health_state"] == "RED"


def test_healthy_watch_cannot_be_promoted(tmp_path: Path) -> None:
    run = _watch(tmp_path, health="GREEN")
    try:
        build_install_handoff_request(run, WATCH_ID, EPISODE_ID)
    except ValueError as exc:
        assert "RED" in str(exc)
    else:
        raise AssertionError("healthy install watch was promoted")


def test_handoff_receipt_is_idempotent_and_separate(tmp_path: Path) -> None:
    run = _watch(tmp_path)
    first = write_install_handoff_receipt(
        run,
        WATCH_ID,
        EPISODE_ID,
        {"workflow_handoff": {"episode_id": "ase-1"}},
    )
    second = write_install_handoff_receipt(
        run,
        WATCH_ID,
        EPISODE_ID,
        {"workflow_handoff": {"episode_id": "ase-2"}},
    )

    assert first == second
    assert read_install_handoff_receipt(run, WATCH_ID, EPISODE_ID) == first
    assert (
        run
        / "install_assurance"
        / WATCH_ID
        / "workflow_handoffs"
        / f"{EPISODE_ID}.json"
    ).is_file()


def test_handoff_receipt_parallel_writers_converge(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workers = 8
    run = _watch(tmp_path)
    barrier = threading.Barrier(workers)
    local = threading.local()
    original_read = install_assurance.read_install_handoff_receipt

    def synchronized_read(run_path, watch_id, install_episode_id):
        result = original_read(run_path, watch_id, install_episode_id)
        if not getattr(local, "synchronized", False):
            local.synchronized = True
            barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(
        install_assurance,
        "read_install_handoff_receipt",
        synchronized_read,
    )

    def write(index: int):
        return install_assurance.write_install_handoff_receipt(
            run,
            WATCH_ID,
            EPISODE_ID,
            {"workflow_handoff": {"episode_id": f"ase-{index}"}},
        )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = [future.result() for future in [pool.submit(write, i) for i in range(workers)]]

    final = original_read(run, WATCH_ID, EPISODE_ID)
    assert final is not None
    assert results == [final] * workers


def test_digital_twin_promotion_endpoint_writes_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from fastapi.testclient import TestClient

    from lpr_cpe_demo.digital_twin import api

    run = _watch(tmp_path)
    monkeypatch.setattr(api, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(
        api,
        "_post_workflow_handoff",
        lambda payload: {
            "created": True,
            "episode": {"episode_id": "ase-P1"},
            "incident": {"incident_id": "INC-P1"},
            "request": payload,
        },
    )
    with TestClient(api.app) as client:
        response = client.post(
            f"/api/runs/{run.name}/install-assurance/watches/{WATCH_ID}/promote",
            auth=("demo", "CHANGE_ME"),
            json={"install_episode_id": EPISODE_ID},
        )
        assert response.status_code == 200, response.text
        assert response.json()["workflow_handoff"]["episode"]["episode_id"] == "ase-P1"

        repeat = client.post(
            f"/api/runs/{run.name}/install-assurance/watches/{WATCH_ID}/promote",
            auth=("demo", "CHANGE_ME"),
            json={"install_episode_id": EPISODE_ID},
        )
        assert repeat.status_code == 200
        assert repeat.json() == response.json()
