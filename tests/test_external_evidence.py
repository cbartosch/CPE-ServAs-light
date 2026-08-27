from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from types import ModuleType

import pytest

from lpr_cpe_demo.digital_twin.external_evidence import (
    add_csv_content,
    analyze_import_batch,
    build_external_scenario_projection,
    create_import_batch,
    csv_template,
    external_evidence_contract,
    get_import_batch,
    materialize_import_batch,
    safe_batch_path,
    validate_import_batch,
)


def _csv_row(*values: str) -> str:
    return ",".join(values) + "\n"


IDENTITY = csv_template("identity_map") + _csv_row(
    "SVC-0001234",
    "CUST-0001234",
    "ACCT-0001234",
    "PREM-0001234",
    "CPE-0001234",
    "LPR2400001234",
    "02:4c:00:04:d2:12",
    "HFC",
    "TAP",
    "TAP-000155",
    "HFC-HUB-0003-PORT-0210",
    "NODE-0098",
    "2026-08-01T00:00:00Z",
    "",
)
NXT_TELEMETRY = csv_template("nxt_telemetry") + _csv_row(
    "NXT-TEL-884021",
    "2026-08-27T08:21:00Z",
    "SVC-0001234",
    "CPE-0001234",
    "HFC",
    "TAP-000155",
    "NODE-0098",
    "upstream_tx_dbmv",
    "55.8",
    "dBmV",
    "GOOD",
    "EXT-1",
)
NXT_ALARMS = csv_template("nxt_alarms") + _csv_row(
    "NXT-AEV-00091",
    "NXT-ALM-0182",
    "2026-08-27T08:22:00Z",
    "RAISED",
    "MAJOR",
    "SVC-0001234",
    "CPE-0001234",
    "HFC",
    "NODE-0098",
    "TAP-000155",
    "UPSTREAM_INSTABILITY",
    "Repeated upstream impairment",
    "18",
    "false",
    "NXT-SRC-91",
)
DALLI = csv_template("dvsum_dalli_insights") + _csv_row(
    "DALLI-0001",
    "2026-08-27T08:34:00Z",
    "SVC-0001234",
    "",
    "",
    "access_impairment",
    "hfc_tap",
    "0.86",
    "PLANT",
    "attach_to_existing_mr",
    "NXT",
    "NXT-TEL-884021|NXT-AEV-00091",
    "FRESH",
    "DALLI-1",
    "NXT",
)
GENESYS = csv_template("genesys_interactions") + _csv_row(
    "GEN-000992",
    "2026-08-27T09:04:00Z",
    "2026-08-27T09:16:00Z",
    "CUST-0001234",
    "SVC-0001234",
    "VOICE",
    "BROADBAND_TECH",
    "INTERMITTENT_SERVICE",
    "NETWORK_TICKET_LINKED",
    "false",
    "AGENT-024",
    "Customer reports repeated drops",
    "negative",
    "ATTACHED_TO_EXISTING_CASE",
)
JTRACK = csv_template("jtrack_events") + _csv_row(
    "JTRK-EVT-1231",
    "MR-00077",
    "2026-08-27T08:50:00Z",
    "ACCEPTED",
    "INC-0009",
    "SVC-0001234",
    "WO-001",
    "TAP",
    "TAP-000155",
    "NODE-0098",
    "PLANT",
    "P2",
    "true",
    "Inspect serving tap",
    "",
    "OPEN",
    "0",
    "JTRK-SRC-1231",
)
INSTALL = csv_template("install_cohort") + _csv_row(
    "WO-INSTALL-0088",
    "SVC-0001234",
    "CPE-0001234",
    "NEW_INSTALL",
    "2026-08-27T08:00:00Z",
    "TECH-011",
    "PASSED",
    "true",
    "1G_HFC",
    "WFM",
)


