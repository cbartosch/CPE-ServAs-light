# ruff: noqa: E501, I001
from __future__ import annotations

import copy
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from lpr_cpe_demo.digital_twin import __version__
from lpr_cpe_demo.digital_twin.decision import (
    SCENARIO_POLICIES,
    deterministic_decision,
    fake_agent_decision,
    reconcile,
    unavailable_agent_decision,
)
from lpr_cpe_demo.digital_twin.models import AgentDecision, GenerationConfig, HumanDecision, SCENARIOS
from lpr_cpe_demo.digital_twin.orchestrator import DATASETS, generate, quality_check
from lpr_cpe_demo.digital_twin.providers import build_structured_client, invoke_structured
from lpr_cpe_demo.digital_twin.storage import derive_run_id, load_jsonl_gz, safe_run_path, sha256_file
from lpr_cpe_demo.digital_twin.workflow import CaseStore


def cfg(**kwargs):
    return GenerationConfig(**kwargs)


def _run(tmp_path: Path, **kwargs):
    return generate(cfg(**kwargs), tmp_path)


def _rows(tmp_path: Path, cat: dict) -> dict[str, list[dict]]:
    p = safe_run_path(tmp_path, cat["run_id"])
    return {name: load_jsonl_gz(p / f"{name}.jsonl.gz") for name in DATASETS}


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def test_01_version():
    assert __version__ == "2.4.0"


def test_02_run_id_stable():
    assert derive_run_id(cfg()) == derive_run_id(cfg())


def test_03_run_id_changes_with_scenarios():
    assert derive_run_id(cfg()) != derive_run_id(cfg(scenarios=("slow_wifi",)))


def test_04_path_traversal_blocked(tmp_path):
    with pytest.raises(ValueError):
        safe_run_path(tmp_path, "../outside")


def test_05_unknown_scenario_rejected():
    with pytest.raises(ValidationError):
        cfg(scenarios=("not_real",))


def test_06_strict_boolean_rejects_false_string():
    with pytest.raises(ValidationError):
        AgentDecision(source="llm", provider_status="ok", recommended_domain="cpe", best_action="collect_evidence", next_best_action="collect_evidence", confidence=0.5, safe_to_automate="false", evidence_ids=["e"], concise_rationale="x")


def test_07_fake_is_not_independent():
    det = deterministic_decision("slow_wifi", ["e1"])
    rec = reconcile(det, fake_agent_decision(det), {"e1"})
    assert rec.independent_model is False and rec.human_review_required is True


def test_08_unavailable_is_not_independent():
    det = deterministic_decision("slow_wifi", ["e1"])
    rec = reconcile(det, unavailable_agent_decision(det), {"e1"})
    assert rec.independent_model is False and rec.human_review_required is True


def test_09_side_effect_requires_human_even_with_real_agreement():
    det = deterministic_decision("slow_wifi", ["e1"])
    agent = AgentDecision(source="llm", provider_status="ok", recommended_domain=det["recommended_domain"], best_action=det["best_action"], next_best_action=det["next_best_action"], confidence=0.95, safe_to_automate=True, evidence_ids=["e1"], concise_rationale="agree")
    assert reconcile(det, agent, {"e1"}).human_review_required is True


def test_10_read_only_real_agreement_can_pass():
    det = deterministic_decision("power_outage", ["e1"])
    agent = AgentDecision(source="llm", provider_status="ok", recommended_domain=det["recommended_domain"], best_action=det["best_action"], next_best_action=det["next_best_action"], confidence=0.95, safe_to_automate=True, evidence_ids=["e1"], concise_rationale="agree")
    rec = reconcile(det, agent, {"e1"})
    assert det["best_action"] == "collect_evidence" and rec.human_review_required is False


def test_11_low_confidence_read_only_fails_closed():
    det = deterministic_decision("power_outage", ["e1"])
    agent = AgentDecision(source="llm", provider_status="ok", recommended_domain=det["recommended_domain"], best_action=det["best_action"], next_best_action=det["next_best_action"], confidence=0.5, safe_to_automate=True, evidence_ids=["e1"], concise_rationale="low")
    assert reconcile(det, agent, {"e1"}).human_review_required is True


def test_12_smoke_has_20_datasets(tmp_path):
    cat = _run(tmp_path)
    assert cat["dataset_count"] == 20 and {d["dataset"] for d in cat["datasets"]} == set(DATASETS)


def test_13_smoke_quality_passes(tmp_path):
    assert _run(tmp_path)["quality"]["passed"] is True


def test_14_master_has_exact_technology_mix(tmp_path):
    cat = _run(tmp_path)
    p = safe_run_path(tmp_path, cat["run_id"])
    rows = load_jsonl_gz(p / "subscriber_master.jsonl.gz")
    counts = {t: sum(r["technology"] == t for r in rows) for t in ("HFC", "GPON", "XGS-PON")}
    assert counts == {"HFC": 300, "GPON": 175, "XGS-PON": 25}


def test_15_pending_action_cannot_be_resolved_or_closed(tmp_path):
    cat = _run(tmp_path)
    rows = _rows(tmp_path, cat)
    inc = {r["case_id"]: r for r in rows["incidents"]}
    work_cases = {r["case_id"] for r in rows["work_orders"]}
    val_cases = {r["case_id"] for r in rows["validation_events"]}
    res_cases = {r["case_id"] for r in rows["resolution_events"]}
    for action in rows["action_events"]:
        if action["status"] == "BLOCKED_PENDING_HUMAN":
            case = action["case_id"]
            assert inc[case]["status"] == "OPEN"
            assert inc[case]["resolved_at"] is None and inc[case]["closed_at"] is None
            assert case not in work_cases and case not in val_cases and case not in res_cases


