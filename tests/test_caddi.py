"""DvSum CADDI is explicit without becoming a second source of truth.

The filename remains for compatibility with the Stage 1 review command. New
code and user-facing copy use CADDI; CADDI/CADI remain API and import aliases.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from lpr_cpe_demo.caddi import (
    CADDI_REQUIRED_LINEAGE,
    DVSUM_CADDI_CAPABILITIES,
    caddi_contract,
    caddi_contract_rows,
)
from lpr_cpe_demo.cadi import (
    CADI_CAPABILITIES,
    cadi_contract,
    cadi_contract_rows,
)
from lpr_cpe_demo.dashboard import build
from lpr_cpe_demo.digital_twin import api as digital_twin_api
from lpr_cpe_demo.telemetry import DATA_CONTRACT

ROOT = Path(__file__).resolve().parents[1]


def _by_key() -> dict[str, object]:
    return {capability.key: capability for capability in DVSUM_CADDI_CAPABILITIES}


def test_caddi_is_the_canonical_contract_only_layer() -> None:
    contract = caddi_contract()
    assert contract["layer"] == "DvSum CADDI"
    assert contract["product"] == "CADDI"
    assert contract["expanded_name"] == "Conversational Analytics for Data Driven Insights"
    assert contract["integration_status"] == "contract_only"
    assert contract["live_connection"] is False
    assert contract["preferred_pattern"] == "augment_or_federate"
    assert contract["replacement_policy"] == "selective_only_after_joint_discovery"
    assert contract["compatibility"]["canonical_route"] == "/api/integrations/caddi"


def test_legacy_cadi_import_returns_the_caddi_contract() -> None:
    canonical = caddi_contract()
    assert cadi_contract() == canonical
    assert cadi_contract_rows() == caddi_contract_rows()
    assert CADI_CAPABILITIES == DVSUM_CADDI_CAPABILITIES


def test_caddi_preserves_authoritative_source_systems() -> None:
    policy = caddi_contract()["source_of_truth_policy"]
    assert "originating" in policy.lower()
    assert "remain authoritative" in policy.lower()
    for capability in DVSUM_CADDI_CAPABILITIES:
        assert capability.authoritative_sources
        assert "authoritative" in capability.authority_note.lower()
        assert capability.caddi_role
        assert capability.cadi_role == capability.caddi_role


def test_stakeholder_supplied_caddi_capabilities_are_mapped() -> None:
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
    assert "not currently available" in wifi.caddi_role.lower()


def test_maintenance_and_repair_remain_an_operations_boundary() -> None:
    boundary = _by_key()["maintenance_repair_boundary"]
    assert boundary.coverage == "boundary"
    assert "operational workflow owns execution and closure" in boundary.caddi_role.lower()
    contract = caddi_contract()
    assert "operational workflow remains authoritative" in contract["operations_boundary"].lower()


def test_required_analytical_lineage_is_explicit() -> None:
    contract = caddi_contract()
    assert set(CADDI_REQUIRED_LINEAGE) == set(contract["required_lineage"])
    assert "analytical_record_id" in contract["required_lineage"]
    assert "authoritative_status_source" in contract["required_lineage"]


def test_dashboard_exposes_caddi_without_claiming_runtime_data() -> None:
    block = build(count=20, seed=1).block("cadi_call_center_layer")
    assert block.title.startswith("DvSum CADDI")
    assert block.provenance == "assumed"
    assert block.data["status"] == "contract_only"
    assert block.data["live_connection"] is False
    assert block.data["capabilities"] == caddi_contract_rows()
    assert "second source of truth" in block.note


def test_data_contract_marks_the_live_caddi_adapter_as_unwired() -> None:
    panel = next(panel for panel in DATA_CONTRACT if panel.panel == "cadi_call_center_context")
    assert panel.refresh == "per Genesys interaction"
    assert len(panel.requirements) == len(DVSUM_CADDI_CAPABILITIES)
    assert len(panel.blocking) == len(panel.requirements)
    assert all("DvSum CADDI" in requirement.source_system for requirement in panel.requirements)


def test_digital_twin_api_exposes_canonical_and_legacy_routes() -> None:
    client = TestClient(digital_twin_api.app)
    auth = ("demo", "CHANGE_ME")
    canonical = client.get("/api/integrations/caddi", auth=auth)
    former_single_d = client.get("/api/integrations/cadi", auth=auth)

    assert canonical.status_code == 200
    assert former_single_d.status_code == 200
    assert canonical.json() == former_single_d.json()
    assert canonical.json()["layer"] == "DvSum CADDI"


def test_all_three_ui_surfaces_use_the_full_dvsum_caddi_name() -> None:
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
    assert "DvSum CADDI" in control
    assert 'href="digital-twin?view=caddi"' in theme
    assert '"DvSum CADDI & Genesys"' in digital
    assert "Live DvSum CADDI adapter" in digital
    assert "No live DvSum CADDI adapter is connected" in cockpit


def test_caddi_contract_document_is_explicit_about_stage_boundaries() -> None:
    document = (ROOT / "docs/DVSUM_CADDI_INTEGRATION_CONTRACT.md").read_text(
        encoding="utf-8"
    )
    flattened = " ".join(document.split())
    assert "DvSum CADDI" in document
    assert "second source of truth" in flattened
    assert "Genesys" in document
    assert "24-Hour Install Assurance Watch" in document
    assert "live DvSum CADDI" in document


def test_user_facing_panels_use_only_the_canonical_product_name() -> None:
    paths = [
        ROOT / "src/lpr_cpe_demo/dashboard.py",
        ROOT / "src/lpr_cpe_demo/digital_twin/streamlit_app.py",
        ROOT / "src/lpr_cpe_demo/ui/pages/cockpit.py",
        ROOT / "src/lpr_cpe_demo/ui/pages/control_tower.py",
        ROOT / "src/lpr_cpe_demo/ui/theme_dark.py",
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "DvSum CADDI" in text
        obsolete = "dal" + "li"
        assert obsolete.lower() not in text.lower()