def _complete_batch(
    tmp_path: Path,
    *,
    as_of: str | None = None,
    mode: str | None = None,
) -> str:
    batch = create_import_batch(
        tmp_path,
        mode=mode or ("point_in_time" if as_of else "historical_replay"),
        name="test evidence",
        as_of=as_of,
    )
    batch_id = batch["batch_id"]
    files = {
        "identity_map": IDENTITY,
        "nxt_telemetry": NXT_TELEMETRY,
        "nxt_alarms": NXT_ALARMS,
        "dvsum_dalli_insights": DALLI,
        "genesys_interactions": GENESYS,
        "jtrack_events": JTRACK,
        "install_cohort": INSTALL,
    }
    for source, content in files.items():
        add_csv_content(
            tmp_path,
            batch_id,
            source_type=source,
            filename=f"{source}.csv",
            content=content,
        )
    return batch_id


def test_external_evidence_contract_is_read_only_and_names_dvsum_dalli():
    contract = external_evidence_contract()
    assert contract["production_writes"] is False
    assert contract["llm"]["cannot_execute_actions"] is True
    assert "DvSum DALLI" in contract["sources"]["dvsum_dalli_insights"]["label"]
    assert contract["source_aliases"]["caddi"] == "dvsum_dalli_insights"
    assert csv_template("dalli").startswith("insight_id,generated_at")


def test_batch_validates_correlates_and_preserves_lineage(tmp_path):
    batch_id = _complete_batch(tmp_path)
    report = validate_import_batch(tmp_path, batch_id)
    assert report["accepted_rows"] == 7
    assert report["quarantined_rows"] == 0
    assert report["issue_counts"]["ERROR"] == 0
    detail = get_import_batch(tmp_path, batch_id)
    assert detail["correlation_report"]["service_count"] == 1
    assert detail["timeline"]["returned"] == 6
    assert detail["manifest"]["production_writes"] is False
    raw_files = list(safe_batch_path(tmp_path, batch_id).joinpath("raw").glob("*.csv"))
    assert len(raw_files) == 7


def test_fake_agent_triangulates_and_action_remains_blocked(tmp_path):
    batch_id = _complete_batch(tmp_path)
    validate_import_batch(tmp_path, batch_id)
    analysis = analyze_import_batch(
        tmp_path,
        batch_id,
        enable_llm=True,
        llm_provider="fake",
    )
    assert analysis["agent_invocation"]["provider_status"] == "synthetic_offline_agent"
    assert analysis["agent_invocation"]["attempted_external_call"] is False
    recommendation = analysis["reconciled_recommendations"][0]
    assert recommendation["authoritative_recommendation"]["action"] == "attach_to_existing_mr"
    assert recommendation["production_write"] is False
    assert recommendation["execution_permitted"] is False
    assert analysis["action_execution"] is False


def test_missing_real_provider_credentials_fails_closed_to_offline_agent(tmp_path, monkeypatch):
    batch_id = _complete_batch(tmp_path)
    validate_import_batch(tmp_path, batch_id)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    analysis = analyze_import_batch(
        tmp_path,
        batch_id,
        enable_llm=True,
        llm_provider="openai",
        llm_model="test-model",
    )
    invocation = analysis["agent_invocation"]
    assert invocation["attempted_external_call"] is False
    assert invocation["completed"] is False
    assert invocation["provider_status"].startswith("unavailable_missing_")
    assert analysis["deterministic_quality_gate_authoritative"] is True


def test_identity_conflict_quarantines_the_source_record(tmp_path):
    batch = create_import_batch(tmp_path)
    add_csv_content(
        tmp_path,
        batch["batch_id"],
        source_type="identity_map",
        filename="identity.csv",
        content=IDENTITY,
    )
    mismatched = NXT_TELEMETRY.replace(
        "CPE-0001234,HFC,TAP-000155",
        "CPE-0001234,GPON,ODP-999999",
    )
    add_csv_content(
        tmp_path,
        batch["batch_id"],
        source_type="nxt_telemetry",
        filename="nxt.csv",
        content=mismatched,
    )
    report = validate_import_batch(tmp_path, batch["batch_id"])
    codes = {issue["code"] for issue in report["issues"]}
    assert "TECHNOLOGY_MISMATCH" in codes
    assert "DELIMITER_ID_MISMATCH" in codes
    assert report["quarantined_rows"] >= 1