def test_16_historical_closure_is_after_approval_and_action(tmp_path):
    cat = _run(tmp_path)
    rows = _rows(tmp_path, cat)
    human = {r["case_id"]: r for r in rows["human_decisions"]}
    actions = {r["case_id"]: r for r in rows["action_events"]}
    for incident in rows["incidents"]:
        if incident["status"] != "CLOSED":
            continue
        case = incident["case_id"]
        assert actions[case]["status"] == "SIMULATED_EXECUTED"
        assert human[case]["status"] in {"APPROVED", "NOT_REQUIRED"}
        if human[case]["status"] == "APPROVED":
            assert _dt(human[case]["decided_at"]) <= _dt(actions[case]["event_timestamp"])
        assert _dt(actions[case]["event_timestamp"]) <= _dt(incident["resolved_at"]) <= _dt(incident["closed_at"])


def test_17_remote_and_read_only_branches_do_not_create_truck_rolls(tmp_path):
    cat = _run(tmp_path)
    rows = _rows(tmp_path, cat)
    det = {r["case_id"]: r for r in rows["deterministic_decisions"]}
    work_cases = {r["case_id"] for r in rows["work_orders"]}
    mr_cases = {r["case_id"] for r in rows["mrs"]}
    actions = {r["case_id"]: r for r in rows["action_events"]}
    for case, decision in det.items():
        if actions[case]["status"] == "SIMULATED_EXECUTED" and decision["best_action"] in {"remote_repair", "collect_evidence"}:
            assert case not in work_cases and case not in mr_cases


def test_18_mr_evidence_exists_before_acceptance(tmp_path):
    cat = _run(tmp_path)
    rows = _rows(tmp_path, cat)
    evidence = {}
    for r in rows["telemetry_tr181"]:
        evidence[r["event_id"]] = _dt(r["event_timestamp"])
    for r in rows["nxt_alarms"]:
        evidence[r["event_id"]] = _dt(r["event_timestamp"])
    for r in rows["field_evidence"]:
        evidence[r["evidence_id"]] = _dt(r["captured_at"])
    assert rows["mrs"]
    for mr in rows["mrs"]:
        accepted = _dt(mr["accepted_at"])
        assert all(evidence[eid] <= accepted for eid in mr["evidence_refs"])
        completed = _dt(mr["completed_at"])
        assert all(evidence[eid] <= completed for eid in mr["completion_evidence_refs"])


def test_19_work_and_validation_lifecycle_ordering(tmp_path):
    cat = _run(tmp_path)
    rows = _rows(tmp_path, cat)
    work_by_case = {r["case_id"]: r for r in rows["work_orders"]}
    for wo in rows["work_orders"]:
        assert _dt(wo["dispatched_at"]) <= _dt(wo["arrived_at"]) <= _dt(wo["completed_at"])
    for val in rows["validation_events"]:
        if val["case_id"] in work_by_case:
            assert _dt(work_by_case[val["case_id"]]["completed_at"]) <= _dt(val["event_timestamp"])


def test_20_all_scenarios_have_explicit_truth_and_compatible_technology(tmp_path):
    cat = _run(tmp_path, scenarios=tuple(sorted(SCENARIOS)))
    rows = _rows(tmp_path, cat)
    master = {r["service_id"]: r for r in rows["subscriber_master"]}
    det = {r["case_id"]: r for r in rows["deterministic_decisions"]}
    for manifest in rows["scenario_manifests"]:
        case = manifest["case_id"]
        policy = SCENARIO_POLICIES[manifest["scenario"]]
        assert det[case]["recommended_domain"] == policy["domain"] != "unknown"
        assert det[case]["best_action"] == policy["best_action"]
        assert master[manifest["service_id"]]["technology"] in policy["technologies"]
    assert all(m["technology"] == "HFC" for m in rows["scenario_manifests"] if m["scenario"] == "hfc_ingress")


def test_21_resolution_truth_matches_deterministic_domain(tmp_path):
    cat = _run(tmp_path, scenarios=tuple(sorted(SCENARIOS)))
    rows = _rows(tmp_path, cat)
    det = {r["case_id"]: r for r in rows["deterministic_decisions"]}
    for res in rows["resolution_events"]:
        assert res["fault_domain"] == det[res["case_id"]]["recommended_domain"]


def test_22_operational_volume_scales_with_homes(tmp_path):
    cat_small = _run(tmp_path / "small", profile="full", homes=5_000, scenarios=("slow_wifi", "fiber_cut", "power_outage"), seed=1)
    cat_large = _run(tmp_path / "large", profile="full", homes=10_000, scenarios=("slow_wifi", "fiber_cut", "power_outage"), seed=2)
    def count(cat, name):
        return next(d["row_count"] for d in cat["datasets"] if d["dataset"] == name)
    assert count(cat_small, "telemetry_tr181") >= 500
    assert count(cat_large, "telemetry_tr181") > count(cat_small, "telemetry_tr181")
    assert count(cat_large, "incidents") > count(cat_small, "incidents") > len(cat_small["config"]["scenarios"])


