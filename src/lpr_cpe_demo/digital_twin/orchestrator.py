# ruff: noqa: E501
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import time
import uuid
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from itertools import chain
from pathlib import Path

from pydantic import ValidationError

from .care import build_care_records, refresh_care_status
from .decision import (
    SCENARIO_POLICIES,
    deterministic_decision,
    disabled_agent_decision,
    fake_agent_decision,
    reconcile_with_operating_controls,
    unavailable_agent_decision,
)
from .models import AgentDecision, GenerationConfig, HumanDecision
from .predictive_bridge import build_snapshot
from .providers import build_structured_client, invoke_structured
from .storage import (
    atomic_write_jsonl_gz,
    canonical_config,
    derive_run_id,
    iter_jsonl_gz,
    load_jsonl_gz,
    replace_with_retry,
    safe_run_path,
    sha256_file,
    write_jsonl_gz,
)
from .workflow import CaseStore

DATASETS = (
    "subscriber_master",
    "scenario_manifests",
    "telemetry_tr181",
    "nxt_alarms",
    "contacts",
    "incidents",
    "work_orders",
    "field_evidence",
    "mrs",
    "validation_events",
    "resolution_events",
    "deterministic_decisions",
    "agent_decisions",
    "reconciliation_records",
    "human_decisions",
    "action_events",
    "predictive_modem_pulls",
    "predictive_tickets",
    "care_tickets",
    "care_ticket_reviews",
)