def test_point_in_time_replay_excludes_future_records_from_timeline(tmp_path):
    batch_id = _complete_batch(tmp_path, as_of="2026-08-27T08:30:00Z")
    report = validate_import_batch(tmp_path, batch_id)
    assert "FUTURE_EVIDENCE_EXCLUDED" in {issue["code"] for issue in report["issues"]}
    timeline = get_import_batch(tmp_path, batch_id)["timeline"]["events"]
    assert all(event["event_at"] <= "2026-08-27T08:30:00Z" for event in timeline)
    assert not any(event["source_type"] == "genesys_interactions" for event in timeline)
    analysis = analyze_import_batch(tmp_path, batch_id, llm_provider="fake")
    recommendation = analysis["deterministic_recommendations"][0]
    assert recommendation["recommended_action"] == "expanded_rf_diagnostics"
    assert recommendation["existing_mr_ids"] == []


def test_missing_dalli_evidence_reference_is_visible(tmp_path):
    batch_id = _complete_batch(tmp_path)
    batch_path = safe_batch_path(tmp_path, batch_id)
    dalli_path = next((batch_path / "raw").glob("dvsum_dalli_insights__*.csv"))
    content = dalli_path.read_text(encoding="utf-8").replace(
        "NXT-TEL-884021|NXT-AEV-00091",
        "NXT-TEL-884021|MISSING-RECORD",
    )
    add_csv_content(
        tmp_path,
        batch_id,
        source_type="dvsum_dalli_insights",
        filename="dalli.csv",
        content=content,
        replace=True,
    )
    report = validate_import_batch(tmp_path, batch_id)
    assert "DALLI_EVIDENCE_REFERENCE_MISSING" in {
        issue["code"] for issue in report["issues"]
    }


def test_formula_prefix_is_flagged_without_mutating_raw_file(tmp_path):
    batch = create_import_batch(tmp_path)
    add_csv_content(
        tmp_path,
        batch["batch_id"],
        source_type="identity_map",
        filename="identity.csv",
        content=IDENTITY,
    )
    dangerous = GENESYS.replace("Customer reports repeated drops", "=HYPERLINK(\"x\")")
    add_csv_content(
        tmp_path,
        batch["batch_id"],
        source_type="genesys_interactions",
        filename="genesys.csv",
        content=dangerous,
    )
    report = validate_import_batch(tmp_path, batch["batch_id"])
    assert "CSV_FORMULA_PREFIX" in {issue["code"] for issue in report["issues"]}
    raw = next(safe_batch_path(tmp_path, batch["batch_id"]).joinpath("raw").glob("genesys*.csv"))
    assert "=HYPERLINK" in raw.read_text(encoding="utf-8")


def test_batch_paths_and_duplicate_uploads_fail_closed(tmp_path):
    with pytest.raises(ValueError):
        safe_batch_path(tmp_path, "../../escape")
    batch = create_import_batch(tmp_path)
    add_csv_content(
        tmp_path,
        batch["batch_id"],
        source_type="identity_map",
        filename="identity.csv",
        content=IDENTITY,
    )
    with pytest.raises(FileExistsError):
        add_csv_content(
            tmp_path,
            batch["batch_id"],
            source_type="identity_map",
            filename="identity2.csv",
            content=IDENTITY,
        )


def test_materialized_overlay_does_not_change_canonical_catalog(tmp_path):
    run_id = "RUN-20260827-AAAAAAAAAAAAAAAAAAAA"
    run_path = tmp_path / run_id
    run_path.mkdir()
    catalog = b'{"run_id":"RUN-20260827-AAAAAAAAAAAAAAAAAAAA"}\n'
    (run_path / "catalog.json").write_bytes(catalog)
    before = hashlib.sha256((run_path / "catalog.json").read_bytes()).hexdigest()
    batch_id = _complete_batch(tmp_path)
    validate_import_batch(tmp_path, batch_id)
    analyze_import_batch(tmp_path, batch_id, llm_provider="fake")
    scenario = materialize_import_batch(tmp_path, batch_id, run_id=run_id)
    after = hashlib.sha256((run_path / "catalog.json").read_bytes()).hexdigest()
    assert before == after
    assert scenario["canonical_run_unchanged"] is True
    assert scenario["production_writes"] is False
    assert (run_path / "external_evidence" / batch_id / "scenario.json").exists()