def test_23_quality_gate_catches_p0_mutations(tmp_path):
    cat = _run(tmp_path)
    baseline = _rows(tmp_path, cat)
    assert quality_check(baseline)["passed"] is True

    historical_fiber = next(m["case_id"] for m in baseline["scenario_manifests"] if m["scenario"] == "fiber_cut" and m["lifecycle_mode"].startswith("SYNTHETIC_HISTORY"))
    fiber_work = next(w for w in baseline["work_orders"] if w["case_id"] == historical_fiber)

    mutations = []

    a = copy.deepcopy(baseline)
    next(v for v in a["validation_events"] if v["case_id"] == historical_fiber)["event_timestamp"] = fiber_work["arrived_at"]
    mutations.append(a)

    b = copy.deepcopy(baseline)
    v = next(v for v in b["validation_events"] if v["case_id"] == historical_fiber)
    v["service_test"] = "FAIL"
    v["stable"] = False
    mutations.append(b)

    c = copy.deepcopy(baseline)
    next(r for r in c["resolution_events"] if r["case_id"] == historical_fiber)["resolved_at"] = fiber_work["arrived_at"]
    mutations.append(c)

    d = copy.deepcopy(baseline)
    d["action_events"][0]["production_write"] = True
    mutations.append(d)

    e = copy.deepcopy(baseline)
    e["agent_decisions"][0]["evidence_ids"] = [e["agent_decisions"][1]["evidence_ids"][0]]
    mutations.append(e)

    f = copy.deepcopy(baseline)
    w = next(w for w in f["work_orders"] if w["case_id"] == historical_fiber)
    w["arrived_at"] = "2026-08-21T00:00:00+00:00"
    mutations.append(f)

    g = copy.deepcopy(baseline)
    g["incidents"][1]["incident_id"] = g["incidents"][0]["incident_id"]
    mutations.append(g)

    h = copy.deepcopy(baseline)
    mr = next(m for m in h["mrs"] if m["case_id"] == historical_fiber)
    completion_ev = mr["completion_evidence_refs"][0]
    mr["evidence_refs"].append(completion_ev)
    mutations.append(h)

    assert all(quality_check(mutated)["passed"] is False for mutated in mutations)


def test_24_quality_gate_catches_pending_case_closure(tmp_path):
    cat = _run(tmp_path)
    rows = _rows(tmp_path, cat)
    pending = next(a["case_id"] for a in rows["action_events"] if a["status"] == "BLOCKED_PENDING_HUMAN")
    inc = next(i for i in rows["incidents"] if i["case_id"] == pending)
    inc["status"] = "CLOSED"
    inc["resolved_at"] = inc["opened_at"]
    inc["closed_at"] = inc["opened_at"]
    assert quality_check(rows)["passed"] is False


def test_25_quality_gate_catches_technology_mismatch(tmp_path):
    cat = _run(tmp_path, scenarios=("hfc_ingress",))
    rows = _rows(tmp_path, cat)
    sid = rows["scenario_manifests"][0]["service_id"]
    next(r for r in rows["subscriber_master"] if r["service_id"] == sid)["technology"] = "GPON"
    assert quality_check(rows)["passed"] is False


def test_26_catalog_hashes_are_file_content_hashes(tmp_path):
    cat = _run(tmp_path)
    p = safe_run_path(tmp_path, cat["run_id"])
    assert all(d["sha256"] == sha256_file(p / d["path"]) for d in cat["datasets"])


def test_27_same_config_gzip_hashes_are_reproducible(tmp_path):
    config = cfg()
    cat_a = generate(config, tmp_path / "a")
    cat_b = generate(config, tmp_path / "b")
    hashes_a = {d["dataset"]: d["sha256"] for d in cat_a["datasets"]}
    hashes_b = {d["dataset"]: d["sha256"] for d in cat_b["datasets"]}
    assert hashes_a == hashes_b


def test_28_durable_human_decision_and_simulated_effect(tmp_path):
    store = CaseStore(tmp_path / "cases.sqlite")
    store.create_pending("CASE-X", "remote_repair", ["remote_repair"])
    result = store.decide(HumanDecision(case_id="CASE-X", revision=1, response="approve", actor="demo", rationale="approved for simulation"))
    assert result["state"] == "ACTION_SIMULATED" and result["simulated_effect"]["production_write"] is False
    with pytest.raises(ValueError):
        store.decide(HumanDecision(case_id="CASE-X", revision=1, response="approve", actor="demo", rationale="replay"))


def test_29_auto_execution_only_from_ready_auto(tmp_path):
    store = CaseStore(tmp_path / "cases.sqlite")
    store.create_case("CASE-A", "collect_evidence", ["collect_evidence"], False)
    result = store.auto_execute("CASE-A", "policy")
    assert result["state"] == "ACTION_SIMULATED" and result["simulated_effect"]["authorization"] == "POLICY_AUTO"
    store.create_pending("CASE-B", "collect_evidence", ["collect_evidence"])
    with pytest.raises(ValueError):
        store.auto_execute("CASE-B", "policy")


def test_30_provider_branches_bind_and_invoke(monkeypatch):
    calls = []
    expected = {"source":"llm","provider_status":"ok","recommended_domain":"unknown","best_action":"collect_evidence","next_best_action":"collect_evidence","confidence":0.5,"safe_to_automate":False,"evidence_ids":["e1"],"concise_rationale":"test"}
    class Structured:
        def invoke(self, messages):
            calls.append(("invoke", messages))
            return expected
    class Chat:
        def __init__(self, **kwargs): calls.append(("init", kwargs))
        def with_structured_output(self, schema):
            calls.append(("bind", schema))
            return Structured()
    monkeypatch.setitem(sys.modules, "langchain_openai", types.SimpleNamespace(ChatOpenAI=Chat))
    monkeypatch.setitem(sys.modules, "langchain_anthropic", types.SimpleNamespace(ChatAnthropic=Chat))
    for provider in ("openai", "anthropic"):
        client = build_structured_client(provider, "test-model", "key")
        result = invoke_structured(client, {"evidence_ids":["e1"]})
        assert result.source == "llm"
    assert sum(1 for c in calls if c[0] == "init") == 2
    assert sum(1 for c in calls if c[0] == "bind") == 2
    assert sum(1 for c in calls if c[0] == "invoke") == 2

    flow_calls = []
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("lpr_cpe_demo.digital_twin.orchestrator.build_structured_client", lambda provider, model, api_key: flow_calls.append((provider, model, api_key)) or object())
    def flow_invoke(client, packet):
        flow_calls.append(("invoke-flow", packet["case_id"]))
        return AgentDecision(source="llm", provider_status="ok", recommended_domain="wifi_or_home", best_action="remote_repair", next_best_action="dispatch_clean", confidence=0.9, safe_to_automate=False, evidence_ids=packet["evidence_ids"], concise_rationale="flow test")
    monkeypatch.setattr("lpr_cpe_demo.digital_twin.orchestrator.invoke_structured", flow_invoke)
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        cat = generate(GenerationConfig(profile="smoke", homes=10, scenarios=("slow_wifi",), enable_llm=True, llm_provider="openai", llm_model="test-model"), Path(td))
        assert cat["quality"]["passed"] is True
    assert ("openai", "test-model", "test-key") in flow_calls
    assert any(c[0] == "invoke-flow" for c in flow_calls)


