from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from lpr_cpe_demo.digital_twin.executive_projection import build_executive_projection
from lpr_cpe_demo.digital_twin.install_assurance import (
    create_install_assurance_watch,
    latest_install_assurance_projection,
    list_install_assurance_watches,
    load_install_assurance_watch,
)
from lpr_cpe_demo.digital_twin.models import GenerationConfig
from lpr_cpe_demo.digital_twin.orchestrator import generate
from lpr_cpe_demo.digital_twin.storage import safe_run_path, sha256_file


def _run(tmp_path: Path, *, homes: int = 200) -> tuple[dict, Path]:
    catalog = generate(
        GenerationConfig(
            homes=homes,
            seed=260826,
            scenarios=("fiber_cut", "slow_wifi", "power_outage"),
        ),
        tmp_path,
    )
    return catalog, safe_run_path(tmp_path, catalog["run_id"])


def _watch(run_path: Path, *, as_of_hours: float = 24.0) -> dict:
    return create_install_assurance_watch(
        run_path,
        population=12,
        as_of_hours=as_of_hours,
        stability_tail_hours=4.0,
        seed=17,
    )


def _detail(run_path: Path, summary: dict) -> dict:
    return load_install_assurance_watch(run_path, summary["watch_id"], limit=5000)


def test_install_watch_is_an_immutable_child_artifact(tmp_path):
    catalog, run_path = _run(tmp_path)
    catalog_path = run_path / "catalog.json"
    before_catalog = catalog_path.read_bytes()
    before_hashes = {
        entry["dataset"]: sha256_file(run_path / entry["path"])
        for entry in catalog["datasets"]
    }

    first = _watch(run_path)
    second = _watch(run_path)

    assert first == second
    assert catalog_path.read_bytes() == before_catalog
    assert {
        entry["dataset"]: sha256_file(run_path / entry["path"])
        for entry in catalog["datasets"]
    } == before_hashes
    assert first["measurement_context"]["canonical_run_unchanged"] is True
    assert first["production_writes"] is False


def test_healthy_hfc_and_pon_pass_without_incidents(tmp_path):
    _, run_path = _run(tmp_path)
    detail = _detail(run_path, _watch(run_path))
    by_scenario = {row["scenario"]: row for row in detail["episodes"]}

    for scenario in ("healthy_hfc", "healthy_pon"):
        episode = by_scenario[scenario]
        assert episode["lifecycle_state"] == "PASSED_24H"
        assert episode["health_state"] == "GREEN"
        assert episode["incident_id"] is None
        assert episode["outcome"] == "PASSED_WITHOUT_INTERVENTION"


def test_remote_stabilization_passes_as_assurance_not_break_fix(tmp_path):
    _, run_path = _run(tmp_path)
    detail = _detail(run_path, _watch(run_path))
    episode = next(
        row for row in detail["episodes"] if row["scenario"] == "remote_stabilized"
    )

    assert episode["lifecycle_state"] == "PASSED_24H"
    assert episode["incident_id"] is None
    assert episode["outcome"] == "PASSED_AFTER_REMOTE_STABILIZATION"
    assert "controlled_remote_reprovision" in episode["action_types"]
    assert episode["network_before_call"] is True


def test_persistent_hfc_and_pon_promote_once_to_root_incidents(tmp_path):
    _, run_path = _run(tmp_path)
    detail = _detail(run_path, _watch(run_path))
    episodes = {
        row["scenario"]: row
        for row in detail["episodes"]
        if row["scenario"] in {"persistent_hfc_impairment", "persistent_pon_impairment"}
    }
    incidents = {row["incident_id"]: row for row in detail["incidents"]}

    assert set(episodes) == {"persistent_hfc_impairment", "persistent_pon_impairment"}
    for episode in episodes.values():
        assert episode["lifecycle_state"] == "PROMOTED_TO_INCIDENT"
        assert episode["incident_id"] in incidents
        assert len(episode["work_order_ids"]) == 1
        assert len(episode["mr_ids"]) == 1
        assert incidents[episode["incident_id"]]["root_incident_id"] == episode["incident_id"]


