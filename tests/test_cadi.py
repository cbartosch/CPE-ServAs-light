"""CADI is explicit without becoming a second source of truth."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from lpr_cpe_demo.cadi import CADI_CAPABILITIES, cadi_contract, cadi_contract_rows
from lpr_cpe_demo.dashboard import build
from lpr_cpe_demo.digital_twin import api as digital_twin_api
from lpr_cpe_demo.telemetry import DATA_CONTRACT

ROOT = Path(__file__).resolve().parents[1]


def _by_key() -> dict[str, object]:
    return {capability.key: capability for capability in CADI_CAPABILITIES}


def test_cadi_is_a_contract_only_call_center_layer() -> None:
    contract = cadi_contract()
    assert contract["layer"] == "CADI"
    assert contract["owner_scope"] == "Call center / Genesys"
    assert contract["integration_status"] == "contract_only"
    assert contract["live_connection"] is False
    assert contract["preferred_pattern"] == "augment_or_federate"
    assert contract["replacement_policy"] == "selective_only_after_joint_discovery"


def test_cadi_preserves_authoritative_source_systems() -> None:
    contract = cadi_contract()
    policy = contract["source_of_truth_policy"]
    assert "originating" in policy
    assert "remain authoritative" in policy
    for capability in CADI_CAPABILITIES:
        assert capability.authoritative_sources
        assert "authoritative" in capability.authority_note.lower()


def test_stakeholder_supplied_cadi_capabilities_are_mapped() -> None:
    capabilities = _by_key()
    assert "CSG" in capabilities["billing"].authoritative_sources
    assert capabilities["outage_pnm"].authoritative_sources == ("OTS",)

    offline = capabilities["access_device_offline"].authoritative_sources
    assert "Intraway HFC provisioning" in offline
    assert "CommScope ServAssure NXT" in offline
    assert "Symphonica FTTH" in offline

    node = capabilities["node_outage_maintenance"].authoritative_sources
    assert "NEXT/Dvision real-time feed" in node
    assert "LLA seven-day history" in node

    premise = capabilities["premise_modem_history"].authoritative_sources
    assert "Dvision real-time feed" in premise
    assert "LLA seven-day history" in premise

    provisioning = capabilities["provisioning"].authoritative_sources
    assert "Intraway" in provisioning
    assert "Symphonica FTTH" in provisioning


def test_wifi_gap_and_plume_target_are_explicit() -> None:
    wifi = _by_key()["wifi"]
    assert wifi.coverage == "gap"
    assert wifi.authoritative_sources == ("Plume",)
    assert "not currently available" in wifi.cadi_role.lower()


def test_maintenance_and_repair_remain_an_operations_boundary() -> None:
    boundary = _by_key()["maintenance_repair_boundary"]
    assert boundary.coverage == "boundary"
    assert "not the vpto repair execution system" in boundary.cadi_role.lower()
    contract = cadi_contract()
    assert "Operations/VPTO" in contract["operations_boundary"]
    assert "rather than owning execution or closure" in contract["operations_boundary"]


def test_dashboard_exposes_cadi_without_claiming_runtime_data() -> None:
    block = build(count=20, seed=1).block("cadi_call_center_layer")
    assert block.provenance == "assumed"
    assert block.data["status"] == "contract_only"
    assert block.data["live_connection"] is False
    assert block.data["capabilities"] == cadi_contract_rows()
    assert "second source of truth" in block.note


def test_data_contract_marks_the_live_cadi_adapter_as_unwired() -> None:
    panel = next(panel for panel in DATA_CONTRACT if panel.panel == "cadi_call_center_context")
    assert panel.refresh == "per Genesys interaction"
    assert len(panel.requirements) == len(CADI_CAPABILITIES)
    assert len(panel.blocking) == len(panel.requirements)
    assert "blocked" in panel.status


def test_digital_twin_api_exposes_the_cadi_contract() -> None:
    client = TestClient(digital_twin_api.app)
    response = client.get("/api/integrations/cadi", auth=("demo", "CHANGE_ME"))
    assert response.status_code == 200
    assert response.json()["live_connection"] is False
    assert response.json()["summary"]["known_gaps"] == 1


def test_all_three_ui_surfaces_make_the_cadi_boundary_visible() -> None:
    control = (ROOT / "src/lpr_cpe_demo/ui/pages/control_tower.py").read_text(encoding="utf-8")
    theme = (ROOT / "src/lpr_cpe_demo/ui/theme_dark.py").read_text(encoding="utf-8")
    digital = (ROOT / "src/lpr_cpe_demo/digital_twin/streamlit_app.py").read_text(encoding="utf-8")
    cockpit = (ROOT / "src/lpr_cpe_demo/ui/pages/cockpit.py").read_text(encoding="utf-8")

    assert 'dash.block("cadi_call_center_layer")' in control
    assert 'href="digital-twin?view=cadi"' in theme
    assert '"CADI & Genesys"' in digital
    assert "Live CADI adapter" in digital
    assert "No live CADI adapter is connected" in cockpit
    assert "remains the execution view" in cockpit


def test_cadi_contract_document_is_explicit_about_stage_boundaries() -> None:
    document = (ROOT / "docs/CADI_INTEGRATION_CONTRACT.md").read_text(encoding="utf-8")
    assert "second source of truth" in " ".join(document.split())
    assert "Genesys" in document
    assert "Chuck" not in document  # operational boundary, not personal dependency
    assert "Stage 2 applies the shared measurement contract" in document
    assert "24-Hour Install Assurance Watch (Stage 3)" in document
    assert "live CADI data adapter" in document