def test_31_independent_audit_mutations_fail_closed(tmp_path):
    cat = _run(tmp_path / "base", scenarios=tuple(sorted(SCENARIOS)))
    baseline = _rows(tmp_path / "base", cat)
    assert quality_check(baseline)["passed"] is True

    historical_fiber = next(
        m["case_id"] for m in baseline["scenario_manifests"]
        if m["scenario"] == "fiber_cut" and m["lifecycle_mode"].startswith("SYNTHETIC_HISTORY")
    )
    fiber_manifest = next(m for m in baseline["scenario_manifests"] if m["case_id"] == historical_fiber)
    fiber_work = next(w for w in baseline["work_orders"] if w["case_id"] == historical_fiber)
    other_service = next(m["service_id"] for m in baseline["scenario_manifests"] if m["service_id"] != fiber_manifest["service_id"])
    other_incident = next(i["incident_id"] for i in baseline["incidents"] if i["incident_id"] != fiber_manifest["root_incident_id"])

    mutations = []

    a = copy.deepcopy(baseline)
    next(m for m in a["mrs"] if m["case_id"] == historical_fiber)["incident_id"] = other_incident
    mutations.append(a)

    b = copy.deepcopy(baseline)
    next(w for w in b["work_orders"] if w["case_id"] == historical_fiber)["service_id"] = other_service
    mutations.append(b)

    c = copy.deepcopy(baseline)
    next(i for i in c["incidents"] if i["incident_id"] == fiber_manifest["root_incident_id"])["service_id"] = other_service
    mutations.append(c)

    d = copy.deepcopy(baseline)
    next(v for v in d["validation_events"] if v["case_id"] == historical_fiber)["incident_id"] = other_incident
    mutations.append(d)

    e = copy.deepcopy(baseline)
    next(r for r in e["resolution_events"] if r["case_id"] == historical_fiber)["incident_id"] = other_incident
    mutations.append(e)

    f = copy.deepcopy(baseline)
    next(v for v in f["validation_events"] if v["case_id"] == historical_fiber)["evidence_refs"] = []
    mutations.append(f)

    g = copy.deepcopy(baseline)
    next(r for r in g["deterministic_decisions"] if r["case_id"] == historical_fiber)["evidence_ids"] = []
    mutations.append(g)

    h = copy.deepcopy(baseline)
    next(r for r in h["agent_decisions"] if r["case_id"] == historical_fiber)["evidence_ids"] = []
    mutations.append(h)

    i = copy.deepcopy(baseline)
    next(r for r in i["action_events"] if r["case_id"] == historical_fiber)["action"] = "collect_evidence"
    mutations.append(i)

    j = copy.deepcopy(baseline)
    next(r for r in j["reconciliation_records"] if r["case_id"] == historical_fiber)["human_review_required"] = False
    human = next(r for r in j["human_decisions"] if r["case_id"] == historical_fiber)
    human.update({"status": "NOT_REQUIRED", "required": False, "response": None, "actor": None, "decided_at": None})
    mutations.append(j)

    k = copy.deepcopy(baseline)
    mr = next(m for m in k["mrs"] if m["case_id"] == historical_fiber)
    mr["created_at"] = (_dt(mr["accepted_at"]) + timedelta(minutes=1)).isoformat()
    mutations.append(k)

    late_mr_rows = copy.deepcopy(baseline)
    mr = next(m for m in late_mr_rows["mrs"] if m["case_id"] == historical_fiber)
    mr["completed_at"] = (_dt(fiber_work["completed_at"]) - timedelta(minutes=1)).isoformat()
    mutations.append(late_mr_rows)

    m = copy.deepcopy(baseline)
    next(x for x in m["mrs"] if x["case_id"] == historical_fiber)["delimiter_id"] = "TAP-999999"
    mutations.append(m)

    assert len(mutations) == 13
    assert all(quality_check(mutated)["passed"] is False for mutated in mutations)

    repeat_cat = _run(tmp_path / "repeat", profile="full", homes=5_000, scenarios=("slow_wifi",), seed=77)
    repeat_rows = _rows(tmp_path / "repeat", repeat_cat)
    repeat_manifest = next(m for m in repeat_rows["scenario_manifests"] if m["repeat_sequence"] > 0)
    parent = next(m for m in repeat_rows["scenario_manifests"] if m["case_id"] == repeat_manifest["repeat_of_case_id"])
    repeat_manifest["event_timestamp"] = (_dt(parent["event_timestamp"]) + timedelta(days=31)).isoformat()
    assert quality_check(repeat_rows)["passed"] is False


def test_32_repeats_share_root_incident_and_require_supervisor(tmp_path):
    cat = _run(tmp_path, profile="full", homes=5_000, scenarios=("slow_wifi",), seed=78)
    rows = _rows(tmp_path, cat)
    incidents_by_case = {i["case_id"]: i for i in rows["incidents"]}
    humans = {h["case_id"]: h for h in rows["human_decisions"]}
    repeats = [m for m in rows["scenario_manifests"] if m["repeat_sequence"] > 0]
    assert repeats
    for repeat in repeats:
        root = next(m for m in rows["scenario_manifests"] if m["case_id"] == repeat["root_case_id"])
        assert repeat["case_id"] not in incidents_by_case
        assert repeat["root_incident_id"] == root["root_incident_id"]
        assert repeat["service_id"] == root["service_id"]
        assert repeat["supervisor_escalation_required"] is True
        assert humans[repeat["case_id"]]["required"] is True
        assert humans[repeat["case_id"]]["supervisor_escalation"] is True
        assert "supervisor" in humans[repeat["case_id"]]["actor"]