def test_common_cause_installs_share_one_root_incident(tmp_path):
    _, run_path = _run(tmp_path)
    detail = _detail(run_path, _watch(run_path))
    episodes = [
        row for row in detail["episodes"] if row["scenario"] == "common_cause_hfc"
    ]

    assert len(episodes) == 2
    assert episodes[0]["delimiter_id"] == episodes[1]["delimiter_id"]
    assert episodes[0]["incident_id"] == episodes[1]["incident_id"]
    incident = next(
        row for row in detail["incidents"] if row["incident_id"] == episodes[0]["incident_id"]
    )
    assert incident["common_cause"] is True
    assert len(incident["episode_ids"]) == 2
    assert len(incident["service_ids"]) == 2


def test_late_action_extends_watch_beyond_hour_24(tmp_path):
    _, run_path = _run(tmp_path)
    detail = _detail(run_path, _watch(run_path, as_of_hours=24.0))
    episode = next(
        row for row in detail["episodes"] if row["scenario"] == "late_action_extension"
    )

    assert episode["lifecycle_state"] == "RECOVERING"
    assert episode["nominal_maturity_at"] < episode["effective_maturity_at"]
    assert episode["incident_id"] is None
    assert detail["summary"]["metrics"]["matured_episodes"] < 12


def test_late_action_can_pass_after_stability_tail(tmp_path):
    _, run_path = _run(tmp_path)
    detail = _detail(run_path, _watch(run_path, as_of_hours=28.0))
    episode = next(
        row for row in detail["episodes"] if row["scenario"] == "late_action_extension"
    )

    assert episode["lifecycle_state"] == "PASSED_24H"
    assert episode["incident_id"] is None


def test_open_install_incident_is_not_closed_by_watch_maturity(tmp_path):
    _, run_path = _run(tmp_path)
    detail = _detail(run_path, _watch(run_path))
    episode = next(row for row in detail["episodes"] if row["scenario"] == "active_red")
    incident = next(
        row for row in detail["incidents"] if row["incident_id"] == episode["incident_id"]
    )

    assert episode["lifecycle_state"] == "PROMOTED_TO_INCIDENT"
    assert incident["status"] == "OPEN"
    assert incident["closed_at"] is None


def test_genesys_contacts_attach_without_restarting_diagnostics(tmp_path):
    _, run_path = _run(tmp_path)
    detail = _detail(run_path, _watch(run_path))

    assert detail["contacts"]
    assert all(contact["diagnostics_restarted"] is False for contact in detail["contacts"])
    assert all(contact["duplicate_incident_created"] is False for contact in detail["contacts"])
    assert all(contact["episode_id"] for contact in detail["contacts"])
    promoted_contact = next(
        contact for contact in detail["contacts"] if contact["incident_id"] is not None
    )
    assert promoted_contact["disposition"] == "ATTACH_TO_EXISTING_INSTALL_INCIDENT"


def test_dvsum_caddi_projection_keeps_authoritative_lineage(tmp_path):
    _, run_path = _run(tmp_path)
    detail = _detail(run_path, _watch(run_path))

    assert len(detail["caddi_contexts"]) == len(detail["episodes"])
    context = next(row for row in detail["caddi_contexts"] if row["genesys_interaction_id"])
    assert context["canonical_name"] == "DvSum CADDI"
    assert context["source_layer"] == "dvsum_caddi"
    assert context["authoritative_status_source"] == "LPR Install Assurance"
    assert context["live_connection"] is False
    assert context["production_write"] is False
    assert "LPR Install Assurance" in context["underlying_source_systems"]


def test_install_metrics_use_matured_episode_denominator(tmp_path):
    _, run_path = _run(tmp_path)
    summary = _watch(run_path)
    metrics = summary["metrics"]
    rate = metrics["pass_rate_24h"]

    assert rate["numerator"] == metrics["passed_24h"]
    assert rate["denominator"] == metrics["matured_episodes"]
    assert metrics["matured_episodes"] < metrics["episodes_entering_watch"]
    assert sum(summary["lifecycle_partition"].values()) == 12
    assert sum(summary["health_partition"].values()) == 12
    assert summary["reconciliation"]["status_partition_balances"] is True
    assert summary["reconciliation"]["promoted_have_incident"] is True