def test_install_watch_projection_uses_external_evidence_without_mutating_run(tmp_path):
    batch_id = _complete_batch(
        tmp_path,
        as_of="2026-08-28T09:12:00Z",
        mode="install_watch",
    )
    validate_import_batch(tmp_path, batch_id)
    analyze_import_batch(tmp_path, batch_id, llm_provider="fake")
    projection = build_external_scenario_projection(tmp_path, batch_id)
    assert projection["mode"] == "install_watch"
    assert projection["metrics"]["services"] == 1
    service = projection["services"][0]
    assert service["service_id"] == "SVC-0001234"
    assert service["lifecycle_state"] == "PROMOTED_TO_INCIDENT"
    assert service["health_state"] == "RED"
    assert service["recommended_action"] == "attach_to_existing_mr"
    assert projection["action_execution"] is False

def test_external_evidence_api_round_trip(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from lpr_cpe_demo.digital_twin import api

    monkeypatch.setattr(api, "DATA_ROOT", tmp_path)
    client = TestClient(api.app)
    auth = ("demo", "CHANGE_ME")
    created = client.post(
        "/api/import-batches",
        auth=auth,
        json={"mode": "historical_replay", "name": "api test"},
    )
    assert created.status_code == 200
    batch_id = created.json()["batch_id"]
    for source, content in {
        "identity_map": IDENTITY,
        "nxt_telemetry": NXT_TELEMETRY,
        "dvsum_dalli_insights": DALLI,
        "genesys_interactions": GENESYS,
        "jtrack_events": JTRACK,
        "install_cohort": INSTALL,
    }.items():
        uploaded = client.post(
            f"/api/import-batches/{batch_id}/files/{source}",
            auth=auth,
            json={"filename": f"{source}.csv", "content": content},
        )
        assert uploaded.status_code == 200
    validated = client.post(f"/api/import-batches/{batch_id}/validate", auth=auth, json={})
    assert validated.status_code == 200
    analyzed = client.post(
        f"/api/import-batches/{batch_id}/analyze",
        auth=auth,
        json={"enable_llm": True, "llm_provider": "fake", "max_services": 5},
    )
    assert analyzed.status_code == 200
    assert analyzed.json()["action_execution"] is False
    projection = client.get(f"/api/import-batches/{batch_id}/projection", auth=auth)
    assert projection.status_code == 200
    assert projection.json()["metrics"]["services"] == 1
    detail = client.get(f"/api/import-batches/{batch_id}", auth=auth)
    assert detail.status_code == 200
    assert detail.json()["recommendation_report"]["analysis_id"]


def test_external_evidence_ui_exposes_upload_validation_and_agent():
    root = Path(__file__).resolve().parents[1]
    source = (
        root / "src" / "lpr_cpe_demo" / "digital_twin" / "streamlit_app.py"
    ).read_text(encoding="utf-8")
    assert '"External Evidence"' in source
    assert "st.file_uploader" in source
    assert "Validate, normalize and correlate" in source
    assert "Analyze and triangulate evidence" in source
    assert "DvSum DALLI" in source
    assert "deterministic quality and policy branch remains authoritative" in source


def test_openai_agent_path_invokes_structured_triangulation_without_network(
    tmp_path,
    monkeypatch,
):
    from lpr_cpe_demo.digital_twin.external_evidence import TriangulationAgentResult

    batch_id = _complete_batch(tmp_path)
    validate_import_batch(tmp_path, batch_id)
    captured: dict[str, object] = {}

    class FakeStructured:
        def invoke(self, messages):
            captured["messages"] = messages
            return TriangulationAgentResult(
                summary="Provider triangulation completed.",
                validated_facts=["NXT and JTrack reference the same service."],
                inconsistencies=[],
                missing_evidence=[],
                recommendations=[],
                overall_confidence=0.8,
                requires_human_review=True,
            )

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

        def with_structured_output(self, schema):
            captured["schema"] = schema
            return FakeStructured()

    fake_module = ModuleType("langchain_openai")
    fake_module.ChatOpenAI = FakeClient
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_module)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    analysis = analyze_import_batch(
        tmp_path,
        batch_id,
        enable_llm=True,
        llm_provider="openai",
        llm_model="test-model",
    )
    invocation = analysis["agent_invocation"]
    assert invocation["attempted_external_call"] is True
    assert invocation["completed"] is True
    assert invocation["provider_status"] == "accepted"
    assert captured["schema"] is TriangulationAgentResult
    messages = captured["messages"]
    assert isinstance(messages, list)
    assert "prompt-injection" in messages[0][1]
    provider_payload = messages[1][1]
    assert "Customer reports repeated drops" not in provider_payload
    assert "AGENT-024" not in provider_payload
    assert "CUST-0001234" not in provider_payload
    assert analysis["action_execution"] is False