REGIONS = ("metro", "coastal", "mountain", "remote_island")
PROFILE_CASE_RATE = {"smoke": 0.0, "preview": 0.005, "board": 0.005, "full": 0.005}
PROFILE_TELEMETRY_RATE = {"smoke": 1.0, "preview": 0.25, "board": 0.10, "full": 0.10}
REPEAT_WINDOW = timedelta(days=30)
CLOSURE_CHECKS = (
    "original_symptom_absent",
    "service_test_passed",
    "telemetry_stable",
    "repair_actions_documented",
    "required_measurements_captured",
)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def _parse_ts(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _technology(i: int, homes: int) -> str:
    frac = (i + 0.5) / homes
    if frac <= 0.60:
        return "HFC"
    if frac <= 0.95:
        return "GPON"
    return "XGS-PON"


def _subscriber(i: int, homes: int) -> dict:
    tech = _technology(i, homes)
    sid = f"SVC-{i+1:07d}"
    delimiter = "TAP" if tech == "HFC" else "ODP"
    return {
        "customer_id": f"CUST-{i+1:07d}",
        "service_account_id": f"ACCT-{i+1:07d}",
        "premise_id": f"PREM-{i+1:07d}",
        "service_id": sid,
        "device_id": f"CPE-{i+1:07d}",
        "serial_number": f"LPR{2400000000+i:010d}",
        "mac_address": f"02:4c:{(i>>16)&255:02x}:{(i>>8)&255:02x}:{i&255:02x}:{(i*17)&255:02x}",
        "technology": tech,
        "region": REGIONS[i % len(REGIONS)],
        "delimiter_type": delimiter,
        "delimiter_id": f"{delimiter}-{(i//8)+1:06d}",
        "access_port_id": f"{tech}-HUB-{(i//512)+1:04d}-PORT-{(i%512)+1:04d}",
    }


def _agent_decision(config: GenerationConfig, deterministic: dict, evidence_packet: dict):
    if config.llm_provider == "fake":
        return fake_agent_decision(deterministic)
    if config.llm_provider == "disabled" or not config.enable_llm:
        return disabled_agent_decision(deterministic)
    provider = config.llm_provider
    key_name = "OPENAI_API_KEY" if provider == "openai" else "ANTHROPIC_API_KEY"
    api_key = os.getenv(key_name)
    if not api_key or not config.llm_model:
        return unavailable_agent_decision(deterministic)
    try:
        client = build_structured_client(provider, config.llm_model, api_key)
        return invoke_structured(client, evidence_packet)
    except Exception:
        return unavailable_agent_decision(deterministic)


def _case_count(config: GenerationConfig) -> int:
    minimum = len(config.scenarios) * 2
    if config.profile == "smoke":
        return minimum
    return max(minimum, round(config.homes * PROFILE_CASE_RATE[config.profile]))


def _telemetry_count(config: GenerationConfig) -> int:
    return max(1, min(config.homes, math.ceil(config.homes * PROFILE_TELEMETRY_RATE[config.profile])))


def _predictive_count(config: GenerationConfig, total_cases: int) -> int:
    if not config.enable_predictive:
        return 0
    requested = config.predictive_population
    if requested > 0:
        return min(config.homes, max(total_cases, requested))
    return min(config.homes, max(total_cases, min(_telemetry_count(config), 20_000)))


def _predictive_subscribers(
    config: GenerationConfig,
    total_cases: int,
    case_subscribers: dict[str, dict],
) -> list[dict]:
    target = _predictive_count(config, total_cases)
    if target == 0:
        return []
    selected = dict(case_subscribers)
    for index in _sample_indices(config.homes, target, config.seed + 47):
        sub = _subscriber(index, config.homes)
        selected.setdefault(sub["service_id"], sub)
        if len(selected) >= target:
            break
    return list(selected.values())[:target]


def _coprime_step(n: int, seed: int) -> int:
    if n <= 1:
        return 1
    step = 7919 + (abs(seed) % 997)
    while math.gcd(step, n) != 1:
        step += 1
    return step


def _sample_indices(homes: int, count: int, seed: int):
    start = abs(seed) % homes
    step = _coprime_step(homes, seed)
    for n in range(count):
        yield (start + n * step) % homes


def _compatible_subscriber(homes: int, scenario: str, token: int) -> tuple[int, dict]:
    allowed = SCENARIO_POLICIES[scenario]["technologies"]
    start = abs(token) % homes
    for offset in range(homes):
        i = (start + offset) % homes
        if _technology(i, homes) in allowed:
            return i, _subscriber(i, homes)
    raise ValueError(f"no subscriber technology compatible with scenario {scenario!r}")


def _background_telemetry(config: GenerationConfig, base: datetime):
    for i in _sample_indices(config.homes, _telemetry_count(config), config.seed + 31):
        sub = _subscriber(i, config.homes)
        event_time = base - timedelta(minutes=30) + timedelta(seconds=i % 1800)
        yield {
            "event_id": f"TEL-BG-{sub['service_id']}",
            "case_id": None,
            "service_id": sub["service_id"],
            "event_timestamp": _iso(event_time),
            "collection_timestamp": _iso(event_time + timedelta(seconds=30)),
            "technology": sub["technology"],
            "health": "HEALTHY",
            "scenario": "baseline",
        }


def _base_case(
    scenario: str,
    sub: dict,
    idx: int,
    base: datetime,
    *,
    root_case_id: str | None = None,
    root_incident_id: str | None = None,
    repeat_of_case_id: str | None = None,
    repeat_sequence: int = 0,
) -> dict:
    case_id = f"CASE-{idx+1:07d}-{scenario.upper()}"
    is_repeat = root_case_id is not None
    root_case_id = root_case_id or case_id
    root_incident_id = root_incident_id or f"INC-{root_case_id}"
    t0 = base + timedelta(minutes=idx * 2)
    t_alarm = t0 + timedelta(minutes=2)
    t_contact = t_alarm + timedelta(minutes=2)
    t_ticket = t_contact + timedelta(minutes=1)
    tele_pre = f"TEL-{case_id}-PRE"
    alarm = f"ALM-{case_id}"
    contact = f"CON-{case_id}"
    manifest = {
        "scenario": scenario,
        "case_id": case_id,
        "root_case_id": root_case_id,
        "root_incident_id": root_incident_id,
        "service_id": sub["service_id"],
        "technology": sub["technology"],
        "delimiter_type": sub["delimiter_type"],
        "delimiter_id": sub["delimiter_id"],
        "event_timestamp": _iso(t0),
        "repeat_of_case_id": repeat_of_case_id,
        "repeat_sequence": repeat_sequence,
        "supervisor_escalation_required": is_repeat,
    }
    incident = None
    if not is_repeat:
        incident = {
            "incident_id": root_incident_id,
            "case_id": root_case_id,
            "root_case_id": root_case_id,
            "service_id": sub["service_id"],
            "opened_at": _iso(t_ticket),
            "resolved_at": None,
            "closed_at": None,
            "status": "OPEN",
            "root_scenario": scenario,
            "repeat_count": 0,
            "reopen_count": 0,
            "last_repeat_at": None,
            "last_reopened_at": None,
            "prior_closed_at": None,
        }
    return {
        "scenario": manifest,
        "tele_pre": {
            "event_id": tele_pre,
            "case_id": case_id,
            "service_id": sub["service_id"],
            "event_timestamp": _iso(t0),
            "collection_timestamp": _iso(t0 + timedelta(seconds=30)),
            "technology": sub["technology"],
            "health": "DEGRADED",
            "scenario": scenario,
        },
        "alarm": {
            "event_id": alarm,
            "case_id": case_id,
            "service_id": sub["service_id"],
            "event_timestamp": _iso(t_alarm),
            "collection_timestamp": _iso(t_alarm + timedelta(seconds=20)),
            "alarm_family": "NETWORK_OR_CPE_DEGRADATION",
            "severity": "MAJOR",
        },
        "contact": {
            "contact_id": contact,
            "case_id": case_id,
            "root_case_id": root_case_id,
            "incident_id": root_incident_id,
            "service_id": sub["service_id"],
            "contact_timestamp": _iso(t_contact),
            "channel": "VOICE",
            "repeat_contact": is_repeat,
            "repeat_of_case_id": repeat_of_case_id,
            "repeat_sequence": repeat_sequence,
        },
        "incident_seed": incident,
        "incident": incident,
        "sub": sub,
        "t_ticket": t_ticket,
        "diagnosis_completed_at": t_ticket + timedelta(minutes=4),
    }


def _required_skill(action: str, sub: dict) -> str:
    if action == "cpe_swap":
        return "CPE_SWAP_CERTIFIED"
    if action == "dispatch_clean":
        return "CLEAN_BOOTS_CERTIFIED"
    if action in {"create_mr", "plant_repair"}:
        return "HFC_PLANT" if sub["technology"] == "HFC" else "PON_PLANT"
    return "REMOTE_ASSURANCE"


def _parts_required(action: str) -> list[str]:
    if action == "cpe_swap":
        return ["replacement_cpe", "premise_test_kit"]
    if action == "dispatch_clean":
        return ["drop_repair_kit", "premise_test_kit"]
    if action in {"create_mr", "plant_repair"}:
        return ["plant_test_kit", "repair_materials"]
    return []


def _work_order(
    *,
    case: dict,
    action: str,
    work_order_id: str,
    work_order_type: str,
    crew_domain: str,
    action_time: datetime,
    dispatched_at: datetime,
    arrived_at: datetime,
    completed_at: datetime,
) -> dict:
    manifest = case["scenario"]
    sub = case["sub"]
    diagnosis = case["diagnosis_completed_at"]
    readiness = max(diagnosis + timedelta(minutes=1), action_time + timedelta(seconds=30))
    assigned = readiness + timedelta(seconds=30)
    required_skill = _required_skill(action, sub)
    return {
        "work_order_id": work_order_id,
        "incident_id": manifest["root_incident_id"],
        "case_id": manifest["case_id"],
        "root_case_id": manifest["root_case_id"],
        "service_id": sub["service_id"],
        "work_order_type": work_order_type,
        "diagnosis_completed_at": _iso(diagnosis),
        "readiness_checked_at": _iso(readiness),
        "assigned_at": _iso(assigned),
        "dispatched_at": _iso(dispatched_at),
        "arrived_at": _iso(arrived_at),
        "completed_at": _iso(completed_at),
        "crew_domain": crew_domain,
        "required_skill": required_skill,
        "technician_skill": required_skill,
        "skill_confirmed": True,
        "parts_required": _parts_required(action),
        "parts_confirmed": True,
        "access_confirmed": True,
        "cpe_available": True if action == "cpe_swap" else None,
        "readiness_passed": True,
        "repeat_sequence": manifest["repeat_sequence"],
        "supervisor_escalation_confirmed": bool(manifest["supervisor_escalation_required"]),
        "supervisor_actor": "synthetic_senior_supervisor" if manifest["supervisor_escalation_required"] else None,
    }


def _closure_checklist() -> dict[str, bool]:
    return {key: True for key in CLOSURE_CHECKS}


def _materialize_effect(rows: dict[str, list[dict]], case: dict, action: str, action_time: datetime) -> datetime | None:
    """Materialize only records causally downstream of an authorized simulated action."""
    manifest = case["scenario"]
    sub = case["sub"]
    case_id = manifest["case_id"]
    incident = case["incident"]
    if incident is None:
        raise ValueError("materialization requires root incident")
    ticket = manifest["root_incident_id"]
    scenario = manifest["scenario"]
    policy = SCENARIO_POLICIES[scenario]

    validation_field_evidence: list[str] = []
    tele_post_time: datetime | None = None

    if action in {"remote_repair", "collect_evidence"}:
        if action == "collect_evidence":
            return None
        tele_post_time = action_time + timedelta(minutes=10)

    elif action in {"dispatch_clean", "cpe_swap"}:
        wo_id = f"WO-{case_id}"
        t_dispatch = action_time + timedelta(minutes=5)
        t_arrive = t_dispatch + timedelta(minutes=35)
        t_complete = t_arrive + timedelta(minutes=50)
        wo = _work_order(
            case=case,
            action=action,
            work_order_id=wo_id,
            work_order_type="CPE_SWAP" if action == "cpe_swap" else "CLEAN_BOOTS",
            crew_domain="CLEAN",
            action_time=action_time,
            dispatched_at=t_dispatch,
            arrived_at=t_arrive,
            completed_at=t_complete,
        )
        if action == "cpe_swap":
            diag_id = f"EVD-{case_id}-CPE-DIAG"
            t_diag = t_arrive + timedelta(minutes=15)
            replacement_start = t_diag + timedelta(minutes=5)
            swap_id = f"EVD-{case_id}-CPE-SWAP"
            wo["replacement_started_at"] = _iso(replacement_start)
            wo["precondition_evidence_refs"] = [diag_id]
            rows["field_evidence"].append({
                "evidence_id": diag_id,
                "case_id": case_id,
                "root_case_id": manifest["root_case_id"],
                "incident_id": ticket,
                "service_id": sub["service_id"],
                "work_order_id": wo_id,
                "captured_at": _iso(t_diag),
                "delimiter_id": sub["delimiter_id"],
                "measurement": "cpe_diagnostic_failed",
                "diagnostic_result": "FAIL",
                "documented_reason": "Synthetic failed CPE diagnostic authorizes replacement.",
                "photo_ref": f"synthetic://{diag_id}/diagnostic",
            })
            rows["field_evidence"].append({
                "evidence_id": swap_id,
                "case_id": case_id,
                "root_case_id": manifest["root_case_id"],
                "incident_id": ticket,
                "service_id": sub["service_id"],
                "work_order_id": wo_id,
                "captured_at": _iso(t_complete - timedelta(minutes=5)),
                "delimiter_id": sub["delimiter_id"],
                "measurement": "cpe_replacement_completed",
                "diagnostic_result": None,
                "documented_reason": "Replacement completed after failed diagnostic.",
                "photo_ref": f"synthetic://{swap_id}/photo",
            })
            validation_field_evidence.extend([diag_id, swap_id])
        else:
            evidence_id = f"EVD-{case_id}"
            rows["field_evidence"].append({
                "evidence_id": evidence_id,
                "case_id": case_id,
                "root_case_id": manifest["root_case_id"],
                "incident_id": ticket,
                "service_id": sub["service_id"],
                "work_order_id": wo_id,
                "captured_at": _iso(t_complete - timedelta(minutes=5)),
                "delimiter_id": sub["delimiter_id"],
                "measurement": "last_good_first_bad",
                "diagnostic_result": "BOUNDARY_CONFIRMED",
                "documented_reason": "Clean Boots repair and boundary test completed.",
                "photo_ref": f"synthetic://{evidence_id}/photo",
            })
            validation_field_evidence.append(evidence_id)
        rows["work_orders"].append(wo)
        tele_post_time = t_complete + timedelta(minutes=5)

    elif action in {"create_mr", "plant_repair"}:
        mr_id = f"MR-{case_id}"
        t_created = action_time + timedelta(minutes=2)
        t_accepted = t_created + timedelta(minutes=3)
        wo_id = f"WO-{case_id}-PLANT"
        t_dispatch = t_accepted + timedelta(minutes=5)
        t_arrive = t_dispatch + timedelta(minutes=40)
        t_complete = t_arrive + timedelta(minutes=60)
        field_evidence_id = f"EVD-{case_id}-PLANT"
        initial_evidence = [case["tele_pre"]["event_id"], case["alarm"]["event_id"]]
        rows["work_orders"].append(_work_order(
            case=case,
            action=action,
            work_order_id=wo_id,
            work_order_type="PLANT_REPAIR",
            crew_domain="PLANT",
            action_time=action_time,
            dispatched_at=t_dispatch,
            arrived_at=t_arrive,
            completed_at=t_complete,
        ))
        rows["field_evidence"].append({
            "evidence_id": field_evidence_id,
            "case_id": case_id,
            "root_case_id": manifest["root_case_id"],
            "incident_id": ticket,
            "service_id": sub["service_id"],
            "work_order_id": wo_id,
            "captured_at": _iso(t_complete - timedelta(minutes=5)),
            "delimiter_id": sub["delimiter_id"],
            "measurement": "plant_repair_completion",
            "diagnostic_result": "REPAIRED",
            "documented_reason": "Plant repair completed and measured at handoff delimiter.",
            "photo_ref": f"synthetic://{field_evidence_id}/photo",
        })
        rows["mrs"].append({
            "mr_id": mr_id,
            "case_id": case_id,
            "root_case_id": manifest["root_case_id"],
            "incident_id": ticket,
            "service_id": sub["service_id"],
            "work_order_id": wo_id,
            "delimiter_type": sub["delimiter_type"],
            "delimiter_id": sub["delimiter_id"],
            "evidence_refs": initial_evidence,
            "created_at": _iso(t_created),
            "accepted_at": _iso(t_accepted),
            "completion_evidence_refs": [field_evidence_id],
            "completed_at": _iso(t_complete + timedelta(minutes=2)),
        })
        validation_field_evidence.append(field_evidence_id)
        tele_post_time = t_complete + timedelta(minutes=5)

    else:
        raise ValueError(f"unsupported simulated action: {action}")

    if not policy["restores_on_best_action"] or tele_post_time is None:
        return None

    tele_post_id = f"TEL-{case_id}-POST"
    rows["telemetry_tr181"].append({
        "event_id": tele_post_id,
        "case_id": case_id,
        "service_id": sub["service_id"],
        "event_timestamp": _iso(tele_post_time),
        "collection_timestamp": _iso(tele_post_time + timedelta(seconds=30)),
        "technology": sub["technology"],
        "health": "HEALTHY",
        "scenario": scenario,
    })
    t_validate = tele_post_time + timedelta(minutes=10)
    val_id = f"VAL-{case_id}"
    val_evidence = [tele_post_id, *validation_field_evidence]
    rows["validation_events"].append({
        "validation_id": val_id,
        "case_id": case_id,
        "root_case_id": manifest["root_case_id"],
        "incident_id": ticket,
        "service_id": sub["service_id"],
        "event_timestamp": _iso(t_validate),
        "evidence_refs": val_evidence,
        "service_test": "PASS",
        "stable": True,
        "closure_checklist": _closure_checklist(),
        "checklist_completed_at": _iso(t_validate),
        "customer_confirmation": "NOT_REQUIRED_TELEMETRY_SUFFICIENT",
    })
    res_id = f"RES-{case_id}"
    rows["resolution_events"].append({
        "resolution_id": res_id,
        "case_id": case_id,
        "root_case_id": manifest["root_case_id"],
        "incident_id": ticket,
        "service_id": sub["service_id"],
        "resolved_at": _iso(t_validate),
        "validation_ref": val_id,
        "outcome": "RESTORED",
        "fault_domain": policy["domain"],
    })
    t_close = t_validate + timedelta(minutes=5)
    incident["resolved_at"] = _iso(t_validate)
    incident["closed_at"] = _iso(t_close)
    incident["status"] = "CLOSED"
    return t_close


@contextmanager
def _generation_lock(data_root: Path, run_id: str, timeout_seconds: float = 60.0):
    data_root.mkdir(parents=True, exist_ok=True)
    lock_path = data_root / f".{run_id}.lock"
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            lock_path.mkdir()
            break
        except FileExistsError as exc:
            try:
                age = time.time() - lock_path.stat().st_mtime
                if age > 300:
                    shutil.rmtree(lock_path, ignore_errors=True)
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError("generation lock timeout") from exc
            time.sleep(0.05)
    try:
        yield
    finally:
        shutil.rmtree(lock_path, ignore_errors=True)


def _read_catalog(path: Path, config_digest: str) -> dict | None:
    if not path.exists():
        return None
    catalog = json.loads(path.read_text(encoding="utf-8"))
    if catalog.get("config_sha256") != config_digest:
        raise ValueError("immutable run ID collision")
    return catalog


def generate(config: GenerationConfig, data_root: Path) -> dict:
    if config.output_format != "jsonl_gz":
        raise ValueError("P0 offline generator in this bundle supports jsonl_gz; use Docker successor for Parquet")
    data_root = data_root.resolve()
    data_root.mkdir(parents=True, exist_ok=True)
    run_id = derive_run_id(config)
    final_run_path = safe_run_path(data_root, run_id)
    catalog_path = final_run_path / "catalog.json"
    config_digest = hashlib.sha256(canonical_config(config)).hexdigest()
    existing = _read_catalog(catalog_path, config_digest)
    if existing is not None:
        return existing

    with _generation_lock(data_root, run_id):
        existing = _read_catalog(catalog_path, config_digest)
        if existing is not None:
            return existing
        if final_run_path.exists():
            shutil.rmtree(final_run_path)
        build_path = data_root / f".{run_id}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
        build_path.mkdir(parents=False, exist_ok=False)
        try:
            catalog = _generate_into(config, build_path, run_id, config_digest)
            replace_with_retry(build_path, final_run_path)
            return catalog
        except Exception:
            shutil.rmtree(build_path, ignore_errors=True)
            raise


def _generate_into(config: GenerationConfig, run_path: Path, run_id: str, config_digest: str) -> dict:
    base = datetime(config.run_date.year, config.run_date.month, config.run_date.day, 12, 0, tzinfo=UTC)
    rows: dict[str, list[dict]] = {name: [] for name in DATASETS}
    case_store = CaseStore(run_path / "control.sqlite")
    case_subscribers: dict[str, dict] = {}
    scenario_occurrence: Counter[str] = Counter()
    repeat_root_for_scenario: dict[str, tuple[str, str, dict]] = {}
    incident_by_id: dict[str, dict] = {}
    last_attempt_for_root: dict[str, str] = {}
    repeat_count = 0

    total_cases = _case_count(config)
    for idx in range(total_cases):
        scenario = config.scenarios[idx % len(config.scenarios)]
        scenario_occurrence[scenario] += 1
        occurrence = scenario_occurrence[scenario]
        repeat = occurrence > 2 and occurrence % 10 == 0 and scenario in repeat_root_for_scenario

        if repeat:
            root_case_id, root_incident_id, sub = repeat_root_for_scenario[scenario]
            root_incident = incident_by_id[root_incident_id]
            repeat_sequence = int(root_incident.get("repeat_count", 0)) + 1
            repeat_of_case_id = last_attempt_for_root.get(root_case_id, root_case_id)
            case = _base_case(
                scenario,
                sub,
                idx,
                base,
                root_case_id=root_case_id,
                root_incident_id=root_incident_id,
                repeat_of_case_id=repeat_of_case_id,
                repeat_sequence=repeat_sequence,
            )
            case["incident"] = root_incident
            root_incident["repeat_count"] = repeat_sequence
            root_incident["last_repeat_at"] = case["scenario"]["event_timestamp"]
            if root_incident["status"] == "CLOSED":
                root_incident["prior_closed_at"] = root_incident["closed_at"]
                root_incident["resolved_at"] = None
                root_incident["closed_at"] = None
                root_incident["status"] = "OPEN"
                root_incident["reopen_count"] = int(root_incident.get("reopen_count", 0)) + 1
                root_incident["last_reopened_at"] = case["scenario"]["event_timestamp"]
            repeat_count += 1
        else:
            _, sub = _compatible_subscriber(config.homes, scenario, config.seed + idx * 137)
            case = _base_case(scenario, sub, idx, base)
            root_incident = case["incident_seed"]
            assert root_incident is not None
            rows["incidents"].append(root_incident)
            incident_by_id[root_incident["incident_id"]] = root_incident
            if occurrence == 2:
                repeat_root_for_scenario[scenario] = (
                    case["scenario"]["root_case_id"],
                    case["scenario"]["root_incident_id"],
                    sub,
                )

        case_id = case["scenario"]["case_id"]
        last_attempt_for_root[case["scenario"]["root_case_id"]] = case_id
        case_subscribers[sub["service_id"]] = sub
        rows["scenario_manifests"].append(case["scenario"])
        rows["telemetry_tr181"].append(case["tele_pre"])
        rows["nxt_alarms"].append(case["alarm"])
        rows["contacts"].append(case["contact"])

        evidence_ids = [case["tele_pre"]["event_id"], case["alarm"]["event_id"]]
        det = deterministic_decision(scenario, evidence_ids)
        evidence_packet = {
            "case_id": case_id,
            "root_case_id": case["scenario"]["root_case_id"],
            "root_incident_id": case["scenario"]["root_incident_id"],
            "scenario": scenario,
            "technology": sub["technology"],
            "delimiter_type": sub["delimiter_type"],
            "delimiter_id": sub["delimiter_id"],
            "repeat_sequence": case["scenario"]["repeat_sequence"],
            "evidence_ids": evidence_ids,
            "evidence": [case["tele_pre"], case["alarm"]],
            "eligible_actions": det["eligible_actions"],
        }
        agent = _agent_decision(config, det, evidence_packet)
        rec = reconcile_with_operating_controls(
            det,
            agent,
            set(evidence_ids),
            repeat=bool(case["scenario"]["repeat_sequence"]),
        )
        rows["deterministic_decisions"].append({"case_id": case_id, **det})
        rows["agent_decisions"].append({"case_id": case_id, **agent.model_dump()})
        rows["reconciliation_records"].append({"case_id": case_id, **rec.model_dump()})

        t_decision = case["t_ticket"] + timedelta(minutes=5)
        case["diagnosis_completed_at"] = t_decision - timedelta(minutes=1)
        is_live_pending = occurrence == 1 and rec.human_review_required
        if is_live_pending:
            case_store.create_case(case_id, det["best_action"], det["eligible_actions"], True, at=_iso(t_decision))
            rows["human_decisions"].append({
                "case_id": case_id,
                "status": "PENDING",
                "revision": 1,
                "required": True,
                "response": None,
                "actor": None,
                "decided_at": None,
                "rationale": None,
                "source": "live_control",
                "supervisor_escalation": False,
            })
            rows["action_events"].append({
                "case_id": case_id,
                "action": det["best_action"],
                "status": "BLOCKED_PENDING_HUMAN",
                "event_timestamp": _iso(t_decision),
                "production_write": False,
            })
            case["scenario"]["lifecycle_mode"] = "LIVE_PENDING"
            continue

        if rec.human_review_required:
            human_time = t_decision + timedelta(minutes=1)
            is_repeat = bool(case["scenario"]["repeat_sequence"])
            rows["human_decisions"].append({
                "case_id": case_id,
                "status": "APPROVED",
                "revision": 1,
                "required": True,
                "response": "approve",
                "actor": "synthetic_senior_supervisor" if is_repeat else "synthetic_supervisor",
                "decided_at": _iso(human_time),
                "rationale": "Synthetic historical approval under operating controls.",
                "source": "synthetic_history",
                "supervisor_escalation": is_repeat,
            })
            action_time = human_time + timedelta(minutes=1)
            case["scenario"]["lifecycle_mode"] = "SYNTHETIC_HISTORY_APPROVED"
        else:
            action_time = t_decision + timedelta(minutes=1)
            rows["human_decisions"].append({
                "case_id": case_id,
                "status": "NOT_REQUIRED",
                "revision": 1,
                "required": False,
                "response": None,
                "actor": None,
                "decided_at": None,
                "rationale": None,
                "source": "policy_auto",
                "supervisor_escalation": False,
            })
            case["scenario"]["lifecycle_mode"] = "POLICY_AUTO"

        rows["action_events"].append({
            "case_id": case_id,
            "action": det["best_action"],
            "status": "SIMULATED_EXECUTED",
            "event_timestamp": _iso(action_time),
            "production_write": False,
        })
        _materialize_effect(rows, case, det["best_action"], action_time)

    scenario_by_service: dict[str, str] = {}
    for manifest in rows["scenario_manifests"]:
        scenario_by_service.setdefault(manifest["service_id"], manifest["scenario"])
    predictive_subscribers = _predictive_subscribers(config, total_cases, case_subscribers)
    if predictive_subscribers:
        predictive = build_snapshot(
            predictive_subscribers,
            scenario_by_service=scenario_by_service,
            ran_at=base - timedelta(hours=1),
            seed=config.seed,
            days=config.predictive_days,
            scan_id=f"PRED-{run_id}",
        )
        rows["predictive_modem_pulls"] = predictive.pulls
        rows["predictive_tickets"] = predictive.tickets
    else:
        predictive = None

    care_tickets, care_reviews = build_care_records(
        contacts=rows["contacts"],
        manifests=rows["scenario_manifests"],
        incidents=rows["incidents"],
        subscribers=case_subscribers,
        predictive_tickets=rows["predictive_tickets"],
        deterministic=rows["deterministic_decisions"],
        agent=rows["agent_decisions"],
        reconciliation=rows["reconciliation_records"],
    )
    rows["care_tickets"] = care_tickets
    rows["care_ticket_reviews"] = care_reviews

    files: list[dict] = []
    master_path = run_path / "subscriber_master.jsonl.gz"
    master_count = write_jsonl_gz(master_path, (_subscriber(i, config.homes) for i in range(config.homes)))
    files.append({"dataset": "subscriber_master", "path": master_path.name, "row_count": master_count, "sha256": sha256_file(master_path)})

    telemetry_path = run_path / "telemetry_tr181.jsonl.gz"
    telemetry_count = write_jsonl_gz(telemetry_path, chain(_background_telemetry(config, base), rows["telemetry_tr181"]))
    files.append({"dataset": "telemetry_tr181", "path": telemetry_path.name, "row_count": telemetry_count, "sha256": sha256_file(telemetry_path)})

    for name in DATASETS:
        if name in {"subscriber_master", "telemetry_tr181"}:
            continue
        path = run_path / f"{name}.jsonl.gz"
        count = write_jsonl_gz(path, rows[name])
        files.append({"dataset": name, "path": path.name, "row_count": count, "sha256": sha256_file(path)})

    file_by_name = {entry["dataset"]: entry for entry in files}
    files = [file_by_name[name] for name in DATASETS]

    quality_rows = dict(rows)
    quality_rows["subscriber_master"] = list({**case_subscribers, **{s["service_id"]: s for s in predictive_subscribers}}.values())
    quality = quality_check(quality_rows)
    if master_count != config.homes:
        quality["errors"].append("subscriber master count does not match configured homes")
    expected_min_telemetry = _telemetry_count(config) + total_cases
    if telemetry_count < expected_min_telemetry:
        quality["errors"].append("telemetry volume did not scale to configured profile")
    if len(rows["contacts"]) != total_cases:
        quality["errors"].append("case-attempt volume did not scale to configured profile")
    if len(rows["incidents"]) != total_cases - repeat_count:
        quality["errors"].append("root-incident volume disagrees with repeat consolidation")
    quality["passed"] = not quality["errors"]
    quality["scope"] = "canonical case graph, hard operating controls, causal invariants, repeat governance and volume contracts"
    if not quality["passed"]:
        raise ValueError("generated data failed quality gate: " + "; ".join(quality["errors"][:10]))

    catalog = {
        "version": "2.4.0",
        "release": "P0 Fixed R3 Hotfix5.5",
        "run_id": run_id,
        "config": config.model_dump(mode="json"),
        "config_sha256": config_digest,
        "datasets": files,
        "dataset_count": len(files),
        "quality": quality,
        "operational_scale": {
            "homes": config.homes,
            "case_attempts": total_cases,
            "root_incidents": len(rows["incidents"]),
            "repeat_attempts": repeat_count,
            "background_telemetry_rows": _telemetry_count(config),
            "predictive_modems_scanned": 0 if predictive is None else predictive.scanned,
            "predictive_tickets": 0 if predictive is None else len(predictive.tickets),
            "care_tickets": len(rows["care_tickets"]),
            "case_attempt_rate_per_home": total_cases / config.homes,
        },
        "production_writes": False,
    }
    (run_path / "catalog.json").write_text(json.dumps(catalog, indent=2, sort_keys=True), encoding="utf-8")
    return catalog


def run_predictive_scan(
    run_path: Path,
    *,
    population: int,
    days: int,
    day_index: int = 0,
) -> dict:
    """Create an immutable predictive modem-pull artifact under an existing run.

    Canonical run datasets remain unchanged. Each parameter set gets a deterministic
    scan id and its own directory, so an operator can compare predictive pulls
    without changing the evidence that produced the parent run id.
    """
    catalog_path = run_path / "catalog.json"
    if not catalog_path.exists():
        raise ValueError("run not found")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    config = GenerationConfig.model_validate(catalog["config"])
    if population < 1 or population > config.homes:
        raise ValueError(f"population must be between 1 and {config.homes}")
    if days < 7 or days > 60:
        raise ValueError("days must be between 7 and 60")
    if day_index < 0 or day_index > 365:
        raise ValueError("day_index must be between 0 and 365")

    manifests = load_jsonl_gz(run_path / "scenario_manifests.jsonl.gz")
    scenario_by_service: dict[str, str] = {}
    for manifest in manifests:
        scenario_by_service.setdefault(manifest["service_id"], manifest["scenario"])
    case_subscribers = {
        row["service_id"]: row
        for row in _case_master_projection(run_path, manifests)
    }
    target = min(config.homes, max(population, len(case_subscribers)))
    selected = dict(case_subscribers)
    for index in _sample_indices(config.homes, target, config.seed + 83 + day_index):
        sub = _subscriber(index, config.homes)
        selected.setdefault(sub["service_id"], sub)
        if len(selected) >= target:
            break

    payload = json.dumps(
        {"run_id": catalog["run_id"], "population": target, "days": days, "day_index": day_index},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    scan_id = "SCAN-" + hashlib.sha256(payload).hexdigest().upper()[:16]
    root = run_path / "predictive_scans"
    root.mkdir(parents=True, exist_ok=True)
    final = root / scan_id
    summary_path = final / "summary.json"
    if summary_path.exists():
        return json.loads(summary_path.read_text(encoding="utf-8"))

    ran_at = datetime(
        config.run_date.year,
        config.run_date.month,
        config.run_date.day,
        3,
        0,
        tzinfo=UTC,
    ) + timedelta(days=day_index)
    snapshot = build_snapshot(
        list(selected.values())[:target],
        scenario_by_service=scenario_by_service,
        ran_at=ran_at,
        seed=config.seed + day_index * 1009,
        days=days,
        scan_id=scan_id,
    )

    care_rows = load_jsonl_gz(run_path / "care_tickets.jsonl.gz")
    predictive_by_service: dict[str, list[dict]] = defaultdict(list)
    for ticket in snapshot.tickets:
        predictive_by_service[str(ticket["service_id"])].append(ticket)
    matches = 0
    for care in care_rows:
        care_time = _parse_ts(care.get("opened_at"))
        if care_time is None:
            continue
        if any(
            (_parse_ts(ticket.get("opened_at")) or care_time + timedelta(seconds=1)) <= care_time
            for ticket in predictive_by_service.get(str(care.get("service_id")), [])
        ):
            matches += 1

    summary = {
        **snapshot.summary(),
        "canonical_run_id": catalog["run_id"],
        "requested_population": population,
        "effective_population": target,
        "trend_window_days": days,
        "day_index": day_index,
        "care_tickets_correlated": matches,
        "production_writes": False,
    }
    build = root / f".{scan_id}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
    build.mkdir(parents=False, exist_ok=False)
    try:
        write_jsonl_gz(build / "predictive_modem_pulls.jsonl.gz", snapshot.pulls)
        write_jsonl_gz(build / "predictive_tickets.jsonl.gz", snapshot.tickets)
        (build / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        if final.exists():
            shutil.rmtree(final)
        replace_with_retry(build, final)
    except Exception:
        shutil.rmtree(build, ignore_errors=True)
        raise
    return summary


def list_predictive_scans(run_path: Path) -> list[dict]:
    root = run_path / "predictive_scans"
    if not root.exists():
        return []
    result = []
    for path in sorted(root.glob("SCAN-*/summary.json"), reverse=True):
        try:
            result.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return result


def load_predictive_scan(run_path: Path, scan_id: str, *, limit: int = 100) -> dict:
    if not scan_id.startswith("SCAN-") or len(scan_id) != 21 or any(
        char not in "0123456789ABCDEF" for char in scan_id[5:]
    ):
        raise ValueError("invalid scan_id")
    path = run_path / "predictive_scans" / scan_id
    if not path.is_dir():
        raise KeyError(scan_id)
    summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
    return {
        "summary": summary,
        "tickets": load_jsonl_gz(path / "predictive_tickets.jsonl.gz", limit=limit),
        "pulls": load_jsonl_gz(path / "predictive_modem_pulls.jsonl.gz", limit=limit),
    }


def _unique_errors(rows: list[dict], field: str, label: str) -> list[str]:
    values = [r.get(field) for r in rows if r.get(field) is not None]
    return [f"duplicate {label}"] if len(values) != len(set(values)) else []


def _records_by_case(rows: list[dict]) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        case_id = row.get("case_id")
        if case_id is not None:
            result[case_id].append(row)
    return dict(result)


def quality_check(rows: dict[str, list[dict]]) -> dict:
    """Fail closed on graph, policy, operating-control and causal invariants."""
    errors: list[str] = []
    checks = 0

    # 1. Identity uniqueness.
    checks += 1
    for dataset, field, label in (
        ("subscriber_master", "service_id", "service_id"),
        ("scenario_manifests", "case_id", "case_id"),
        ("telemetry_tr181", "event_id", "telemetry event_id"),
        ("nxt_alarms", "event_id", "alarm event_id"),
        ("contacts", "contact_id", "contact_id"),
        ("incidents", "incident_id", "incident_id"),
        ("work_orders", "work_order_id", "work_order_id"),
        ("field_evidence", "evidence_id", "field evidence_id"),
        ("mrs", "mr_id", "mr_id"),
        ("validation_events", "validation_id", "validation_id"),
        ("resolution_events", "resolution_id", "resolution_id"),
        ("deterministic_decisions", "case_id", "deterministic case_id"),
        ("agent_decisions", "case_id", "agent case_id"),
        ("reconciliation_records", "case_id", "reconciliation case_id"),
        ("human_decisions", "case_id", "human case_id"),
        ("action_events", "case_id", "action case_id"),
        ("predictive_modem_pulls", "pull_id", "predictive pull_id"),
        ("predictive_tickets", "ticket_id", "predictive ticket_id"),
        ("care_tickets", "care_ticket_id", "care ticket_id"),
        ("care_ticket_reviews", "care_ticket_id", "care review ticket_id"),
    ):
        errors.extend(_unique_errors(rows.get(dataset, []), field, label))

    master = {r["service_id"]: r for r in rows.get("subscriber_master", [])}
    manifests = {r["case_id"]: r for r in rows.get("scenario_manifests", [])}
    incidents_by_id = {r["incident_id"]: r for r in rows.get("incidents", [])}
    incidents_by_root = {r["case_id"]: r for r in rows.get("incidents", [])}
    deterministic = {r["case_id"]: r for r in rows.get("deterministic_decisions", [])}
    agents = {r["case_id"]: r for r in rows.get("agent_decisions", [])}
    reconciliations = {r["case_id"]: r for r in rows.get("reconciliation_records", [])}
    humans = {r["case_id"]: r for r in rows.get("human_decisions", [])}
    actions = {r["case_id"]: r for r in rows.get("action_events", [])}
    work_by_case = _records_by_case(rows.get("work_orders", []))
    work_by_id = {r["work_order_id"]: r for r in rows.get("work_orders", [])}
    mr_by_case = _records_by_case(rows.get("mrs", []))
    validations = {r["validation_id"]: r for r in rows.get("validation_events", [])}
    validations_by_case = {r["case_id"]: r for r in rows.get("validation_events", [])}
    resolutions_by_case = {r["case_id"]: r for r in rows.get("resolution_events", [])}
    resolutions_by_incident: dict[str, list[dict]] = defaultdict(list)
    for r in rows.get("resolution_events", []):
        resolutions_by_incident[r.get("incident_id")].append(r)

    evidence_by_id: dict[str, tuple[str | None, datetime | None, dict]] = {}
    for r in rows.get("telemetry_tr181", []):
        evidence_by_id[r["event_id"]] = (r.get("case_id"), _parse_ts(r.get("event_timestamp")), r)
    for r in rows.get("nxt_alarms", []):
        evidence_by_id[r["event_id"]] = (r.get("case_id"), _parse_ts(r.get("event_timestamp")), r)
    for r in rows.get("field_evidence", []):
        evidence_by_id[r["evidence_id"]] = (r.get("case_id"), _parse_ts(r.get("captured_at")), r)

    # 2. Canonical per-case graph: root incident, service, technology and delimiter are non-bypassable.
    checks += 1
    for case_id, manifest in manifests.items():
        sid = manifest.get("service_id")
        sub = master.get(sid)
        root_case_id = manifest.get("root_case_id")
        root_incident_id = manifest.get("root_incident_id")
        if sub is None:
            errors.append(f"scenario service missing from master for {case_id}")
            continue
        if manifest.get("technology") != sub.get("technology"):
            errors.append(f"scenario technology disagrees with subscriber for {case_id}")
        if manifest.get("delimiter_type") != sub.get("delimiter_type") or manifest.get("delimiter_id") != sub.get("delimiter_id"):
            errors.append(f"scenario delimiter disagrees with subscriber for {case_id}")
        root_manifest = manifests.get(root_case_id)
        if root_manifest is None:
            errors.append(f"missing root case for {case_id}")
        elif root_manifest.get("service_id") != sid:
            errors.append(f"root case service mismatch for {case_id}")
        incident = incidents_by_id.get(root_incident_id)
        if incident is None:
            errors.append(f"missing root incident for {case_id}")
        elif incident.get("case_id") != root_case_id or incident.get("service_id") != sid:
            errors.append(f"root incident graph mismatch for {case_id}")
        if manifest.get("repeat_sequence", 0) == 0 and (root_case_id != case_id or root_incident_id != f"INC-{case_id}"):
            errors.append(f"non-repeat case has non-self root for {case_id}")
        if manifest.get("repeat_sequence", 0) > 0 and case_id in incidents_by_root:
            errors.append(f"repeat attempt created a child incident for {case_id}")

    for name in ("telemetry_tr181", "nxt_alarms", "contacts", "work_orders", "field_evidence", "mrs", "validation_events", "resolution_events"):
        for row in rows.get(name, []):
            case_id = row.get("case_id")
            if case_id is None:
                continue
            manifest = manifests.get(case_id)
            if manifest is None:
                errors.append(f"orphan case in {name}")
                continue
            sid = row.get("service_id")
            if sid is not None and sid != manifest.get("service_id"):
                errors.append(f"cross-case service in {name}")
            incident_id = row.get("incident_id")
            if incident_id is not None and incident_id != manifest.get("root_incident_id"):
                errors.append(f"cross-case incident in {name}")
            delimiter_id = row.get("delimiter_id")
            if delimiter_id is not None and delimiter_id != manifest.get("delimiter_id"):
                errors.append(f"cross-case delimiter in {name}")

    for incident in rows.get("incidents", []):
        manifest = manifests.get(incident.get("case_id"))
        if manifest is None or manifest.get("root_case_id") != incident.get("case_id"):
            errors.append("incident is not anchored to a root case")
        elif incident.get("incident_id") != manifest.get("root_incident_id") or incident.get("service_id") != manifest.get("service_id"):
            errors.append("incident identity disagrees with root manifest")

    # 3. Scenario truth and technology constraints are complete.
    checks += 1
    for case_id, manifest in manifests.items():
        policy = SCENARIO_POLICIES.get(manifest.get("scenario"))
        det = deterministic.get(case_id)
        sub = master.get(manifest.get("service_id"))
        if policy is None:
            errors.append(f"unknown scenario policy for {case_id}")
            continue
        if sub is not None and sub.get("technology") not in policy["technologies"]:
            errors.append(f"scenario technology incompatible for {case_id}")
        if det is None:
            errors.append(f"missing deterministic decision for {case_id}")
            continue
        if det.get("recommended_domain") != policy["domain"] or det.get("recommended_domain") == "unknown":
            errors.append(f"deterministic domain mismatch for {case_id}")
        if det.get("best_action") != policy["best_action"]:
            errors.append(f"deterministic action mismatch for {case_id}")

    # 4. Deterministic and agent evidence must be non-empty, present and case-local.
    checks += 1
    for dataset in ("deterministic_decisions", "agent_decisions"):
        for decision in rows.get(dataset, []):
            case_id = decision.get("case_id")
            refs = decision.get("evidence_ids") or []
            if not refs:
                errors.append(f"{dataset} has empty evidence")
            for evidence_id in refs:
                evidence = evidence_by_id.get(evidence_id)
                if evidence is None:
                    errors.append(f"{dataset} cites missing evidence")
                elif evidence[0] != case_id:
                    errors.append(f"{dataset} cites cross-case evidence")

    # 5. Recompute reconciliation/policy from source facts; never trust stored human-gate flags.
    checks += 1
    rec_fields = (
        "independent_model",
        "domain_agreement",
        "action_agreement",
        "evidence_valid",
        "human_review_required",
        "reason",
    )
    expected_rec: dict[str, dict] = {}
    for case_id, manifest in manifests.items():
        det = deterministic.get(case_id)
        agent_row = agents.get(case_id)
        stored = reconciliations.get(case_id)
        action = actions.get(case_id)
        if det is None or agent_row is None or stored is None:
            errors.append(f"missing decision/reconciliation record for {case_id}")
            continue
        try:
            agent = AgentDecision.model_validate({k: v for k, v in agent_row.items() if k != "case_id"})
        except ValidationError:
            errors.append(f"invalid agent decision schema for {case_id}")
            continue
        valid_evidence = {eid for eid, item in evidence_by_id.items() if item[0] == case_id}
        recomputed = reconcile_with_operating_controls(
            det,
            agent,
            valid_evidence,
            repeat=bool(manifest.get("repeat_sequence", 0)),
        ).model_dump()
        expected_rec[case_id] = recomputed
        for field in rec_fields:
            if stored.get(field) != recomputed.get(field):
                errors.append(f"stored reconciliation violates recomputed policy for {case_id}")
                break
        if action is None or action.get("action") != det.get("best_action"):
            errors.append(f"action disagrees with deterministic policy for {case_id}")

    # 6. Work assignment is gated by diagnosis, skill, parts/CPE and access readiness.
    checks += 1
    for wo in rows.get("work_orders", []):
        diagnosis = _parse_ts(wo.get("diagnosis_completed_at"))
        readiness = _parse_ts(wo.get("readiness_checked_at"))
        assigned = _parse_ts(wo.get("assigned_at"))
        dispatch = _parse_ts(wo.get("dispatched_at"))
        arrive = _parse_ts(wo.get("arrived_at"))
        complete = _parse_ts(wo.get("completed_at"))
        if not all((diagnosis, readiness, assigned, dispatch, arrive, complete)) or not (diagnosis <= readiness <= assigned <= dispatch <= arrive <= complete):
            errors.append("invalid work-order readiness/lifecycle ordering")
        if wo.get("readiness_passed") is not True or wo.get("skill_confirmed") is not True or wo.get("parts_confirmed") is not True or wo.get("access_confirmed") is not True:
            errors.append("work order assigned without complete readiness gate")
        if not wo.get("required_skill") or wo.get("required_skill") != wo.get("technician_skill"):
            errors.append("work order skill mismatch")
        if wo.get("parts_required") and wo.get("parts_confirmed") is not True:
            errors.append("work order parts not confirmed")
        if wo.get("work_order_type") == "CPE_SWAP" and wo.get("cpe_available") is not True:
            errors.append("CPE swap assigned without replacement CPE")
        manifest = manifests.get(wo.get("case_id"), {})
        if manifest.get("repeat_sequence", 0) > 0:
            if wo.get("supervisor_escalation_confirmed") is not True or not wo.get("supervisor_actor"):
                errors.append("repeat work dispatched without supervisor escalation")

    for evidence in rows.get("field_evidence", []):
        wo = work_by_id.get(evidence.get("work_order_id"))
        if wo is None or wo.get("case_id") != evidence.get("case_id"):
            errors.append("field evidence missing case-local work order")
            continue
        captured = _parse_ts(evidence.get("captured_at"))
        arrive = _parse_ts(wo.get("arrived_at"))
        complete = _parse_ts(wo.get("completed_at"))
        if not captured or not arrive or not complete or not (arrive <= captured <= complete):
            errors.append("field evidence outside work interval")

    # 7. CPE replacement requires a separately documented failed diagnostic before swap starts.
    checks += 1
    evidence_rows = {r["evidence_id"]: r for r in rows.get("field_evidence", [])}
    for wo in rows.get("work_orders", []):
        if wo.get("work_order_type") != "CPE_SWAP":
            continue
        start = _parse_ts(wo.get("replacement_started_at"))
        refs = wo.get("precondition_evidence_refs") or []
        if not start or not refs:
            errors.append("CPE swap lacks pre-replacement diagnostic gate")
            continue
        valid_failed_diag = False
        for ref in refs:
            ev = evidence_rows.get(ref)
            captured = _parse_ts(ev.get("captured_at")) if ev else None
            if (
                ev
                and ev.get("case_id") == wo.get("case_id")
                and ev.get("work_order_id") == wo.get("work_order_id")
                and ev.get("measurement") == "cpe_diagnostic_failed"
                and ev.get("diagnostic_result") == "FAIL"
                and ev.get("documented_reason")
                and captured
                and captured < start
            ):
                valid_failed_diag = True
        if not valid_failed_diag:
            errors.append("CPE replacement started without documented failed diagnostic")

    # 8. MR evidence, delimiter and lifecycle must be fully ordered.
    checks += 1
    for mr in rows.get("mrs", []):
        created = _parse_ts(mr.get("created_at"))
        accepted = _parse_ts(mr.get("accepted_at"))
        completed = _parse_ts(mr.get("completed_at"))
        wo = work_by_id.get(mr.get("work_order_id"))
        dispatch = _parse_ts(wo.get("dispatched_at")) if wo else None
        work_complete = _parse_ts(wo.get("completed_at")) if wo else None
        if not all((created, accepted, completed, dispatch, work_complete)) or not (created <= accepted <= dispatch <= work_complete <= completed):
            errors.append("invalid MR/work lifecycle ordering")
        initial_refs = mr.get("evidence_refs") or []
        completion_refs = mr.get("completion_evidence_refs") or []
        if not initial_refs or not completion_refs:
            errors.append("MR lacks required initial/completion evidence")
        for evidence_id in initial_refs:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None or evidence[0] != mr.get("case_id"):
                errors.append("invalid MR initial evidence")
            elif created is None or evidence[1] is None or evidence[1] > created:
                errors.append("MR created before cited evidence exists")
        for evidence_id in completion_refs:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None or evidence[0] != mr.get("case_id"):
                errors.append("invalid MR completion evidence")
            elif completed is None or evidence[1] is None or evidence[1] > completed:
                errors.append("MR completed before completion evidence exists")

    # 9. Validation requires objective evidence, PASS/stability and a complete closure checklist.
    checks += 1
    for val in rows.get("validation_events", []):
        val_time = _parse_ts(val.get("event_timestamp"))
        refs = val.get("evidence_refs") or []
        if not refs:
            errors.append("validation has no objective evidence")
        healthy_telemetry = False
        for evidence_id in refs:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                errors.append("validation cites missing evidence")
                continue
            if evidence[0] != val.get("case_id"):
                errors.append("validation cites cross-case evidence")
            if val_time is None or evidence[1] is None or evidence[1] > val_time:
                errors.append("validation precedes cited evidence")
            row = evidence[2]
            if row.get("event_id", "").startswith("TEL-") and row.get("health") == "HEALTHY":
                healthy_telemetry = True
        if not healthy_telemetry:
            errors.append("validation lacks healthy post-fix telemetry")
        if val.get("service_test") != "PASS" or val.get("stable") is not True:
            errors.append("validation is not PASS/stable")
        checklist = val.get("closure_checklist") or {}
        if set(checklist) != set(CLOSURE_CHECKS) or any(checklist.get(k) is not True for k in CLOSURE_CHECKS):
            errors.append("closure checklist incomplete")
        checklist_time = _parse_ts(val.get("checklist_completed_at"))
        if val_time is None or checklist_time is None or checklist_time > val_time:
            errors.append("closure checklist not completed before validation")
        for wo in work_by_case.get(val.get("case_id"), []):
            complete = _parse_ts(wo.get("completed_at"))
            if val_time is None or complete is None or complete > val_time:
                errors.append("validation precedes work completion")

    # 10. Resolution is case-local, evidence-backed and matches scenario truth.
    checks += 1
    for res in rows.get("resolution_events", []):
        val = validations.get(res.get("validation_ref"))
        if val is None or val.get("case_id") != res.get("case_id") or val.get("incident_id") != res.get("incident_id"):
            errors.append("resolution missing case-local validation")
            continue
        resolved_at = _parse_ts(res.get("resolved_at"))
        validated_at = _parse_ts(val.get("event_timestamp"))
        if resolved_at is None or validated_at is None or resolved_at < validated_at:
            errors.append("resolution precedes validation")
        manifest = manifests.get(res.get("case_id"))
        if manifest and res.get("fault_domain") != SCENARIO_POLICIES[manifest["scenario"]]["domain"]:
            errors.append("resolution fault domain contradicts scenario truth")

    # 11. Root incident final state must agree with the latest attempt on that root.
    checks += 1
    attempts_by_root: dict[str, list[dict]] = defaultdict(list)
    for manifest in manifests.values():
        attempts_by_root[manifest.get("root_case_id")].append(manifest)
    for root_case_id, incident in incidents_by_root.items():
        opened = _parse_ts(incident.get("opened_at"))
        resolved = _parse_ts(incident.get("resolved_at"))
        closed = _parse_ts(incident.get("closed_at"))
        attempts = sorted(attempts_by_root.get(root_case_id, []), key=lambda x: _parse_ts(x.get("event_timestamp")) or datetime.min.replace(tzinfo=UTC))
        if not attempts:
            errors.append("root incident has no attempts")
            continue
        latest = attempts[-1]
        latest_case = latest["case_id"]
        latest_action = actions.get(latest_case, {})
        latest_det = deterministic.get(latest_case, {})
        latest_restored = latest_case in resolutions_by_case
        if incident.get("status") == "CLOSED":
            if not opened or not resolved or not closed or not (opened <= resolved <= closed):
                errors.append("invalid closed root-incident lifecycle")
            if not latest_restored:
                errors.append("root incident closed without latest-attempt resolution")
            else:
                res_time = _parse_ts(resolutions_by_case[latest_case].get("resolved_at"))
                if res_time is None or closed < res_time:
                    errors.append("root incident closes before latest resolution")
        elif incident.get("status") == "OPEN":
            if resolved is not None or closed is not None:
                errors.append("open root incident contains resolved/closed timestamp")
            if latest_action.get("status") == "SIMULATED_EXECUTED" and latest_det.get("best_action") != "collect_evidence" and latest_restored:
                errors.append("restored latest attempt left root incident open")
        else:
            errors.append("unknown root incident status")
        repeats = [a for a in attempts if a.get("repeat_sequence", 0) > 0]
        if int(incident.get("repeat_count", 0)) != len(repeats):
            errors.append("root incident repeat count mismatch")

    # 12. Human/action state must satisfy recomputed policy; blocked cases cannot create downstream work.
    checks += 1
    for case_id in manifests:
        human = humans.get(case_id)
        action = actions.get(case_id)
        rec = expected_rec.get(case_id)
        if human is None or action is None or rec is None:
            errors.append(f"missing control-plane record for {case_id}")
            continue
        if action.get("production_write") is not False:
            errors.append("production write enabled in action event")
        status = action.get("status")
        if status == "BLOCKED_PENDING_HUMAN":
            if human.get("status") != "PENDING" or human.get("required") is not True or rec.get("human_review_required") is not True:
                errors.append("blocked action lacks required pending human decision")
            if work_by_case.get(case_id) or mr_by_case.get(case_id) or case_id in validations_by_case or case_id in resolutions_by_case:
                errors.append("downstream records exist while action remains pending")
        elif status == "SIMULATED_EXECUTED":
            action_time = _parse_ts(action.get("event_timestamp"))
            if rec.get("human_review_required"):
                if human.get("status") != "APPROVED" or human.get("response") != "approve" or human.get("required") is not True:
                    errors.append("human-gated action executed without approval")
                decided = _parse_ts(human.get("decided_at"))
                if not decided or not action_time or decided > action_time:
                    errors.append("action executed before human approval")
            elif human.get("status") != "NOT_REQUIRED" or human.get("required") is not False:
                errors.append("policy-auto action has inconsistent human status")
        elif status == "BLOCKED_NEEDS_EVIDENCE":
            if human.get("status") != "EVIDENCE_REQUESTED" or human.get("response") != "request_evidence":
                errors.append("evidence-request block has inconsistent human record")
            if work_by_case.get(case_id) or mr_by_case.get(case_id) or case_id in validations_by_case or case_id in resolutions_by_case:
                errors.append("downstream records exist after evidence request")
        elif status == "BLOCKED_ESCALATED":
            if human.get("status") not in {"ESCALATED", "REJECTED"} or human.get("response") not in {"escalate", "reject"}:
                errors.append("escalated/rejected block has inconsistent human record")
            if work_by_case.get(case_id) or mr_by_case.get(case_id) or case_id in validations_by_case or case_id in resolutions_by_case:
                errors.append("downstream records exist after escalation/rejection")
        else:
            errors.append("unknown action status")

    # 13. Selected action controls which downstream branch is allowed.
    checks += 1
    for case_id, det in deterministic.items():
        action_row = actions.get(case_id)
        if not action_row or action_row.get("status") != "SIMULATED_EXECUTED":
            continue
        work = work_by_case.get(case_id, [])
        mrs = mr_by_case.get(case_id, [])
        selected = det.get("best_action")
        if selected in {"remote_repair", "collect_evidence"} and (work or mrs):
            errors.append("remote/read-only branch incorrectly created truck work")
        if selected in {"dispatch_clean", "cpe_swap"} and (len(work) != 1 or mrs):
            errors.append("field branch missing or duplicated Clean Boots work")
        if selected in {"create_mr", "plant_repair"} and (len(work) != 1 or len(mrs) != 1):
            errors.append("plant branch missing MR or plant work")
        action_time = _parse_ts(action_row.get("event_timestamp"))
        for wo in work:
            dispatch = _parse_ts(wo.get("dispatched_at"))
            if action_time is None or dispatch is None or dispatch < action_time:
                errors.append("work dispatched before authorized action")
        for mr in mrs:
            created = _parse_ts(mr.get("created_at"))
            if action_time is None or created is None or created < action_time:
                errors.append("MR created before authorized action")

    # 14. Restoring actions require validation/resolution; evidence-only actions remain open at attempt level.
    checks += 1
    for case_id, det in deterministic.items():
        action_row = actions.get(case_id)
        if not action_row or action_row.get("status") != "SIMULATED_EXECUTED":
            continue
        selected = det.get("best_action")
        if selected == "collect_evidence":
            if case_id in resolutions_by_case or case_id in validations_by_case:
                errors.append("collect-evidence action incorrectly claims restoration")
        elif case_id not in resolutions_by_case or case_id not in validations_by_case:
            errors.append("executed restoring action lacks verified closure")

    # 15. Repeat attempts remain on one root incident, stay inside the repeat window and require supervisor escalation.
    checks += 1
    for manifest in manifests.values():
        seq = int(manifest.get("repeat_sequence", 0) or 0)
        parent_id = manifest.get("repeat_of_case_id")
        if seq <= 0:
            if parent_id is not None or manifest.get("supervisor_escalation_required") is True:
                errors.append("non-repeat case has repeat metadata")
            continue
        parent = manifests.get(parent_id)
        root = manifests.get(manifest.get("root_case_id"))
        human = humans.get(manifest.get("case_id"), {})
        if parent is None or root is None:
            errors.append("repeat attempt references missing parent/root")
            continue
        if parent.get("root_case_id") != manifest.get("root_case_id") or parent.get("service_id") != manifest.get("service_id"):
            errors.append("repeat attempt changes root/service identity")
        parent_time = _parse_ts(parent.get("event_timestamp"))
        repeat_time = _parse_ts(manifest.get("event_timestamp"))
        if parent_time is None or repeat_time is None or not (parent_time < repeat_time <= parent_time + REPEAT_WINDOW):
            errors.append("repeat attempt outside 30-day window")
        if manifest.get("root_incident_id") != root.get("root_incident_id"):
            errors.append("repeat attempt changes root incident")
        if manifest.get("supervisor_escalation_required") is not True:
            errors.append("repeat attempt missing supervisor escalation policy")
        if human.get("required") is not True or human.get("supervisor_escalation") is not True or "supervisor" not in str(human.get("actor", "")):
            errors.append("repeat attempt lacks supervisor/senior approval")

    # 16. Dataset-level closure/production safety: no production effects, and every closed root has objective validation.
    checks += 1
    if any(a.get("production_write") is not False for a in rows.get("action_events", [])):
        errors.append("production-write safety contract violated")
    for incident in rows.get("incidents", []):
        if incident.get("status") == "CLOSED":
            linked = resolutions_by_incident.get(incident.get("incident_id"), [])
            if not linked:
                errors.append("closed root incident lacks resolution history")

    # 17. Predictive pulls and tickets must be service/device correlated and evidence-backed.
    checks += 1
    pulls = rows.get("predictive_modem_pulls", [])
    pulls_by_device = {r.get("device_id"): r for r in pulls}
    predictive_by_id = {r.get("ticket_id"): r for r in rows.get("predictive_tickets", [])}
    for pull in pulls:
        sub = master.get(pull.get("service_id"))
        if sub is None or sub.get("device_id") != pull.get("device_id"):
            errors.append("predictive pull is not correlated to subscriber master")
        if not pull.get("kpis") or int(pull.get("trend_window_days", 0)) < 7:
            errors.append("predictive pull lacks trend evidence")
    for ticket in predictive_by_id.values():
        pull = pulls_by_device.get(ticket.get("device_id"))
        if pull is None or pull.get("service_id") != ticket.get("service_id"):
            errors.append("predictive ticket lacks matching modem pull")
            continue
        findings = ticket.get("findings") or []
        if not findings:
            errors.append("predictive ticket lacks findings")
        if ticket.get("ticket_class") == "proactive" and not any(f.get("breached_now") is True for f in findings):
            errors.append("proactive ticket has no breached KPI")
        if ticket.get("ticket_class") == "forecast":
            if any(f.get("breached_now") is True for f in findings):
                errors.append("forecast ticket contains current breach")
            if not any(f.get("days_to_breach") is not None for f in findings):
                errors.append("forecast ticket lacks days-to-breach evidence")
        elif ticket.get("ticket_class") != "proactive":
            errors.append("unknown predictive ticket class")

    # 18. Care tickets must attach to the canonical root incident and never duplicate it.
    checks += 1
    contacts_by_id = {r.get("contact_id"): r for r in rows.get("contacts", [])}
    care_by_id = {r.get("care_ticket_id"): r for r in rows.get("care_tickets", [])}
    for care in care_by_id.values():
        contact = contacts_by_id.get(care.get("contact_id"))
        manifest = manifests.get(care.get("case_id"))
        incident = incidents_by_id.get(care.get("incident_id"))
        if contact is None or manifest is None or incident is None:
            errors.append("care ticket has orphan contact/case/incident")
            continue
        if care.get("incident_id") != manifest.get("root_incident_id") or care.get("service_id") != manifest.get("service_id"):
            errors.append("care ticket is not attached to canonical root incident")
        if care.get("duplicate_incident_suppressed") is not True or care.get("production_write") is not False:
            errors.append("care ticket duplicate/production-write safety contract violated")
        expected_status = "CLOSED" if incident.get("status") == "CLOSED" else "OPEN"
        if care.get("status") != expected_status:
            errors.append("care ticket status disagrees with root incident")

    # 19. Predictive-to-care correlation must be causal and service-local.
    checks += 1
    for care in care_by_id.values():
        predictive_id = care.get("predictive_ticket_id")
        if care.get("predictive_match") is True:
            predictive_ticket = predictive_by_id.get(predictive_id)
            if predictive_ticket is None:
                errors.append("care predictive match references missing ticket")
                continue
            if predictive_ticket.get("service_id") != care.get("service_id"):
                errors.append("care predictive match crosses service identity")
            pred_time = _parse_ts(predictive_ticket.get("opened_at"))
            care_time = _parse_ts(care.get("opened_at"))
            if pred_time is None or care_time is None or pred_time > care_time:
                errors.append("care predictive match is not predictive-before-contact")
            if care.get("correlation_disposition") != "ATTACH_TO_PREDICTIVE_ROOT_INCIDENT":
                errors.append("predictive care match has wrong correlation disposition")
        elif predictive_id is not None:
            errors.append("care ticket carries predictive id without predictive match")

    # 20. Care reviews must reconcile deterministic, agent and predictive context.
    checks += 1
    reviews = {r.get("care_ticket_id"): r for r in rows.get("care_ticket_reviews", [])}
    if set(reviews) != set(care_by_id):
        errors.append("care review coverage does not match care ticket queue")
    for care_id, review in reviews.items():
        care = care_by_id.get(care_id)
        if care is None:
            continue
        case_id = care.get("case_id")
        det = deterministic.get(case_id, {})
        agent_row = agents.get(case_id, {})
        rec = reconciliations.get(case_id, {})
        if review.get("deterministic_domain") != det.get("recommended_domain") or review.get("deterministic_action") != det.get("best_action"):
            errors.append("care review disagrees with deterministic branch")
        if review.get("agent_source") != agent_row.get("source") or review.get("agent_action") != agent_row.get("best_action"):
            errors.append("care review disagrees with agent decision")
        if review.get("reconciled_human_review_required") != rec.get("human_review_required"):
            errors.append("care review disagrees with reconciliation")
        if review.get("predictive_match") != care.get("predictive_match") or review.get("predictive_ticket_id") != care.get("predictive_ticket_id"):
            errors.append("care review disagrees with predictive correlation")

    return {"passed": not errors, "errors": errors, "checks": checks}


def _load_run_rows(run_path: Path) -> dict[str, list[dict]]:
    rows: dict[str, list[dict]] = {}
    for name in DATASETS:
        if name == "subscriber_master":
            continue
        rows[name] = load_jsonl_gz(run_path / f"{name}.jsonl.gz")
    return rows


def _case_master_projection(
    run_path: Path,
    manifests: list[dict],
    extra_service_ids: set[str] | None = None,
) -> list[dict]:
    wanted = {m["service_id"] for m in manifests}
    wanted.update(extra_service_ids or set())
    found: dict[str, dict] = {}
    for row in iter_jsonl_gz(run_path / "subscriber_master.jsonl.gz"):
        sid = row.get("service_id")
        if sid in wanted:
            found[sid] = row
            if len(found) == len(wanted):
                break
    return list(found.values())


def _quality_projection(run_path: Path, rows: dict[str, list[dict]]) -> dict[str, list[dict]]:
    result = dict(rows)
    predictive_services = {
        str(row["service_id"])
        for row in rows.get("predictive_modem_pulls", [])
        if row.get("service_id")
    }
    result["subscriber_master"] = _case_master_projection(
        run_path,
        rows["scenario_manifests"],
        predictive_services,
    )
    result["telemetry_tr181"] = [r for r in rows["telemetry_tr181"] if r.get("case_id") is not None]
    return result


def _write_changed_datasets(run_path: Path, rows: dict[str, list[dict]], catalog: dict, changed: set[str]) -> None:
    by_name = {d["dataset"]: d for d in catalog["datasets"]}
    for name in sorted(changed):
        path = run_path / f"{name}.jsonl.gz"
        count = atomic_write_jsonl_gz(path, rows[name])
        entry = by_name[name]
        entry["row_count"] = count
        entry["sha256"] = sha256_file(path)
    catalog["datasets"] = [by_name[name] for name in DATASETS]


def materialize_live_decision(
    run_path: Path,
    decision: HumanDecision,
    store: CaseStore,
    store_result: dict,
) -> dict:
    """Mirror a durable live decision into exported datasets and complete simulated restoration when approved."""
    catalog_path = run_path / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    rows = _load_run_rows(run_path)
    manifests = {r["case_id"]: r for r in rows["scenario_manifests"]}
    manifest = manifests.get(decision.case_id)
    if manifest is None:
        raise KeyError(decision.case_id)
    human = next(r for r in rows["human_decisions"] if r["case_id"] == decision.case_id)
    action = next(r for r in rows["action_events"] if r["case_id"] == decision.case_id)
    det = next(r for r in rows["deterministic_decisions"] if r["case_id"] == decision.case_id)
    decided_at = _parse_ts(store_result.get("updated_at")) or datetime.now(UTC)
    changed = {"human_decisions", "action_events"}

    human.update({
        "revision": decision.revision,
        "required": True,
        "response": decision.response,
        "actor": decision.actor,
        "decided_at": _iso(decided_at),
        "rationale": decision.rationale,
        "source": "live_control",
        "supervisor_escalation": bool(manifest.get("repeat_sequence", 0)),
    })

    if decision.response == "approve":
        human["status"] = "APPROVED"
        action_time = decided_at + timedelta(minutes=1)
        action.update({"status": "SIMULATED_EXECUTED", "event_timestamp": _iso(action_time), "production_write": False})
        sub = _case_master_projection(run_path, [manifest])
        if not sub:
            raise ValueError("case subscriber not found")
        incident = next((r for r in rows["incidents"] if r["incident_id"] == manifest["root_incident_id"]), None)
        tele_pre = next((r for r in rows["telemetry_tr181"] if r.get("case_id") == decision.case_id and r.get("health") == "DEGRADED"), None)
        alarm = next((r for r in rows["nxt_alarms"] if r.get("case_id") == decision.case_id), None)
        if incident is None or tele_pre is None or alarm is None:
            raise ValueError("live case graph is incomplete")
        if incident.get("status") == "CLOSED":
            incident["prior_closed_at"] = incident["closed_at"]
            incident["resolved_at"] = None
            incident["closed_at"] = None
            incident["status"] = "OPEN"
            incident["reopen_count"] = int(incident.get("reopen_count", 0)) + 1
            incident["last_reopened_at"] = manifest["event_timestamp"]
        case = {
            "scenario": manifest,
            "sub": sub[0],
            "incident": incident,
            "tele_pre": tele_pre,
            "alarm": alarm,
            "t_ticket": _parse_ts(incident.get("opened_at")),
            "diagnosis_completed_at": action_time - timedelta(minutes=2),
        }
        _materialize_effect(rows, case, det["best_action"], action_time)
        changed.update({"telemetry_tr181", "incidents", "work_orders", "field_evidence", "mrs", "validation_events", "resolution_events"})
    elif decision.response == "request_evidence":
        human["status"] = "EVIDENCE_REQUESTED"
        action["status"] = "BLOCKED_NEEDS_EVIDENCE"
    elif decision.response == "reject":
        human["status"] = "REJECTED"
        action["status"] = "BLOCKED_ESCALATED"
    else:
        human["status"] = "ESCALATED"
        action["status"] = "BLOCKED_ESCALATED"

    care_changed, review_changed = refresh_care_status(
        rows.get("care_tickets", []),
        rows.get("care_ticket_reviews", []),
        rows["incidents"],
    )
    if care_changed:
        changed.add("care_tickets")
    if review_changed:
        changed.add("care_ticket_reviews")

    projected = _quality_projection(run_path, rows)
    quality = quality_check(projected)
    if not quality["passed"]:
        raise ValueError("live decision would violate quality gate: " + "; ".join(quality["errors"][:10]))
    _write_changed_datasets(run_path, rows, catalog, changed)
    catalog["quality"] = quality | {"scope": "post-live-decision canonical graph and operating controls"}
    catalog["last_live_update"] = _iso(decided_at)
    catalog_path.write_text(json.dumps(catalog, indent=2, sort_keys=True), encoding="utf-8")

    if decision.response == "approve" and decision.case_id in {r["case_id"] for r in rows["resolution_events"]}:
        store.mark_verified(decision.case_id, at=_iso(decided_at + timedelta(minutes=2)))
    return store.get(decision.case_id)