def test_executive_break_fix_scorecard_does_not_change(tmp_path):
    catalog, run_path = _run(tmp_path)
    before = build_executive_projection(tmp_path, catalog["run_id"])
    _watch(run_path)
    after = build_executive_projection(tmp_path, catalog["run_id"])

    assert before["scorecard"] == after["scorecard"]
    assert before["status_partition"] == after["status_partition"]
    assert "install_assurance" not in before
    assert after["install_assurance"]["summary"]["parent_run_id"] == catalog["run_id"]


def test_watch_listing_and_latest_projection(tmp_path):
    _, run_path = _run(tmp_path)
    first = _watch(run_path, as_of_hours=12.0)
    second = _watch(run_path, as_of_hours=24.0)

    watches = list_install_assurance_watches(run_path)
    assert {row["watch_id"] for row in watches} == {first["watch_id"], second["watch_id"]}
    projection = latest_install_assurance_projection(run_path)
    assert projection is not None
    assert projection["summary"]["watch_id"] in {first["watch_id"], second["watch_id"]}


def test_install_assurance_api_endpoints(tmp_path, monkeypatch):
    from lpr_cpe_demo.digital_twin import api

    monkeypatch.setattr(api, "DATA_ROOT", tmp_path)
    client = TestClient(api.app)
    auth = ("demo", "CHANGE_ME")
    created_run = client.post(
        "/api/runs",
        auth=auth,
        json={
            "config": {
                "homes": 200,
                "seed": 260826,
                "scenarios": ["fiber_cut", "slow_wifi", "power_outage"],
            }
        },
    )
    assert created_run.status_code == 200
    run_id = created_run.json()["run_id"]

    created_watch = client.post(
        f"/api/runs/{run_id}/install-assurance/watches",
        auth=auth,
        json={
            "population": 12,
            "as_of_hours": 24,
            "stability_tail_hours": 4,
            "seed": 17,
        },
    )
    assert created_watch.status_code == 200
    watch_id = created_watch.json()["watch_id"]

    listing = client.get(f"/api/runs/{run_id}/install-assurance/watches", auth=auth)
    assert listing.status_code == 200
    assert any(row["watch_id"] == watch_id for row in listing.json())

    detail = client.get(
        f"/api/runs/{run_id}/install-assurance/watches/{watch_id}?limit=5000",
        auth=auth,
    )
    assert detail.status_code == 200
    assert len(detail.json()["episodes"]) == 12

    projection = client.get(
        f"/api/runs/{run_id}/install-assurance/projection",
        auth=auth,
    )
    assert projection.status_code == 200
    assert projection.json()["summary"]["watch_id"] == watch_id

    active_projection = client.get("/api/install-assurance/projection", auth=auth)
    assert active_projection.status_code == 200
    assert active_projection.json()["summary"]["parent_run_id"] == run_id


def test_caddi_canonical_and_cadi_compatibility_api_alias(tmp_path, monkeypatch):
    from lpr_cpe_demo.digital_twin import api

    monkeypatch.setattr(api, "DATA_ROOT", tmp_path)
    client = TestClient(api.app)
    auth = ("demo", "CHANGE_ME")

    canonical = client.get("/api/integrations/caddi", auth=auth)
    former_single_d = client.get("/api/integrations/cadi", auth=auth)
    assert canonical.status_code == 200
    assert former_single_d.status_code == 200
    assert canonical.json() == former_single_d.json()
    assert canonical.json()["canonical_name"] == "DvSum CADDI"


def test_install_artifact_summary_is_json_round_trip_safe(tmp_path):
    _, run_path = _run(tmp_path)
    summary = _watch(run_path)
    assert json.loads(json.dumps(summary, sort_keys=True)) == summary