def test_each_analysis_is_preserved_with_provider_status(tmp_path):
    batch_id = _complete_batch(tmp_path)
    validate_import_batch(tmp_path, batch_id)
    first = analyze_import_batch(tmp_path, batch_id, llm_provider="fake")
    second = analyze_import_batch(
        tmp_path,
        batch_id,
        enable_llm=False,
        llm_provider="disabled",
    )
    assert first["analysis_id"] != second["analysis_id"]
    batch_path = safe_batch_path(tmp_path, batch_id)
    assert (batch_path / "analyses" / f"{first['analysis_id']}.json").exists()
    assert (batch_path / "analyses" / f"{second['analysis_id']}.json").exists()
    manifest = get_import_batch(tmp_path, batch_id)["manifest"]
    assert len(manifest["analysis_history"]) == 2
    assert manifest["analysis"]["analysis_id"] == second["analysis_id"]

def test_missing_identity_map_rejects_analysis(tmp_path):
    batch = create_import_batch(tmp_path)
    add_csv_content(
        tmp_path,
        batch["batch_id"],
        source_type="nxt_telemetry",
        filename="nxt.csv",
        content=NXT_TELEMETRY,
    )
    report = validate_import_batch(tmp_path, batch["batch_id"])
    assert report["status"] == "REJECTED"
    with pytest.raises(ValueError, match="failed deterministic validation"):
        analyze_import_batch(tmp_path, batch["batch_id"], llm_provider="fake")


def test_physically_implausible_nxt_value_is_quarantined(tmp_path):
    batch = create_import_batch(tmp_path)
    add_csv_content(
        tmp_path,
        batch["batch_id"],
        source_type="identity_map",
        filename="identity.csv",
        content=IDENTITY,
    )
    bad = NXT_TELEMETRY.replace(",55.8,dBmV,", ",999.0,dBmV,")
    add_csv_content(
        tmp_path,
        batch["batch_id"],
        source_type="nxt_telemetry",
        filename="nxt.csv",
        content=bad,
    )
    report = validate_import_batch(tmp_path, batch["batch_id"])
    assert "NXT_VALUE_PHYSICALLY_IMPLAUSIBLE" in {
        issue["code"] for issue in report["issues"]
    }
    assert report["quarantined_rows"] == 1