def test_33_hard_operating_gates_are_materialized_and_enforced(tmp_path):
    cat = _run(tmp_path, scenarios=("cpe_failure", "no_service", "fiber_cut"))
    rows = _rows(tmp_path, cat)
    historical_swap = next(w for w in rows["work_orders"] if w["work_order_type"] == "CPE_SWAP")
    assert historical_swap["readiness_passed"] is True
    assert historical_swap["skill_confirmed"] is True
    assert historical_swap["parts_confirmed"] is True
    assert historical_swap["access_confirmed"] is True
    assert historical_swap["cpe_available"] is True
    assert historical_swap["precondition_evidence_refs"]
    diag = next(e for e in rows["field_evidence"] if e["evidence_id"] == historical_swap["precondition_evidence_refs"][0])
    assert diag["measurement"] == "cpe_diagnostic_failed" and diag["diagnostic_result"] == "FAIL"
    assert _dt(diag["captured_at"]) < _dt(historical_swap["replacement_started_at"])
    for val in rows["validation_events"]:
        assert val["evidence_refs"]
        assert all(val["closure_checklist"].values())

    bad = copy.deepcopy(rows)
    next(w for w in bad["work_orders"] if w["work_order_type"] == "CPE_SWAP")["precondition_evidence_refs"] = []
    assert quality_check(bad)["passed"] is False
    bad = copy.deepcopy(rows)
    bad["work_orders"][0]["parts_confirmed"] = False
    assert quality_check(bad)["passed"] is False
    bad = copy.deepcopy(rows)
    bad["validation_events"][0]["closure_checklist"]["original_symptom_absent"] = False
    assert quality_check(bad)["passed"] is False


def test_34_live_approval_materializes_action_validation_and_closure(tmp_path):
    from lpr_cpe_demo.digital_twin.orchestrator import materialize_live_decision
    cat = _run(tmp_path, scenarios=("slow_wifi",))
    run_path = safe_run_path(tmp_path, cat["run_id"])
    rows = _rows(tmp_path, cat)
    pending = next(h["case_id"] for h in rows["human_decisions"] if h["status"] == "PENDING")
    store = CaseStore(run_path / "control.sqlite")
    decision = HumanDecision(case_id=pending, revision=1, response="approve", actor="demo", rationale="approve live simulation")
    store_result = store.decide(decision, at="2026-08-21T13:00:00+00:00")
    final_state = materialize_live_decision(run_path, decision, store, store_result)
    assert final_state["state"] == "CLOSED_SIMULATED"
    rows_after = _rows(tmp_path, cat)
    assert next(h for h in rows_after["human_decisions"] if h["case_id"] == pending)["status"] == "APPROVED"
    assert next(a for a in rows_after["action_events"] if a["case_id"] == pending)["status"] == "SIMULATED_EXECUTED"
    assert any(v["case_id"] == pending for v in rows_after["validation_events"])
    assert any(r["case_id"] == pending for r in rows_after["resolution_events"])
    assert quality_check(rows_after)["passed"] is True
    updated_catalog = __import__("json").loads((run_path / "catalog.json").read_text())
    assert updated_catalog["quality"]["passed"] is True
    assert all(d["sha256"] == sha256_file(run_path / d["path"]) for d in updated_catalog["datasets"])


def test_35_concurrent_same_run_is_idempotent_and_interrupted_run_recovers(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    config = cfg(profile="full", homes=2_000, scenarios=("slow_wifi", "fiber_cut"), seed=91)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: generate(config, tmp_path), range(4)))
    assert len({r["run_id"] for r in results}) == 1
    assert all(r["quality"]["passed"] for r in results)

    root2 = tmp_path / "recovery"
    run_id = derive_run_id(config)
    broken = safe_run_path(root2, run_id)
    broken.mkdir(parents=True)
    (broken / "partial.tmp").write_text("incomplete")
    recovered = generate(config, root2)
    assert recovered["quality"]["passed"] is True
    assert not (safe_run_path(root2, run_id) / "partial.tmp").exists()