def test_install_assurance_contract_uses_episode_grain(tmp_path, monkeypatch):
    from lpr_cpe_demo.digital_twin import api

    monkeypatch.setattr(api, "DATA_ROOT", tmp_path)
    client = TestClient(api.app)
    response = client.get(
        "/api/install-assurance/contract",
        auth=("demo", "CHANGE_ME"),
    )
    assert response.status_code == 200
    contract = response.json()
    assert contract["primary_entity"]["key"] == "episode_id"
    assert contract["primary_entity"]["not_an_incident_until"] == "PROMOTED_TO_INCIDENT"
    assert contract["separation_policy"]["break_fix_metrics_unchanged"] is True
    assert contract["metrics"]["pass_rate_24h"]["grain"] == "episode_id"


def test_install_assurance_is_visible_across_executive_and_operations_ui():
    root = Path(__file__).resolve().parents[1]
    digital_twin = (
        root / "src" / "lpr_cpe_demo" / "digital_twin" / "streamlit_app.py"
    ).read_text(encoding="utf-8")
    cockpit = (root / "src" / "lpr_cpe_demo" / "ui" / "pages" / "cockpit.py").read_text(
        encoding="utf-8"
    )
    theme = (root / "src" / "lpr_cpe_demo" / "ui" / "theme_dark.py").read_text(
        encoding="utf-8"
    )

    assert '"Install Assurance", _install_assurance' in digital_twin
    assert "Install assurance cohort" in digital_twin
    assert "DvSum CADDI & Genesys context" in digital_twin
    assert "def _install_assurance_panel" in cockpit
    assert "Episode lifecycle is mutually exclusive" in cockpit
    assert 'href="digital-twin?view=install-assurance"' in theme


def test_incident_identity_is_not_assigned_before_promotion(tmp_path):
    _, run_path = _run(tmp_path)
    detail = _detail(run_path, _watch(run_path, as_of_hours=1.0))
    persistent = [
        row
        for row in detail["episodes"]
        if row["scenario"]
        in {"persistent_hfc_impairment", "persistent_pon_impairment", "active_red"}
    ]
    assert persistent
    assert all(row["lifecycle_state"] == "ACTIVE" for row in persistent)
    assert all(row["incident_id"] is None for row in persistent)
    assert detail["incidents"] == []


def test_watch_path_traversal_and_population_cap_are_rejected(tmp_path):
    _, run_path = _run(tmp_path, homes=6_000)
    try:
        load_install_assurance_watch(run_path, "../escape")
    except ValueError:
        pass
    else:
        raise AssertionError("watch path traversal was not rejected")

    try:
        create_install_assurance_watch(run_path, population=5_001)
    except ValueError as exc:
        assert "5,000" in str(exc)
    else:
        raise AssertionError("oversized install watch was not rejected")


def test_install_watch_is_reproducible_across_data_roots(tmp_path):
    first_catalog, first_path = _run(tmp_path / "first")
    second_catalog, second_path = _run(tmp_path / "second")
    assert first_catalog["run_id"] == second_catalog["run_id"]

    first = _watch(first_path)
    second = _watch(second_path)
    assert first == second

    first_detail = _detail(first_path, first)
    second_detail = _detail(second_path, second)
    for key in (
        "episodes",
        "observations",
        "actions",
        "contacts",
        "incidents",
        "caddi_contexts",
    ):
        assert first_detail[key] == second_detail[key]


def test_install_watch_rows_are_simulation_only_and_causal(tmp_path):
    _, run_path = _run(tmp_path)
    detail = _detail(run_path, _watch(run_path))
    episodes = {row["episode_id"]: row for row in detail["episodes"]}

    for dataset in (
        "episodes",
        "observations",
        "actions",
        "contacts",
        "incidents",
        "caddi_contexts",
    ):
        assert all(row.get("production_write") is False for row in detail[dataset])

    for action in detail["actions"]:
        episode = episodes[action["episode_id"]]
        assert action["scheduled_at"] <= episode["as_of_at"]
    for contact in detail["contacts"]:
        episode = episodes[contact["episode_id"]]
        assert contact["opened_at"] <= episode["as_of_at"]
    for context in detail["caddi_contexts"]:
        assert context["episode_id"] in episodes
        assert context["episode_id"] in context["source_record_ids"]
