from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from lpr_cpe_demo.digital_twin import api as digital_twin_api
from lpr_cpe_demo.digital_twin.executive_projection import build_executive_projection
from lpr_cpe_demo.digital_twin.models import GenerationConfig
from lpr_cpe_demo.digital_twin.orchestrator import generate
from lpr_cpe_demo.digital_twin.storage import write_jsonl_gz
from lpr_cpe_demo.measurement import (
    STATUS_PARTITION_KEYS,
    build_operations_projection,
    measurement_contract,
    status_partition_total,
)

ROOT = Path(__file__).resolve().parents[1]


def _run(tmp_path: Path, *, homes: int = 500) -> dict:
    return generate(
        GenerationConfig(
            homes=homes,
            profile="smoke",
            scenarios=("fiber_cut", "slow_wifi", "power_outage"),
        ),
        tmp_path,
    )


def test_shared_contract_defines_grains_statuses_and_invariants() -> None:
    contract = measurement_contract()
    assert contract["primary_executive_grain"] == "incident_id"
    assert contract["status_partition"] == list(STATUS_PARTITION_KEYS)
    assert contract["metrics"]["care_contacts"]["grain"] == "contact_id"
    assert contract["metrics"]["root_incidents"]["grain"] == "incident_id"
    assert contract["metrics"]["pending_approvals"]["grain"] == "approval_id"
    assert any("headline metrics" in item for item in contract["invariants"])


def test_digital_twin_projection_reconciles_complete_canonical_populations(tmp_path) -> None:
    catalog = _run(tmp_path)
    projection = build_executive_projection(tmp_path, catalog["run_id"])
    metrics = projection["metrics"]
    context = projection["measurement_context"]

    assert context["mode"] == "digital_twin_run"
    assert context["run_id"] == catalog["run_id"]
    assert context["primary_grain"] == "incident_id"
    assert projection["data_completeness"]["headline_metrics_from_paginated_rows"] is False
    assert projection["data_completeness"]["truncated"] is False
    assert projection["reconciliation"]["passed"] is True

    assert (
        metrics["forecast_risk_services"]["value"]
        + metrics["degraded_services"]["value"]
        == metrics["at_risk_services"]["value"]
    )
    care = projection["care_funnel"]
    assert care["predictively_matched"] + care["reactive_only"] == care["contacts"]
    assert status_partition_total(projection["status_partition"]) == metrics[
        "root_incidents"
    ]["value"]
    assert metrics["case_attempts"]["value"] >= metrics["root_incidents"]["value"]
    assert metrics["actual_duplicate_attempts_intercepted"]["available"] is False
    assert projection["scorecard"]["duplicate_incidents_avoided"] is None


