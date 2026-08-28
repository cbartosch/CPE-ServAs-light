from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lpr_cpe_demo.digital_twin.dispatch_projection import (
    DispatchProjectionIntegrityError,
    MixedRegionDelimiterError,
    build_dispatch_cost_projection,
    dispatch_cost_contract,
)
from lpr_cpe_demo.digital_twin.models import GenerationConfig
from lpr_cpe_demo.digital_twin.orchestrator import REGIONS, _subscriber, generate
from lpr_cpe_demo.digital_twin.storage import (
    RUN_SCHEMA_VERSION,
    canonical_config,
    derive_run_id,
    iter_jsonl_gz,
    safe_run_path,
    sha256_file,
    write_jsonl_gz,
)


def _run(tmp_path: Path) -> dict:
    return generate(
        GenerationConfig(
            homes=200,
            seed=42,
            scenarios=["fiber_cut", "hfc_ingress", "slow_wifi", "cpe_failure"],
        ),
        tmp_path,
    )


def _hashes(run_path: Path) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(run_path.iterdir())
        if path.is_file()
    }


def _rewrite_dataset(
    run_path: Path,
    dataset: str,
    rows: list[dict],
) -> None:
    path = run_path / f"{dataset}.jsonl.gz"
    row_count = write_jsonl_gz(path, rows)
    catalog_path = run_path / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    entry = next(item for item in catalog["datasets"] if item["dataset"] == dataset)
    entry["row_count"] = row_count
    entry["sha256"] = sha256_file(path)
    catalog_path.write_text(
        json.dumps(catalog, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_dispatch_contract_separates_generated_modelled_and_assumed_inputs() -> None:
    contract = dispatch_cost_contract()
    assert contract["primary_grain"] == "case_id"
    assert "work-order skill, parts and timestamps" in contract["run_derived_inputs"]
    assert "dispatch hub selection and road/ferry route" in contract["modelled_inputs"]
    assert "labour rates" in contract["assumed_inputs"]
    assert "one delimiter_id must map to exactly one planning region" in contract[
        "topology_controls"
    ]
    assert "every catalog dataset hash and row count is verified before costing" in (
        contract["integrity_controls"]
    )
    assert "comparison-only" in contract["cost_bases"]["generated_execution"]
    assert contract["production_writes"] is False


def test_subscriber_region_is_assigned_at_serving_delimiter_grain() -> None:
    regions_by_delimiter: dict[str, set[str]] = defaultdict(set)
    observed_regions: set[str] = set()
    for index in range(257):
        subscriber = _subscriber(index, 257)
        regions_by_delimiter[subscriber["delimiter_id"]].add(subscriber["region"])
        observed_regions.add(subscriber["region"])

    assert observed_regions == set(REGIONS)
    assert all(len(regions) == 1 for regions in regions_by_delimiter.values())


def test_run_id_changes_when_the_generation_schema_changes() -> None:
    config = GenerationConfig(
        homes=200,
        seed=42,
        scenarios=["fiber_cut", "slow_wifi"],
    )
    legacy_digest = hashlib.sha256(canonical_config(config)).hexdigest().upper()[:20]
    legacy_run_id = f"RUN-{config.run_date:%Y%m%d}-{legacy_digest}"

    assert RUN_SCHEMA_VERSION == "lpr-digital-twin-run-v3-execution-economics"
    assert derive_run_id(config) != legacy_run_id


def test_legacy_run_schema_is_rejected_before_costing(tmp_path: Path) -> None:
    catalog = _run(tmp_path)
    run_path = safe_run_path(tmp_path, catalog["run_id"])
    catalog_path = run_path / "catalog.json"
    stored = json.loads(catalog_path.read_text(encoding="utf-8"))
    stored["run_schema_version"] = "lpr-digital-twin-run-v2-delimiter-region"
    catalog_path.write_text(
        json.dumps(stored, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(DispatchProjectionIntegrityError, match="regenerate the run"):
        build_dispatch_cost_projection(tmp_path, catalog["run_id"])


def test_projection_links_every_generated_case_to_cost_and_dispatch(tmp_path: Path) -> None:
    catalog = _run(tmp_path)
    run_path = safe_run_path(tmp_path, catalog["run_id"])
    manifests = list(iter_jsonl_gz(run_path / "scenario_manifests.jsonl.gz"))
    projection = build_dispatch_cost_projection(tmp_path, catalog["run_id"])

    assert projection["run_id"] == catalog["run_id"]
    assert len(projection["cases"]) == len(manifests)
    assert projection["summary"]["case_attempts"] == len(manifests)
    assert projection["reconciliation"]["case_attempts_equal_manifest_rows"] is True
    assert projection["reconciliation"]["all_identifier_sets_match"] is True
    assert projection["data_integrity"]["passed"] is True
    assert projection["data_integrity"]["catalog_hashes_verified"] is True
    assert projection["data_integrity"]["case_graph_verified"] is True
    assert projection["measurement_context"]["completeness"].startswith("catalog")

    required = {
        "case_id",
        "incident_id",
        "service_id",
        "device_id",
        "scenario",
        "technology",
        "delimiter_id",
        "actual_domain",
        "recommended_domain",
        "executed_or_forecast_action",
        "action_status",
        "cost_basis",
        "site_id",
        "municipio",
        "route",
        "ledger_rows",
        "total_cost_usd",
    }
    for case in projection["cases"]:
        assert required.issubset(case)
        assert case["total_cost_usd"] > 0
        assert case["actual_domain_source"] in {
            "immutable_scenario_truth",
            "validated_resolution",
        }
        assert case["production_write"] is False
        assert "mapped" in case["location_provenance"].lower()
        assert case["cost_provenance"]


def test_generated_execution_and_governed_forecast_are_kept_separate(
    tmp_path: Path,
) -> None:
    catalog = _run(tmp_path)
    projection = build_dispatch_cost_projection(tmp_path, catalog["run_id"])
    summary = projection["summary"]

    assert summary["generated_execution_cases"] > 0
    assert summary["governed_forecast_cases"] > 0
    assert (
        summary["generated_execution_cases"] + summary["governed_forecast_cases"]
        == summary["case_attempts"]
    )
    assert round(
        summary["generated_execution_cost_usd"]
        + summary["governed_forecast_cost_usd"],
        2,
    ) == summary["combined_modelled_cost_usd"]
    assert summary["truck_rolls"] == (
        summary["executed_truck_rolls"]
        + summary["forecast_truck_roll_equivalents"]
    )
    assert summary["dirty_boots_case_denominator"] == summary["case_attempts"]
    assert summary["dirty_boots_field_denominator"] == summary["field_dispatched_cases"]
    assert summary["ferry_jobs"] == (
        summary["executed_ferry_uses"]
        + summary["forecast_ferry_equivalents"]
    )
    assert summary["overnight_jobs"] == (
        summary["executed_overnight_uses"]
        + summary["forecast_overnight_equivalents"]
    )

    executed = [
        case
        for case in projection["cases"]
        if case["cost_basis"] == "generated_execution"
    ]
    forecasts = [
        case
        for case in projection["cases"]
        if case["cost_basis"] == "governed_forecast"
    ]
    assert all(case["action_status"] == "SIMULATED_EXECUTED" for case in executed)
    assert all(case["action_status"] != "SIMULATED_EXECUTED" for case in forecasts)


def test_generated_work_order_timestamps_drive_executed_travel_cost(
    tmp_path: Path,
) -> None:
    catalog = _run(tmp_path)
    projection = build_dispatch_cost_projection(tmp_path, catalog["run_id"])
    case = next(
        row
        for row in projection["cases"]
        if row["work_order_ids"] and row["generated_route_minutes"] is not None
    )
    one_way = int(case["generated_route_minutes"])
    travel_line = next(line for line in case["ledger_rows"] if line["step"] == "travel")
    assert travel_line["minutes"] == 2 * one_way
    assert travel_line["duration_provenance"] == "generated_work_order_economics"
    assert "generated road km" in travel_line["note"]
    assert case["modelled_route_minutes"] > 0
    assert case["execution_economics_complete"] is True
    assert "comparison-only" in case["cost_provenance"]


def test_executed_cost_does_not_import_modelled_route_premiums(tmp_path: Path) -> None:
    catalog = _run(tmp_path)
    run_path = safe_run_path(tmp_path, catalog["run_id"])
    initial = build_dispatch_cost_projection(tmp_path, catalog["run_id"])
    target = next(
        case
        for case in initial["cases"]
        if case["cost_basis"] == "generated_execution"
        and case["work_order_ids"]
        and case["modelled_requires_ferry"]
    )
    work_orders = list(iter_jsonl_gz(run_path / "work_orders.jsonl.gz"))
    for work_order in work_orders:
        if work_order["case_id"] == target["case_id"]:
            work_order["ferry_used"] = False
            work_order["overnight_used"] = False
    _rewrite_dataset(run_path, "work_orders", work_orders)

    projection = build_dispatch_cost_projection(tmp_path, catalog["run_id"])
    case = next(
        row for row in projection["cases"] if row["case_id"] == target["case_id"]
    )
    steps = [line["step"] for line in case["ledger_rows"]]
    assert case["modelled_requires_ferry"] is True
    assert case["requires_ferry"] is False
    assert "ferry" not in steps
    assert "overnight" not in steps


def test_catalog_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    catalog = _run(tmp_path)
    run_path = safe_run_path(tmp_path, catalog["run_id"])
    path = run_path / "deterministic_decisions.jsonl.gz"
    rows = list(iter_jsonl_gz(path))
    rows[0]["recommended_domain"] = "provisioning"
    write_jsonl_gz(path, rows)

    with pytest.raises(DispatchProjectionIntegrityError, match="hash mismatch"):
        build_dispatch_cost_projection(tmp_path, catalog["run_id"])


def test_api_returns_structured_integrity_report_for_catalog_mismatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from lpr_cpe_demo.digital_twin import api

    catalog = _run(tmp_path)
    run_path = safe_run_path(tmp_path, catalog["run_id"])
    path = run_path / "deterministic_decisions.jsonl.gz"
    rows = list(iter_jsonl_gz(path))
    rows[0]["recommended_domain"] = "provisioning"
    write_jsonl_gz(path, rows)
    monkeypatch.setattr(api, "DATA_ROOT", tmp_path)
    response = TestClient(api.app).get(
        f"/api/runs/{catalog['run_id']}/dispatch-cost-projection",
        auth=("demo", "CHANGE_ME"),
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error"] == "dispatch_projection_integrity_failed"
    assert detail["run_id"] == catalog["run_id"]
    assert any("hash mismatch" in issue for issue in detail["issues"])


def test_missing_subscriber_join_fails_closed_even_with_updated_catalog(
    tmp_path: Path,
) -> None:
    catalog = _run(tmp_path)
    run_path = safe_run_path(tmp_path, catalog["run_id"])
    manifests = list(iter_jsonl_gz(run_path / "scenario_manifests.jsonl.gz"))
    missing_service = str(manifests[0]["service_id"])
    subscribers = [
        row
        for row in iter_jsonl_gz(run_path / "subscriber_master.jsonl.gz")
        if str(row["service_id"]) != missing_service
    ]
    _rewrite_dataset(run_path, "subscriber_master", subscribers)

    with pytest.raises(DispatchProjectionIntegrityError, match="no subscriber row"):
        build_dispatch_cost_projection(tmp_path, catalog["run_id"])


def test_missing_root_incident_join_fails_closed_even_with_updated_catalog(
    tmp_path: Path,
) -> None:
    catalog = _run(tmp_path)
    run_path = safe_run_path(tmp_path, catalog["run_id"])
    manifests = list(iter_jsonl_gz(run_path / "scenario_manifests.jsonl.gz"))
    missing_incident = str(manifests[0]["root_incident_id"])
    incidents = [
        row
        for row in iter_jsonl_gz(run_path / "incidents.jsonl.gz")
        if str(row["incident_id"]) != missing_incident
    ]
    _rewrite_dataset(run_path, "incidents", incidents)

    with pytest.raises(DispatchProjectionIntegrityError, match="no root incident"):
        build_dispatch_cost_projection(tmp_path, catalog["run_id"])


def test_missing_immutable_scenario_truth_fails_closed(tmp_path: Path) -> None:
    catalog = _run(tmp_path)
    run_path = safe_run_path(tmp_path, catalog["run_id"])
    manifests = list(iter_jsonl_gz(run_path / "scenario_manifests.jsonl.gz"))
    manifests[0].pop("scenario_truth_domain", None)
    _rewrite_dataset(run_path, "scenario_manifests", manifests)

    with pytest.raises(DispatchProjectionIntegrityError, match="scenario truth domain"):
        build_dispatch_cost_projection(tmp_path, catalog["run_id"])


def test_actual_domain_is_independent_from_the_recommendation(tmp_path: Path) -> None:
    catalog = _run(tmp_path)
    run_path = safe_run_path(tmp_path, catalog["run_id"])
    decisions = list(iter_jsonl_gz(run_path / "deterministic_decisions.jsonl.gz"))
    target = decisions[0]
    target["recommended_domain"] = "provisioning"
    _rewrite_dataset(run_path, "deterministic_decisions", decisions)

    projection = build_dispatch_cost_projection(tmp_path, catalog["run_id"])
    case = next(row for row in projection["cases"] if row["case_id"] == target["case_id"])
    assert case["recommended_domain"] == "provisioning"
    assert case["actual_domain"] != case["recommended_domain"]
    assert case["domain_match"] is False
    assert case["misdispatch_premium_usd"] > 0


def test_non_passing_validation_cannot_support_resolution_costing(
    tmp_path: Path,
) -> None:
    catalog = _run(tmp_path)
    run_path = safe_run_path(tmp_path, catalog["run_id"])
    validations = list(iter_jsonl_gz(run_path / "validation_events.jsonl.gz"))
    validations[0]["service_test"] = "FAIL"
    validations[0]["stable"] = False
    _rewrite_dataset(run_path, "validation_events", validations)

    with pytest.raises(DispatchProjectionIntegrityError, match="non-passing validation"):
        build_dispatch_cost_projection(tmp_path, catalog["run_id"])


def test_generated_work_order_readiness_drives_hub_staging(tmp_path: Path) -> None:
    catalog = _run(tmp_path)
    projection = build_dispatch_cost_projection(tmp_path, catalog["run_id"])
    executed = [case for case in projection["cases"] if case["work_order_ids"]]

    assert executed
    assert all(
        case["dispatch_readiness_source"]
        == "generated_work_order_readiness_adapter"
        for case in executed
    )
    for case in executed:
        skill = case["generated_required_skills"][0]
        if skill == "PON_PLANT":
            assert case["dispatch_required_skills"] == ["fibre_splice"]
            assert case["dispatch_required_parts"] == ["splice_kit"]
        elif skill == "HFC_PLANT":
            assert case["dispatch_required_skills"] == ["hfc_plant"]
            assert case["dispatch_required_parts"] == ["connectors"]
        elif skill == "CPE_SWAP_CERTIFIED":
            assert case["dispatch_required_skills"] == ["cpe_swap"]
            assert case["dispatch_required_parts"] == ["cpe"]


def test_same_generated_delimiter_maps_to_one_dispatch_site(tmp_path: Path) -> None:
    catalog = _run(tmp_path)
    projection = build_dispatch_cost_projection(tmp_path, catalog["run_id"])
    by_delimiter: dict[str, set[str]] = {}
    for case in projection["cases"]:
        by_delimiter.setdefault(case["delimiter_id"], set()).add(case["site_id"])
    assert all(len(site_ids) == 1 for site_ids in by_delimiter.values())


def _introduce_mixed_region_delimiter(run_path: Path) -> str:
    manifests = list(iter_jsonl_gz(run_path / "scenario_manifests.jsonl.gz"))
    case_services = {str(row["service_id"]) for row in manifests}
    subscribers = list(iter_jsonl_gz(run_path / "subscriber_master.jsonl.gz"))
    by_delimiter: dict[str, list[dict]] = defaultdict(list)
    for row in subscribers:
        by_delimiter[str(row["delimiter_id"])].append(row)

    delimiter_id = next(
        str(row["delimiter_id"])
        for row in subscribers
        if str(row["service_id"]) in case_services
        and len(by_delimiter[str(row["delimiter_id"])]) > 1
    )
    group = by_delimiter[delimiter_id]
    original_region = str(group[0]["region"])
    group[1]["region"] = next(region for region in REGIONS if region != original_region)
    _rewrite_dataset(run_path, "subscriber_master", subscribers)
    return delimiter_id


def test_projection_rejects_a_legacy_mixed_region_delimiter(tmp_path: Path) -> None:
    catalog = _run(tmp_path)
    run_path = safe_run_path(tmp_path, catalog["run_id"])
    delimiter_id = _introduce_mixed_region_delimiter(run_path)

    with pytest.raises(MixedRegionDelimiterError, match=delimiter_id):
        build_dispatch_cost_projection(tmp_path, catalog["run_id"])


def test_api_returns_conflict_for_a_mixed_region_legacy_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from lpr_cpe_demo.digital_twin import api

    catalog = _run(tmp_path)
    run_path = safe_run_path(tmp_path, catalog["run_id"])
    delimiter_id = _introduce_mixed_region_delimiter(run_path)
    monkeypatch.setattr(api, "DATA_ROOT", tmp_path)
    client = TestClient(api.app)

    response = client.get(
        f"/api/runs/{catalog['run_id']}/dispatch-cost-projection",
        auth=("demo", "CHANGE_ME"),
    )

    assert response.status_code == 409
    assert delimiter_id in response.json()["detail"]
    assert "regenerate" in response.json()["detail"].lower()


def test_projection_is_read_only_and_deterministic(tmp_path: Path) -> None:
    catalog = _run(tmp_path)
    run_path = safe_run_path(tmp_path, catalog["run_id"])
    before = _hashes(run_path)
    first = build_dispatch_cost_projection(tmp_path, catalog["run_id"])
    second = build_dispatch_cost_projection(tmp_path, catalog["run_id"])
    after = _hashes(run_path)
    assert first == second
    assert before == after


def test_dispatch_projection_api_supports_active_and_explicit_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from lpr_cpe_demo.digital_twin import api

    monkeypatch.setattr(api, "DATA_ROOT", tmp_path)
    client = TestClient(api.app)
    auth = ("demo", "CHANGE_ME")
    created = client.post(
        "/api/runs",
        auth=auth,
        json={
            "config": {
                "homes": 120,
                "seed": 91,
                "scenarios": ["fiber_cut", "slow_wifi"],
            }
        },
    )
    assert created.status_code == 200
    run_id = created.json()["run_id"]

    contract = client.get("/api/dispatch-cost-contract", auth=auth)
    active = client.get("/api/dispatch-cost-projection", auth=auth)
    explicit = client.get(
        f"/api/runs/{run_id}/dispatch-cost-projection",
        auth=auth,
    )
    assert contract.status_code == 200
    assert active.status_code == 200
    assert explicit.status_code == 200
    assert active.json()["run_id"] == run_id
    assert explicit.json() == active.json()


def test_active_dispatch_projection_follows_run_switch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from lpr_cpe_demo.digital_twin import api

    monkeypatch.setattr(api, "DATA_ROOT", tmp_path)
    client = TestClient(api.app)
    auth = ("demo", "CHANGE_ME")
    first = client.post(
        "/api/runs",
        auth=auth,
        json={
            "config": {
                "homes": 90,
                "seed": 901,
                "scenarios": ["fiber_cut"],
            }
        },
    ).json()
    second = client.post(
        "/api/runs",
        auth=auth,
        json={
            "config": {
                "homes": 130,
                "seed": 1301,
                "scenarios": ["hfc_ingress"],
            }
        },
    ).json()

    assert client.get(
        "/api/dispatch-cost-projection", auth=auth
    ).json()["run_id"] == second["run_id"]
    switched = client.put(
        "/api/active-run",
        auth=auth,
        json={"run_id": first["run_id"]},
    )
    assert switched.status_code == 200
    projection = client.get("/api/dispatch-cost-projection", auth=auth)
    assert projection.status_code == 200
    assert projection.json()["run_id"] == first["run_id"]


def test_cost_and_footprint_pages_default_to_the_active_demo_run() -> None:
    root = Path(__file__).resolve().parents[1]
    simulator = (
        root / "src/lpr_cpe_demo/ui/pages/simulator.py"
    ).read_text(encoding="utf-8")
    footprint = (
        root / "src/lpr_cpe_demo/ui/pages/footprint.py"
    ).read_text(encoding="utf-8")
    client = (root / "src/lpr_cpe_demo/ui/client.py").read_text(encoding="utf-8")
    digital_twin = (
        root / "src/lpr_cpe_demo/digital_twin/streamlit_app.py"
    ).read_text(encoding="utf-8")
    legacy_theme = (
        root / "src/lpr_cpe_demo/ui/theme_dark.py"
    ).read_text(encoding="utf-8")

    assert simulator.index('"Active demo run"') < simulator.index('"Planning model"')
    assert "digital_twin_api().dispatch_cost_projection()" in simulator
    assert "Run-derived cost and dispatch cases" in simulator
    assert "Generated execution cost" in simulator
    assert "Governed forecast cost" in simulator

    assert footprint.index('"Active demo run"') < footprint.index(
        '"Manual planning inputs"'
    )
    assert "digital_twin_api().dispatch_cost_projection()" in footprint
    assert "Generated dispatch inputs" in footprint
    assert "generated_route_minutes" in footprint
    assert "modelled_route_minutes" in footprint

    assert "def dispatch_cost_projection(" in client
    assert "/api/dispatch-cost-projection" in client

    assert 'href="footprint"' in digital_twin
    assert 'href="simulator"' in digital_twin
    assert 'href="footprint"' in legacy_theme
    assert 'href="simulator"' in legacy_theme