def test_replacement_preserves_raw_revision_and_materialized_batch_is_locked(tmp_path):
    batch_id = _complete_batch(tmp_path)
    batch_path = safe_batch_path(tmp_path, batch_id)
    before = sorted(path.name for path in (batch_path / "raw").glob("*.csv"))
    add_csv_content(
        tmp_path,
        batch_id,
        source_type="nxt_telemetry",
        filename="nxt-revised.csv",
        content=NXT_TELEMETRY.replace("55.8", "54.9"),
        replace=True,
    )
    after = sorted(path.name for path in (batch_path / "raw").glob("*.csv"))
    assert len(after) == len(before) + 1
    validate_import_batch(tmp_path, batch_id)
    analyze_import_batch(tmp_path, batch_id, llm_provider="fake")
    materialize_import_batch(tmp_path, batch_id)
    with pytest.raises(ValueError, match="materialized import batches are immutable"):
        validate_import_batch(tmp_path, batch_id)
    with pytest.raises(ValueError, match="materialized import batches are immutable"):
        analyze_import_batch(tmp_path, batch_id, llm_provider="fake")
    with pytest.raises(ValueError, match="materialized import batches are immutable"):
        add_csv_content(
            tmp_path,
            batch_id,
            source_type="nxt_telemetry",
            filename="late.csv",
            content=NXT_TELEMETRY,
            replace=True,
        )


def test_dalli_stale_and_domain_action_conflicts_are_flagged(tmp_path):
    batch = create_import_batch(tmp_path)
    for source, content in {
        "identity_map": IDENTITY,
        "nxt_telemetry": NXT_TELEMETRY,
        "dvsum_dalli_insights": DALLI.replace(
            "hfc_tap,0.86,PLANT,attach_to_existing_mr",
            "hfc_tap,0.86,PROVISIONING,reprovision",
        ).replace(",FRESH,", ",STALE,"),
    }.items():
        add_csv_content(
            tmp_path,
            batch["batch_id"],
            source_type=source,
            filename=f"{source}.csv",
            content=content,
        )
    report = validate_import_batch(tmp_path, batch["batch_id"])
    codes = {issue["code"] for issue in report["issues"]}
    assert "DALLI_INSIGHT_NOT_FRESH" in codes
    assert "DALLI_DOMAIN_ACTION_INCONSISTENT" in codes


def test_dvsum_dalli_domain_is_compared_with_deterministic_recommendation(tmp_path):
    batch = create_import_batch(tmp_path)
    files = {
        "identity_map": IDENTITY,
        "nxt_telemetry": NXT_TELEMETRY,
        "dvsum_dalli_insights": DALLI.replace(",hfc_tap,", ",provisioning,"),
        "jtrack_events": JTRACK,
    }
    for source, content in files.items():
        add_csv_content(
            tmp_path,
            batch["batch_id"],
            source_type=source,
            filename=f"{source}.csv",
            content=content,
        )
    validate_import_batch(tmp_path, batch["batch_id"])
    analysis = analyze_import_batch(tmp_path, batch["batch_id"], llm_provider="fake")
    deterministic = analysis["deterministic_recommendations"][0]
    assert deterministic["recommended_domain"] == "hfc_tap"
    assert deterministic["dvsum_dalli_domain"] == "provisioning"
    assert deterministic["dvsum_dalli_domain_agreement"] == "DISAGREE"
    assert deterministic["requires_human_review"] is True


def test_cleared_nxt_alarm_does_not_keep_install_watch_red(tmp_path):
    batch = create_import_batch(
        tmp_path,
        mode="install_watch",
        as_of="2026-08-28T10:00:00Z",
    )
    healthy_telemetry = NXT_TELEMETRY.replace("55.8", "45.0")
    alarm_rows = NXT_ALARMS + (
        "NXT-AEV-00092,NXT-ALM-0182,2026-08-27T08:40:00Z,CLEARED,INFO,"
        "SVC-0001234,CPE-0001234,HFC,NODE-0098,TAP-000155,"
        "UPSTREAM_INSTABILITY,Condition cleared,18,false,NXT-SRC-92\n"
    )
    for source, content in {
        "identity_map": IDENTITY,
        "nxt_telemetry": healthy_telemetry,
        "nxt_alarms": alarm_rows,
        "install_cohort": INSTALL,
    }.items():
        add_csv_content(
            tmp_path,
            batch["batch_id"],
            source_type=source,
            filename=f"{source}.csv",
            content=content,
        )
    validate_import_batch(tmp_path, batch["batch_id"])
    analyze_import_batch(tmp_path, batch["batch_id"], llm_provider="fake")
    projection = build_external_scenario_projection(tmp_path, batch["batch_id"])
    service = projection["services"][0]
    assert service["health_state"] == "GREEN"
    assert service["lifecycle_state"] == "PASSED_24H"


