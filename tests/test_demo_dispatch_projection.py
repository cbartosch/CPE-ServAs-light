from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from lpr_cpe_demo.digital_twin.dispatch_projection import (
    build_dispatch_cost_projection,
    dispatch_cost_contract,
)
from lpr_cpe_demo.digital_twin.models import GenerationConfig
from lpr_cpe_demo.digital_twin.orchestrator import generate
from lpr_cpe_demo.digital_twin.storage import iter_jsonl_gz, safe_run_path


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


def test_dispatch_contract_separates_generated_modelled_and_assumed_inputs() -> None:
    contract = dispatch_cost_contract()
    assert contract["primary_grain"] == "case_id"
    assert "work-order skill, parts and timestamps" in contract["run_derived_inputs"]
    assert "dispatch hub selection and road/ferry route" in contract["modelled_inputs"]
    assert "labour rates" in contract["assumed_inputs"]
    assert contract["production_writes"] is False


def test_projection_links_every_generated_case_to_cost_and_dispatch(tmp_path: Path) -> None:
    catalog = _run(tmp_path)
    run_path = safe_run_path(tmp_path, catalog["run_id"])
    manifests = list(iter_jsonl_gz(run_path / "scenario_manifests.jsonl.gz"))
    projection = build_dispatch_cost_projection(tmp_path, catalog["run_id"])

    assert projection["run_id"] == catalog["run_id"]
    assert len(projection["cases"]) == len(manifests)
    assert projection["summary"]["case_attempts"] == len(manifests)
    assert projection["reconciliation"]["case_attempts_equal_manifest_rows"] is True
    assert projection["measurement_context"]["completeness"].startswith("complete")

    required = {
        "case_id",
        "incident_id",
        "service_id",
        "device_id",
        "scenario",
        "technology",
        "delimiter_id",
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
        assert case["production_write"] is False
        assert "mapped" in case["location_provenance"].lower()
        assert case["cost_provenance"].startswith("Demo-generated")


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
    assert travel_line["duration_provenance"] == "generated_work_order_timestamps"
    assert case["modelled_route_minutes"] > 0


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