def test_36_api_returns_4xx_for_invalid_run_and_unsupported_format(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import lpr_cpe_demo.digital_twin.api as api
    monkeypatch.setattr(api, "DATA_ROOT", tmp_path)
    client = TestClient(api.app)
    auth = ("demo", "CHANGE_ME")
    assert client.get("/api/runs/not-a-run", auth=auth).status_code == 400
    response = client.post("/api/runs", auth=auth, json={"config": {"output_format": "parquet"}})
    assert response.status_code == 422


def test_37_docker_image_prepares_writable_data_root():
    dockerfile = (Path(__file__).parents[1] / "docker" / "Dockerfile.digital-twin").read_text()
    assert "mkdir -p /data" in dockerfile
    assert "chown -R lpr:lpr /app /data" in dockerfile



def test_38_case_store_releases_sqlite_before_directory_publish(tmp_path):
    """Windows must be able to publish a run directory after CaseStore I/O."""
    import os
    from lpr_cpe_demo.digital_twin.workflow import CaseStore

    run_path = tmp_path / "build"
    store = CaseStore(run_path / "control.sqlite")
    store.create_pending("CASE-WINDOWS-LOCK", "collect_evidence", ["collect_evidence"])

    published_path = tmp_path / "published"
    os.replace(run_path, published_path)
    assert (published_path / "control.sqlite").exists()



def test_39_bundle_targets_python_3_14_2():
    root = Path(__file__).parents[1]
    pyproject = (root / "pyproject.toml").read_text()
    dockerfile = (root / "docker" / "Dockerfile.digital-twin").read_text()
    assert 'requires-python = ">=3.14.2,<3.14.3"' in pyproject
    assert 'ARG BASE_IMAGE=python:3.14.2-slim-bookworm' in dockerfile
    assert 'FROM ${BASE_IMAGE}' in dockerfile


def test_40_atomic_replace_retries_transient_permission_error(tmp_path, monkeypatch):
    """A transient Windows-style lock must not fail run publication."""
    import lpr_cpe_demo.digital_twin.storage as storage

    source = tmp_path / "source"
    source.mkdir()
    (source / "control.sqlite").write_text("x")
    destination = tmp_path / "published"

    real_replace = storage.os.replace
    calls = {"count": 0}

    def flaky_replace(src, dst):
        calls["count"] += 1
        if calls["count"] == 1:
            raise PermissionError(13, "transient lock")
        return real_replace(src, dst)

    monkeypatch.setattr(storage.os, "replace", flaky_replace)
    monkeypatch.setattr(storage.time, "sleep", lambda _: None)
    storage.replace_with_retry(source, destination, attempts=3)

    assert calls["count"] == 2
    assert (destination / "control.sqlite").exists()


def test_41_host_ruff_contract_is_packaged():
    root = Path(__file__).parents[1]
    pyproject = (root / "pyproject.toml").read_text()
    assert 'target-version = "py314"' in pyproject
    assert 'line-length = 100' in pyproject
    assert 'select = ["E", "F", "I", "B", "UP", "RUF"]' in pyproject
    long_line_modules = [
        "api.py",
        "decision.py",
        "orchestrator.py",
        "providers.py",
        "streamlit_app.py",
        "workflow.py",
    ]
    for name in long_line_modules:
        first = (root / "src" / "lpr_cpe_demo" / "digital_twin" / name).read_text().splitlines()[0]
        assert first == "# ruff: noqa: E501"
    assert (root / "tests" / "test_digital_twin_p0.py").read_text().splitlines()[0] == "# ruff: noqa: E501, I001"


def test_42_predictive_and_care_datasets_are_correlated(tmp_path):
    cat = _run(tmp_path, scenarios=("slow_wifi", "fiber_cut", "power_outage"))
    rows = _rows(tmp_path, cat)
    assert cat["quality"]["checks"] == 20
    assert rows["predictive_modem_pulls"]
    assert rows["predictive_tickets"]
    assert len(rows["care_tickets"]) == len(rows["contacts"])
    assert len(rows["care_ticket_reviews"]) == len(rows["care_tickets"])
    matched = [ticket for ticket in rows["care_tickets"] if ticket["predictive_match"]]
    assert matched
    predictive = {ticket["ticket_id"]: ticket for ticket in rows["predictive_tickets"]}
    for care in matched:
        pred = predictive[care["predictive_ticket_id"]]
        assert pred["service_id"] == care["service_id"]
        assert _dt(pred["opened_at"]) <= _dt(care["opened_at"])
        assert care["correlation_disposition"] == "ATTACH_TO_PREDICTIVE_ROOT_INCIDENT"
        assert care["duplicate_incident_suppressed"] is True


def test_43_on_demand_predictive_scan_is_immutable_and_idempotent(tmp_path):
    from lpr_cpe_demo.digital_twin.orchestrator import load_predictive_scan, run_predictive_scan

    cat = _run(tmp_path, homes=500, scenarios=("fiber_cut", "slow_wifi"))
    run_path = safe_run_path(tmp_path, cat["run_id"])
    catalog_before = (run_path / "catalog.json").read_bytes()
    first = run_predictive_scan(run_path, population=200, days=14, day_index=0)
    second = run_predictive_scan(run_path, population=200, days=14, day_index=0)
    assert first == second
    assert first["scanned"] >= 200
    assert first["tickets"] > 0
    detail = load_predictive_scan(run_path, first["scan_id"], limit=500)
    assert detail["tickets"]
    assert detail["pulls"]
    assert (run_path / "catalog.json").read_bytes() == catalog_before


def test_44_predictive_and_care_api_surfaces(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import lpr_cpe_demo.digital_twin.api as api

    monkeypatch.setattr(api, "DATA_ROOT", tmp_path)
    cat = _run(tmp_path, homes=500, scenarios=("fiber_cut", "slow_wifi"))
    client = TestClient(api.app)
    auth = ("demo", "CHANGE_ME")
    scan = client.post(
        f"/api/runs/{cat['run_id']}/predictive/scans",
        auth=auth,
        json={"population": 200, "days": 14, "day_index": 0},
    )
    assert scan.status_code == 200
    scan_id = scan.json()["scan_id"]
    detail = client.get(
        f"/api/runs/{cat['run_id']}/predictive/scans/{scan_id}?limit=50",
        auth=auth,
    )
    assert detail.status_code == 200 and detail.json()["tickets"]
    queue = client.get(
        f"/api/runs/{cat['run_id']}/care/tickets?predictive_match=true",
        auth=auth,
    )
    assert queue.status_code == 200 and queue.json()["rows"]
    care_id = queue.json()["rows"][0]["care_ticket_id"]
    care = client.get(f"/api/runs/{cat['run_id']}/care/tickets/{care_id}", auth=auth)
    assert care.status_code == 200
    body = care.json()
    assert body["review"] is not None and body["predictive"] is not None


def test_45_live_approval_updates_linked_care_ticket(tmp_path):
    from lpr_cpe_demo.digital_twin.orchestrator import materialize_live_decision

    cat = _run(tmp_path, scenarios=("slow_wifi",))
    run_path = safe_run_path(tmp_path, cat["run_id"])
    rows = _rows(tmp_path, cat)
    pending = next(h["case_id"] for h in rows["human_decisions"] if h["status"] == "PENDING")
    care_before = next(ticket for ticket in rows["care_tickets"] if ticket["case_id"] == pending)
    assert care_before["status"] == "OPEN"
    store = CaseStore(run_path / "control.sqlite")
    decision = HumanDecision(
        case_id=pending,
        revision=1,
        response="approve",
        actor="demo",
        rationale="approve linked care workflow",
    )
    store_result = store.decide(decision, at="2026-08-21T13:00:00+00:00")
    materialize_live_decision(run_path, decision, store, store_result)
    rows_after = _rows(tmp_path, cat)
    care_after = next(ticket for ticket in rows_after["care_tickets"] if ticket["case_id"] == pending)
    assert care_after["status"] == "CLOSED"
    assert care_after["closed_at"] is not None
    assert quality_check(rows_after)["passed"] is True


def test_46_quality_gate_catches_predictive_care_corruption(tmp_path):
    cat = _run(tmp_path, scenarios=("fiber_cut", "slow_wifi"))
    rows = _rows(tmp_path, cat)

    bad = copy.deepcopy(rows)
    matched = next(ticket for ticket in bad["care_tickets"] if ticket["predictive_match"])
    matched["service_id"] = "SVC-9999999"
    assert quality_check(bad)["passed"] is False

    bad = copy.deepcopy(rows)
    review = bad["care_ticket_reviews"][0]
    review["deterministic_action"] = "wrong_action"
    assert quality_check(bad)["passed"] is False

    bad = copy.deepcopy(rows)
    pred = bad["predictive_tickets"][0]
    pred["findings"] = []
    assert quality_check(bad)["passed"] is False


def test_47_digital_twin_docker_supports_verified_corporate_tls():
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "docker" / "Dockerfile.digital-twin").read_text()
    compose = (root / "docker-compose.yml").read_text()
    env_example = (root / ".env.example").read_text()
    assert "ARG BASE_IMAGE=python:3.14.2-slim-bookworm" in dockerfile
    assert "COPY docker/certs/" in dockerfile
    assert "update-ca-certificates" in dockerfile
    assert "PIP_CERT=/etc/ssl/certs/ca-certificates.crt" in dockerfile
    assert "ARG PIP_INDEX_URL=" in dockerfile
    assert "PIP_INDEX_URL: ${PIP_INDEX_URL:-}" in compose
    assert "BASE_IMAGE: ${DT_BASE_IMAGE:-python:3.14.2-slim-bookworm}" in compose
    assert "DT_BASE_IMAGE=python:3.14.2-slim-bookworm" in env_example
    assert "PIP_INDEX_URL=" in env_example

def test_48_predictive_bridge_uses_py314_collections_abc_imports():
    root = Path(__file__).resolve().parents[1]
    source = (root / "src" / "lpr_cpe_demo" / "digital_twin" / "predictive_bridge.py").read_text()
    assert "from collections.abc import Iterable, Sequence" in source
    assert "from typing import Iterable, Sequence" not in source


def test_49_streamlit_run_id_propagates_and_recovers_latest():
    root = Path(__file__).resolve().parents[1]
    source = (root / "src" / "lpr_cpe_demo" / "digital_twin" / "streamlit_app.py").read_text()
    assert "RUN_STATE_KEYS = (" in source
    for key in ("predictive_run", "care_run", "data_run", "sub_run", "decision_run"):
        assert f'"{key}"' in source
    assert "for key in RUN_STATE_KEYS:" in source
    assert 'result = _request("/api/runs")' in source
    assert 'if remembered and not str(st.session_state.get(key, "")).strip():' in source
    assert 'remembered = _latest_run_id()' in source


def test_50_streamlit_module_is_safe_to_embed_in_main_ui():
    root = Path(__file__).resolve().parents[1]
    source = (root / "src" / "lpr_cpe_demo" / "digital_twin" / "streamlit_app.py").read_text()
    assert 'if __name__ == "__main__":' in source
    assert source.rstrip().endswith('if __name__ == "__main__":\n    render()')
    compile(source, "streamlit_app.py", "exec")


def test_51_unified_compose_has_one_ui_and_both_apis():
    import yaml

    root = Path(__file__).resolve().parents[1]
    compose = yaml.safe_load((root / "docker-compose.yml").read_text())
    services = compose["services"]
    assert {"postgres", "mcp-sim", "api", "digital-twin-api", "ui"}.issubset(services)
    assert "digital-twin-ui" not in services
    ui = services["ui"]
    assert ui["environment"]["DT_API_URL"] == "http://digital-twin-api:8001"
    assert "digital-twin-api" in ui["depends_on"]
    assert any("8501" in str(port) for port in ui["ports"])
    assert not any("8502" in str(port) for port in ui["ports"])
    assert "lpr-dt-data" in compose["volumes"]


def test_52_main_ui_integration_exposes_digital_twin_page():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src" / "lpr_cpe_demo" / "ui" / "app.py").read_text()
    page = (root / "src" / "lpr_cpe_demo" / "ui" / "pages" / "digital_twin.py").read_text()
    assert "digital_twin," in app
    assert 'title="Predictive & Customer Care"' in app
    assert 'url_path="digital-twin"' in app
    assert "from lpr_cpe_demo.digital_twin.streamlit_app import render as render_digital_twin" in page
    assert "render_digital_twin()" in page


def test_53_executive_theme_is_packaged_and_applied():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src" / "lpr_cpe_demo" / "ui" / "app.py").read_text()
    theme = (root / "integration" / "executive_theme.py").read_text()
    style = (root / "src" / "lpr_cpe_demo" / "digital_twin" / "executive_style.py").read_text()
    assert "executive_theme" in app
    assert "executive_theme.css()" in app
    assert "Service Assurance Command Center" in app
    assert '"Executive": [' in app
    assert 'title="Predictive & Customer Care"' in app
    assert "from lpr_cpe_demo.digital_twin.executive_style import css" in theme
    assert "--lpr-navy" in style
    assert ".lpr-exec-hero" in style
    assert "[data-testid=\"stSidebar\"]" in style
    compile(theme, "executive_theme.py", "exec")
    compile(style, "executive_style.py", "exec")


def test_54_digital_twin_has_executive_first_information_architecture():
    root = Path(__file__).resolve().parents[1]
    source = (root / "src" / "lpr_cpe_demo" / "digital_twin" / "streamlit_app.py").read_text()
    assert "Predict before the call. Resolve once." in source
    assert '"Executive View"' in source
    assert '"Create Demo"' in source
    assert '"Predictive Health"' in source
    assert '"Customer Experience"' in source
    assert '"Subscriber Story"' in source
    assert '"Decisions & Controls"' in source
    assert '"Evidence & Audit"' in source
    assert source.index('"Executive View"') < source.index('"Create Demo"')
    assert "Executive demo talk track" in source


def test_55_executive_view_uses_business_kpis_and_progressive_disclosure():
    root = Path(__file__).resolve().parents[1]
    source = (root / "src" / "lpr_cpe_demo" / "digital_twin" / "streamlit_app.py").read_text()
    for label in (
        "Homes modeled",
        "Service risks found",
        "Care contacts pre-correlated",
        "Duplicate incidents avoided",
        "Cases closed",
        "Network saw it first",
        "Governed decision",
    ):
        assert label in source
    assert "Technical evidence & reconciliation" in source
    assert "Advanced model & simulation settings" in source
    assert "Evidence explorer" in source
    assert "Technical generation record" in source


def test_56_executive_ui_preserves_governance_and_simulation_disclosures():
    root = Path(__file__).resolve().parents[1]
    source = (root / "src" / "lpr_cpe_demo" / "digital_twin" / "streamlit_app.py").read_text()
    app = (root / "src" / "lpr_cpe_demo" / "ui" / "app.py").read_text()
    assert "Production writes off" in source
    assert "deterministic controls" in source.lower()
    assert "objective restoration evidence" in source
    assert "simulation" in app.lower()
    assert "production writes disabled" in app.lower()


def test_62_create_run_persists_active_run_across_api_reads(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from lpr_cpe_demo.digital_twin import api

    monkeypatch.setattr(api, "DATA_ROOT", tmp_path)
    client = TestClient(api.app)
    auth = ("demo", "CHANGE_ME")
    created = client.post(
        "/api/runs",
        auth=auth,
        json={"config": {"homes": 90, "seed": 901, "scenarios": ["fiber_cut"]}},
    )
    assert created.status_code == 200
    run_id = created.json()["run_id"]

    active = client.get("/api/active-run", auth=auth)
    assert active.status_code == 200
    assert active.json()["run_id"] == run_id

    # The pointer is durable state under DATA_ROOT, not process-local state.
    second_client = TestClient(api.app)
    active_again = second_client.get("/api/active-run", auth=auth)
    assert active_again.status_code == 200
    assert active_again.json()["run_id"] == run_id


def test_63_active_run_can_switch_and_executive_projection_follows_it(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from lpr_cpe_demo.digital_twin import api

    monkeypatch.setattr(api, "DATA_ROOT", tmp_path)
    client = TestClient(api.app)
    auth = ("demo", "CHANGE_ME")
    first = client.post(
        "/api/runs",
        auth=auth,
        json={"config": {"homes": 90, "seed": 901, "scenarios": ["fiber_cut"]}},
    ).json()
    second = client.post(
        "/api/runs",
        auth=auth,
        json={"config": {"homes": 130, "seed": 1301, "scenarios": ["hfc_ingress"]}},
    ).json()
    assert client.get("/api/active-run", auth=auth).json()["run_id"] == second["run_id"]

    switched = client.put(
        "/api/active-run",
        auth=auth,
        json={"run_id": first["run_id"]},
    )
    assert switched.status_code == 200
    assert switched.json()["run_id"] == first["run_id"]

    projection = client.get("/api/executive-projection", auth=auth)
    assert projection.status_code == 200
    assert projection.json()["run_id"] == first["run_id"]


def test_64_executive_projection_joins_predictive_care_incident_and_governance(tmp_path):
    from lpr_cpe_demo.digital_twin.executive_projection import build_executive_projection

    cat = _run(
        tmp_path,
        homes=500,
        scenarios=("fiber_cut", "slow_wifi", "power_outage"),
    )
    projection = build_executive_projection(tmp_path, cat["run_id"])
    assert projection["run_id"] == cat["run_id"]
    assert projection["stories"]
    assert projection["scorecard"]["care_contacts_total"] > 0

    matched = next(story for story in projection["stories"] if story["predictive_match"])
    assert matched["care_ticket"]["service_id"] == matched["service_id"]
    assert matched["predictive_ticket"]["service_id"] == matched["service_id"]
    assert matched["root_incident"]["incident_id"] == matched["incident_id"]
    governance = matched["governance"]
    assert governance["deterministic_decision"] is not None
    assert governance["agent_decision"] is not None
    assert governance["reconciliation"] is not None
    assert governance["action"] is not None


def test_67_active_run_storage_recovers_from_latest_catalog(tmp_path):
    from lpr_cpe_demo.digital_twin.storage import get_active_run, set_active_run

    first = _run(tmp_path, homes=90, seed=901, scenarios=("fiber_cut",))
    second = _run(tmp_path, homes=130, seed=1301, scenarios=("hfc_ingress",))

    assert set_active_run(tmp_path, first["run_id"]) == first["run_id"]
    assert get_active_run(tmp_path) == first["run_id"]

    pointer = tmp_path / "active_run.json"
    pointer.write_text('{"run_id":"RUN-19990101-AAAAAAAAAAAAAAAAAAAA"}\n', encoding="utf-8")

    first_catalog = safe_run_path(tmp_path, first["run_id"]) / "catalog.json"
    second_catalog = safe_run_path(tmp_path, second["run_id"]) / "catalog.json"
    first_stat = first_catalog.stat()
    second_stat = second_catalog.stat()
    newer_ns = max(first_stat.st_mtime_ns, second_stat.st_mtime_ns) + 1_000_000_000
    import os

    os.utime(second_catalog, ns=(newer_ns, newer_ns))
    assert get_active_run(tmp_path) == second["run_id"]
    assert pointer.exists()