def test_malformed_or_extra_csv_columns_are_quarantined_not_server_errors(tmp_path):
    batch = create_import_batch(tmp_path)
    add_csv_content(
        tmp_path,
        batch["batch_id"],
        source_type="identity_map",
        filename="identity.csv",
        content=IDENTITY,
    )
    extra = NXT_TELEMETRY.replace(
        "NXT-TEL-884021,2026",
        "NXT-TEL-884021,unexpected,2026",
    )
    add_csv_content(
        tmp_path,
        batch["batch_id"],
        source_type="nxt_telemetry",
        filename="nxt.csv",
        content=extra,
    )
    report = validate_import_batch(tmp_path, batch["batch_id"])
    assert "EXTRA_CSV_COLUMNS" in {issue["code"] for issue in report["issues"]}
    assert report["quarantined_rows"] >= 1


def test_duplicate_header_aliases_are_reported(tmp_path):
    batch = create_import_batch(tmp_path)
    duplicate = IDENTITY.replace("service_id,customer_id", "service_id,subscriber_id")
    add_csv_content(
        tmp_path,
        batch["batch_id"],
        source_type="identity_map",
        filename="identity.csv",
        content=duplicate,
    )
    report = validate_import_batch(tmp_path, batch["batch_id"])
    assert "DUPLICATE_CANONICAL_COLUMN" in {
        issue["code"] for issue in report["issues"]
    }


def test_invalid_llm_domain_action_and_evidence_fail_closed(tmp_path, monkeypatch):
    from lpr_cpe_demo.digital_twin.external_evidence import TriangulationAgentResult

    batch_id = _complete_batch(tmp_path)
    validate_import_batch(tmp_path, batch_id)

    class FakeStructured:
        def invoke(self, _messages):
            return {
                "summary": "Unsafe model output for regression testing.",
                "validated_facts": [],
                "inconsistencies": [],
                "missing_evidence": [],
                "recommendations": [
                    {
                        "service_id": "SVC-0001234",
                        "recommended_domain": "moon_network",
                        "recommended_action": "delete_everything",
                        "confidence": 0.99,
                        "rationale": "Unsupported output.",
                        "evidence_refs": ["MISSING-REF"],
                        "missing_evidence": [],
                        "requires_human_review": False,
                    }
                ],
                "overall_confidence": 0.99,
                "requires_human_review": False,
            }

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def with_structured_output(self, schema):
            assert schema is TriangulationAgentResult
            return FakeStructured()

    fake_module = ModuleType("langchain_openai")
    fake_module.ChatOpenAI = FakeClient
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_module)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    analysis = analyze_import_batch(
        tmp_path,
        batch_id,
        llm_provider="openai",
        llm_model="test-model",
    )
    codes = {item["code"] for item in analysis["agent_output_validation"]}
    assert "LLM_UNKNOWN_EVIDENCE_REFERENCE" in codes
    assert "LLM_DOMAIN_NOT_ALLOWED" in codes
    assert "LLM_ACTION_NOT_ALLOWED" in codes
    reconciled = analysis["reconciled_recommendations"][0]
    assert reconciled["authoritative_recommendation"]["action"] == "attach_to_existing_mr"
    assert reconciled["human_review_required"] is True
    assert reconciled["execution_permitted"] is False


def test_external_evidence_endpoints_require_authentication(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from lpr_cpe_demo.digital_twin import api

    monkeypatch.setattr(api, "DATA_ROOT", tmp_path)
    client = TestClient(api.app)
    assert client.get("/api/external-evidence/contract").status_code == 401
    assert client.get("/api/import-batches").status_code == 401