def test_digital_twin_api_exposes_contract_projection_and_page_metadata(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(digital_twin_api, "DATA_ROOT", tmp_path)
    client = TestClient(digital_twin_api.app)
    auth = ("demo", "CHANGE_ME")
    created = client.post(
        "/api/runs",
        auth=auth,
        json={
            "config": {
                "homes": 500,
                "profile": "smoke",
                "scenarios": ["fiber_cut", "slow_wifi", "power_outage"],
            }
        },
    )
    assert created.status_code == 200
    run_id = created.json()["run_id"]

    contract = client.get("/api/measurement-contract", auth=auth)
    assert contract.status_code == 200
    assert contract.json()["primary_executive_grain"] == "incident_id"

    projection = client.get("/api/executive-projection", auth=auth)
    assert projection.status_code == 200
    assert projection.json()["run_id"] == run_id
    assert projection.json()["reconciliation"]["passed"] is True

    dataset = client.get(
        f"/api/runs/{run_id}/datasets/subscriber_master?limit=10",
        auth=auth,
    )
    assert dataset.status_code == 200
    assert dataset.json()["returned"] == 10
    assert dataset.json()["total"] == 500
    assert dataset.json()["truncated"] is True
    assert dataset.json()["headline_safe"] is False

    care = client.get(f"/api/runs/{run_id}/care/tickets?limit=1", auth=auth)
    assert care.status_code == 200
    payload = care.json()
    assert payload["returned"] == 1
    assert payload["filtered_total"] == payload["total"]
    assert payload["truncated"] is True
    assert payload["headline_safe"] is True
    assert (
        payload["summary"]["predictively_matched"]
        + payload["summary"]["reactive_only"]
        == payload["filtered_total"]
    )



def test_headline_aggregates_are_not_limited_to_display_page_size(
    tmp_path,
    monkeypatch,
) -> None:
    run_id = "RUN-20260826-AAAAAAAAAAAAAAAAAAAA"
    run_path = tmp_path / run_id
    run_path.mkdir()
    contact_total = 5_101
    catalog = {
        "run_id": run_id,
        "config": {"homes": 1, "run_date": "2026-08-26"},
        "operational_scale": {"homes": 1},
        "quality": {"passed": True, "checks": 1},
        "production_writes": False,
        "datasets": [
            {"dataset": "care_tickets", "row_count": contact_total},
            {"dataset": "subscriber_master", "row_count": 1},
            {"dataset": "incidents", "row_count": 1},
            {"dataset": "scenario_manifests", "row_count": 1},
        ],
    }
    (run_path / "catalog.json").write_text(
        json.dumps(catalog),
        encoding="utf-8",
    )
    write_jsonl_gz(
        run_path / "subscriber_master.jsonl.gz",
        [{"service_id": "SVC-1", "device_id": "CPE-1"}],
    )
    write_jsonl_gz(
        run_path / "incidents.jsonl.gz",
        [{"incident_id": "INC-1", "status": "OPEN"}],
    )
    write_jsonl_gz(
        run_path / "scenario_manifests.jsonl.gz",
        [
            {
                "case_id": "CASE-1",
                "root_incident_id": "INC-1",
                "service_id": "SVC-1",
            }
        ],
    )
    write_jsonl_gz(
        run_path / "care_tickets.jsonl.gz",
        (
            {
                "care_ticket_id": f"CARE-{index}",
                "contact_id": f"CONTACT-{index}",
                "case_id": "CASE-1",
                "incident_id": "INC-1",
                "service_id": "SVC-1",
                "status": "OPEN",
                "priority": "P3",
                "predictive_match": False,
                "repeat_contact": False,
                "opened_at": f"2026-08-26T12:{index % 60:02d}:00+00:00",
            }
            for index in range(contact_total)
        ),
    )

    projection = build_executive_projection(tmp_path, run_id)
    assert projection["metrics"]["care_contacts"]["value"] == contact_total
    assert projection["care_funnel"]["reactive_only"] == contact_total

    monkeypatch.setattr(digital_twin_api, "DATA_ROOT", tmp_path)
    client = TestClient(digital_twin_api.app)
    response = client.get(
        f"/api/runs/{run_id}/care/tickets?limit=200",
        auth=("demo", "CHANGE_ME"),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == contact_total
    assert payload["filtered_total"] == contact_total
    assert payload["returned"] == 200
    assert payload["truncated"] is True
    assert payload["summary"]["reactive_only"] == contact_total


def test_live_operations_projection_uses_same_schema_without_faking_run_linkage() -> None:
    incidents = [
        {
            "incident_id": "INC-1",
            "status": "open",
            "technology": "HFC",
            "updated_at": datetime(2026, 8, 26, 12, 0, tzinfo=UTC),
            "remote_attempts": 1,
            "field_visits": 0,
            "mr_attempts": 0,
            "diagnostic_cycles": 1,
        },
        {
            "incident_id": "INC-2",
            "status": "waiting",
            "technology": "PON",
            "updated_at": datetime(2026, 8, 26, 12, 1, tzinfo=UTC),
            "remote_attempts": 0,
            "field_visits": 1,
            "mr_attempts": 1,
            "diagnostic_cycles": 2,
        },
        {
            "incident_id": "INC-3",
            "status": "closed",
            "technology": "HFC",
            "updated_at": datetime(2026, 8, 26, 12, 2, tzinfo=UTC),
            "remote_attempts": 1,
            "field_visits": 0,
            "mr_attempts": 0,
            "diagnostic_cycles": 1,
        },
    ]
    approvals = [
        {"approval_id": "APR-1", "status": "pending"},
        {"approval_id": "APR-2", "status": "approved"},
    ]
    projection = build_operations_projection(incidents, approvals)

    assert projection["schema_version"] == measurement_contract()["schema_version"]
    assert projection["measurement_context"]["mode"] == "live_operations"
    assert projection["measurement_context"]["linked_to_active_run"] is False
    assert projection["metrics"]["at_risk_services"]["available"] is False
    assert projection["metrics"]["root_incidents"]["value"] == 3
    assert projection["metrics"]["pending_approvals"]["value"] == 1
    assert projection["status_partition"] == {
        "open": 1,
        "waiting": 1,
        "closed": 1,
        "escalated": 0,
        "quarantined": 0,
    }
    assert projection["reconciliation"]["passed"] is True



def test_live_operations_collapses_common_cause_cases_to_one_root() -> None:
    incidents = [
        {
            "incident_id": "INC-CHILD-1",
            "parent_incident_id": "INC-ROOT",
            "status": "closed",
            "technology": "HFC",
            "updated_at": datetime(2026, 8, 26, 12, 0, tzinfo=UTC),
            "work_orders": [{"work_order_id": "WO-1"}],
            "mr_records": [],
        },
        {
            "incident_id": "INC-CHILD-2",
            "parent_incident_id": "INC-ROOT",
            "status": "waiting",
            "technology": "HFC",
            "updated_at": datetime(2026, 8, 26, 12, 1, tzinfo=UTC),
            "work_orders": [{"work_order_id": "WO-2"}],
            "mr_records": [{"mr_id": "MR-1"}, {"mr_id": "MR-1"}],
        },
    ]
    projection = build_operations_projection(incidents, [])

    assert projection["metrics"]["case_attempts"]["value"] == 2
    assert projection["metrics"]["root_incidents"]["value"] == 1
    assert projection["status_partition"] == {
        "open": 0,
        "waiting": 1,
        "closed": 0,
        "escalated": 0,
        "quarantined": 0,
    }
    assert projection["metrics"]["field_dispatched_root_incidents"]["value"] == 1
    assert projection["metrics"]["work_orders"]["value"] == 2
    assert projection["metrics"]["maintenance_requests"]["value"] == 1


def test_stage2_ui_separates_active_run_planning_model_and_child_scan() -> None:
    control = (
        ROOT / "src/lpr_cpe_demo/ui/pages/control_tower.py"
    ).read_text(encoding="utf-8")
    digital = (
        ROOT / "src/lpr_cpe_demo/digital_twin/streamlit_app.py"
    ).read_text(encoding="utf-8")
    cockpit = (
        ROOT / "src/lpr_cpe_demo/ui/pages/cockpit.py"
    ).read_text(encoding="utf-8")

    assert '("Active run evidence", "Planning model")' in control
    assert 'index=0' in control
    assert 'value=False' in control
    assert "active_projection()" in control
    assert "independent seeded fault sample" in control

    assert '_request("/api/active-run")' in digital
    assert '"PUT", {"run_id": run_id}' in digital
    assert "executive-projection" in digital
    assert "Canonical root attachments" in digital
    assert "not labelled as duplicates avoided" in digital
    assert "exploratory child scan" in digital.lower()
    assert "does not change the canonical parent run" in digital

    assert 'api().get("/api/operations-projection")' in cockpit
    assert "same metric definitions but different populations" in cockpit
    assert "not implicitly linked" in cockpit


def test_stage3_install_assurance_is_not_in_stage2() -> None:
    models = (
        ROOT / "src/lpr_cpe_demo/digital_twin/models.py"
    ).read_text(encoding="utf-8")
    assert "install_assurance" not in models
    assert "24-Hour Install Assurance Watch" not in models
