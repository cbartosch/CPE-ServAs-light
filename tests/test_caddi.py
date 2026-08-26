"""DvSum CADDI is explicit without becoming a second source of truth."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from lpr_cpe_demo.caddi import (
    CADDI_REQUIRED_LINEAGE,
    DVSUM_CADDI_CAPABILITIES,
    caddi_contract,
    caddi_contract_rows,
)
from lpr_cpe_demo.dashboard import build
from lpr_cpe_demo.digital_twin import api as digital_twin_api
from lpr_cpe_demo.telemetry import DATA_CONTRACT

ROOT = Path(__file__).resolve().parents[1]


def _by_key():
    return {capability.key: capability for capability in DVSUM_CADDI_CAPABILITIES}


def test_product_identity_and_scope_are_corrected() -> None:
    contract = caddi_contract()
    assert contract["layer"] == "DvSum CADDI"
    assert contract["vendor"] == "DvSum"
    assert contract["product"] == "CADDI"
    assert contract["expanded_name"] == "Conversational Analytics for Data Driven Insights"
    assert contract["product_scope"] == "Call Center and Network Operations"
    assert contract["declared_lpr_deployment_scope"] == "Call Center via Genesys"
    assert contract["owner_scope"] == "Call Center via Genesys (declared LPR deployment)"
    assert contract["integration_status"] == "contract_only"
    assert contract["live_connection"] is False


def test_nxt_and_genesys_roles_are_explicit_and_distinct() -> None:
    contract = caddi_contract()
    assert "ServAssure NXT collects and normalizes" in contract["nxt_relationship"]
    assert "DvSum CADDI analyzes" in contract["nxt_relationship"]
    assert "Genesys remains the interaction channel" in contract["genesys_relationship"]
    assert contract["presentation_channels"] == ["Genesys"]


def test_caddi_preserves_authoritative_source_systems() -> None:
    contract = caddi_contract()
    policy = contract["source_of_truth_policy"]
    assert "correlate, analyze and recommend" in policy
    assert "remain authoritative" in policy
    for capability in DVSUM_CADDI_CAPABILITIES:
        assert capability.authoritative_sources
        assert "authoritative" in capability.authority_note.lower()


def test_stakeholder_supplied_capabilities_remain_mapped() -> None:
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


def test_product_scope_and_declared_lpr_deployment_are_not_conflated() -> None:
    capabilities = _by_key()
    for key in (
        "outage_pnm",
        "access_device_offline",
        "node_outage_maintenance",
        "premise_modem_history",
        "provisioning",
    ):
        assert "Network Operations" in capabilities[key].product_consumers
        assert capabilities[key].declared_lpr_consumers == ("Call Center",)
        assert capabilities[key].consumers == ("Call Center",)

    boundary = capabilities["maintenance_repair_boundary"]
    assert boundary.coverage == "boundary"
    assert "operational workflow owns execution and closure" in boundary.caddi_role
    assert "remain authoritative" in boundary.authority_note


def test_wifi_gap_and_plume_target_are_explicit() -> None:
    wifi = _by_key()["wifi"]
    assert wifi.coverage == "gap"
    assert wifi.authoritative_sources == ("Plume",)
    assert "not currently available" in wifi.caddi_role.lower()


def test_analytical_lineage_is_mandatory() -> None:
    contract = caddi_contract()
    assert tuple(contract["required_lineage"]) == CADDI_REQUIRED_LINEAGE
    for required in (
        "analytical_record_id",
        "underlying_source_systems",
        "source_record_ids",
        "confidence",
        "authoritative_status_source",
    ):
        assert required in contract["required_lineage"]


def test_dashboard_exposes_caddi_without_claiming_runtime_data() -> None:
    block = build(count=20, seed=1).block("cadi_call_center_layer")
    assert block.provenance == "assumed"
    assert block.data["status"] == "contract_only"
    assert block.data["live_connection"] is False
    assert block.data["capabilities"] == caddi_contract_rows()
    assert "Call Center and Network Operations" in block.note
    assert "declared LPR deployment remains Call Center-facing" in block.note
    assert "second analytical truth" in block.note


def test_data_contract_keeps_stable_identifier_and_count() -> None:
    panel = next(panel for panel in DATA_CONTRACT if panel.panel == "cadi_call_center_context")
    assert panel.refresh == "per Genesys interaction"
    assert len(panel.requirements) == len(DVSUM_CADDI_CAPABILITIES)
    assert len(panel.blocking) == len(panel.requirements)
    assert "blocked" in panel.status
    assert all("DvSum CADDI" in requirement.source_system for requirement in panel.requirements)


def test_digital_twin_api_exposes_canonical_and_legacy_routes() -> None:
    client = TestClient(digital_twin_api.app)
    canonical = client.get("/api/integrations/caddi", auth=("demo", "CHANGE_ME"))
    legacy = client.get("/api/integrations/cadi", auth=("demo", "CHANGE_ME"))
    assert canonical.status_code == 200
    assert legacy.status_code == 200
    assert canonical.json() == legacy.json()
    assert canonical.json()["layer"] == "DvSum CADDI"

    schema = client.get("/openapi.json").json()
    assert schema["paths"]["/api/integrations/cadi"]["get"]["deprecated"] is True
    assert "deprecated" not in schema["paths"]["/api/integrations/caddi"]["get"]


def test_all_ui_surfaces_use_canonical_product_name() -> None:
    control = (
        ROOT / "src/lpr_cpe_demo/ui/pages/control_tower.py"
    ).read_text(encoding="utf-8")
    theme = (ROOT / "src/lpr_cpe_demo/ui/theme_dark.py").read_text(encoding="utf-8")
    digital = (
        ROOT / "src/lpr_cpe_demo/digital_twin/streamlit_app.py"
    ).read_text(encoding="utf-8")
    cockpit = (
        ROOT / "src/lpr_cpe_demo/ui/pages/cockpit.py"
    ).read_text(encoding="utf-8")

    assert 'dash.block("cadi_call_center_layer")' in control
    assert "Declared in DvSum CADDI" in control
    assert 'href="digital-twin?view=caddi"' in theme
    assert '"DvSum CADDI & Genesys"' in digital
    assert "Live CADDI adapter" in digital
    assert "Network Operations" in cockpit
    assert "declared LPR deployment remains Call Center-facing" in cockpit
    assert "No live DvSum CADDI " in cockpit
    assert "adapter is connected." in cockpit


def test_query_alias_preserves_old_bookmarks() -> None:
    source = (
        ROOT / "src/lpr_cpe_demo/digital_twin/streamlit_app.py"
    ).read_text(encoding="utf-8")
    assert '"caddi": "caddi"' in source
    assert '"dvsum-caddi": "caddi"' in source
    assert '"cadi": "caddi"' in source
    assert '"genesys": "caddi"' in source


def test_contract_document_distinguishes_verified_and_lpr_supplied_scope() -> None:
    document = (
        ROOT / "docs/DVSUM_CADDI_INTEGRATION_CONTRACT.md"
    ).read_text(encoding="utf-8")
    assert "What is externally verified" in document
    assert "Declared LPR current-state capability map" in document
    assert "Call Center and Network Operations" in document
    assert "Declared LPR consumer" in document
    assert "does not go to" not in document
    assert "Chuck/VPTO" in document
    assert "ServAssure NXT" in document
    assert "Genesys" in document
    assert "source-system fact" in document
    assert "metric reconciliation between the panels (Stage 2)" in document
    assert "24-Hour Install Assurance Watch (Stage 3)" in document


def test_stage2_semantic_implementation_is_not_present_in_stage1() -> None:
    assert not (ROOT / "src/lpr_cpe_demo/measurement.py").exists()
    assert not (ROOT / "tests/test_measurement_semantics.py").exists()
