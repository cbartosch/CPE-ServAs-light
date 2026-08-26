"""DvSum DALLI is explicit without becoming a second source of truth.

The filename remains for compatibility with the Stage 1 review command. New
code and user-facing copy use DALLI; CADDI/CADI remain API and import aliases.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from lpr_cpe_demo.caddi import caddi_contract
from lpr_cpe_demo.cadi import CADI_CAPABILITIES, cadi_contract, cadi_contract_rows
from lpr_cpe_demo.dalli import (
    DALLI_REQUIRED_LINEAGE,
    DVSUM_DALLI_CAPABILITIES,
    dalli_contract,
    dalli_contract_rows,
)
from lpr_cpe_demo.dashboard import build
from lpr_cpe_demo.digital_twin import api as digital_twin_api
from lpr_cpe_demo.telemetry import DATA_CONTRACT

ROOT = Path(__file__).resolve().parents[1]


def _by_key() -> dict[str, object]:
    return {capability.key: capability for capability in DVSUM_DALLI_CAPABILITIES}


def test_dalli_is_the_canonical_contract_only_layer() -> None:
    contract = dalli_contract()
    assert contract["layer"] == "DvSum DALLI"
    assert contract["product"] == "DALLI"
    assert contract["expanded_name"] is None
    assert contract["integration_status"] == "contract_only"
    assert contract["live_connection"] is False
    assert contract["preferred_pattern"] == "augment_or_federate"
    assert contract["replacement_policy"] == "selective_only_after_joint_discovery"
    assert contract["compatibility"]["canonical_route"] == "/api/integrations/dalli"


def test_legacy_caddi_and_cadi_imports_return_the_dalli_contract() -> None:
    canonical = dalli_contract()
    assert caddi_contract() == canonical
    assert cadi_contract() == canonical
    assert cadi_contract_rows() == dalli_contract_rows()
    assert CADI_CAPABILITIES == DVSUM_DALLI_CAPABILITIES


def test_dalli_preserves_authoritative_source_systems() -> None:
    policy = dalli_contract()["source_of_truth_policy"]
    assert "originating" in policy.lower()
    assert "remain authoritative" in policy.lower()
    for capability in DVSUM_DALLI_CAPABILITIES:
        assert capability.authoritative_sources
        assert "authoritative" in capability.authority_note.lower()
        assert capability.dalli_role
        assert capability.caddi_role == capability.dalli_role
        assert capability.cadi_role == capability.dalli_role


def test_stakeholder_supplied_dalli_capabilities_are_mapped() -> None:
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
    assert "not currently available" in wifi.dalli_role.lower()


def test_maintenance_and_repair_remain_an_operations_boundary() -> None:
    boundary = _by_key()["maintenance_repair_boundary"]
    assert boundary.coverage == "boundary"
    assert "operational workflow owns execution and closure" in boundary.dalli_role.lower()
    contract = dalli_contract()
    assert "operational workflow remains authoritative" in contract["operations_boundary"].lower()


def test_required_analytical_lineage_is_explicit() -> None:
    contract = dalli_contract()
    assert set(DALLI_REQUIRED_LINEAGE) == set(contract["required_lineage"])
    assert "analytical_record_id" in contract["required_lineage"]
    assert "authoritative_status_source" in contract["required_lineage"]


def test_dashboard_exposes_dalli_without_claiming_runtime_data() -> None:
    block = build(count=20, seed=1).block("cadi_call_center_layer")
    assert block.title.startswith("DvSum DALLI")
    assert block.provenance == "assumed"
    assert block.data["status"] == "contract_only"
    assert block.data["live_connection"] is False
    assert block.data["capabilities"] == dalli_contract_rows()
    assert "second source of truth" in block.note


def test_data_contract_marks_the_live_dalli_adapter_as_unwired() -> None:
    panel = next(panel for panel in DATA_CONTRACT if panel.panel == "cadi_call_center_context")
    assert panel.refresh == "per Genesys interaction"
    assert len(panel.requirements) == len(DVSUM_DALLI_CAPABILITIES)
    assert len(panel.blocking) == len(panel.requirements)
    assert all("DvSum DALLI" in requirement.source_system for requirement in panel.requirements)


def test_digital_twin_api_exposes_canonical_and_legacy_routes() -> None:
    client = TestClient(digital_twin_api.app)
    auth = ("demo", "CHANGE_ME")
    canonical = client.get("/api/integrations/dalli", auth=auth)
    former_double_d = client.get("/api/integrations/caddi", auth=auth)
    former_single_d = client.get("/api/integrations/cadi", auth=auth)

    assert canonical.status_code == 200
    assert former_double_d.status_code == 200
    assert former_single_d.status_code == 200
    assert canonical.json() == former_double_d.json() == former_single_d.json()
    assert canonical.json()["layer"] == "DvSum DALLI"


def test_all_three_ui_surfaces_use_the_full_dvsum_dalli_name() -> None:
    control = (ROOT / "src/lpr_cpe_demo/ui/pages/control_tower.py").read_text(
        encoding="utf-8"
    )
    theme = (ROOT / "src/lpr_cpe_demo/ui/theme_dark.py").read_text(encoding="utf-8")
    digital = (
        ROOT / "src/lpr_cpe_demo/digital_twin/streamlit_app.py"
    ).read_text(encoding="utf-8")
    cockpit = (ROOT / "src/lpr_cpe_demo/ui/pages/cockpit.py").read_text(
        encoding="utf-8"
    )

    assert 'dash.block("cadi_call_center_layer")' in control
    assert "DvSum DALLI" in control
    assert 'href="digital-twin?view=dalli"' in theme
    assert '"DvSum DALLI & Genesys"' in digital
    assert "Live DvSum DALLI adapter" in digital
    assert "No live DvSum DALLI adapter is connected" in cockpit


def test_dalli_contract_document_is_explicit_about_stage_boundaries() -> None:
    document = (ROOT / "docs/DVSUM_DALLI_INTEGRATION_CONTRACT.md").read_text(
        encoding="utf-8"
    )
    flattened = " ".join(document.split())
    assert "DvSum DALLI" in document
    assert "second source of truth" in flattened
    assert "Genesys" in document
    assert "24-Hour Install Assurance Watch" in document
    assert "live DvSum DALLI" in document


def test_user_facing_panels_do_not_reintroduce_bare_dali_or_caddi() -> None:
    paths = [
        ROOT / "src/lpr_cpe_demo/dashboard.py",
        ROOT / "src/lpr_cpe_demo/digital_twin/streamlit_app.py",
        ROOT / "src/lpr_cpe_demo/ui/pages/cockpit.py",
        ROOT / "src/lpr_cpe_demo/ui/pages/control_tower.py",
        ROOT / "src/lpr_cpe_demo/ui/theme_dark.py",
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "DvSum DALLI" in text
        assert "DvSum CADDI" not in text
        assert " Dali " not in text
