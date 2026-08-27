"""Synthetic 24-Hour Install Assurance Watch child artifacts.

An install watch is an assurance episode, not a fault incident.  Healthy
installations complete the observation window without creating incidents.
Persistent or severe defects are promoted idempotently to a durable root
incident inside the install-assurance artifact.  The parent Digital Twin run and
its canonical break/fix datasets remain immutable.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from lpr_cpe_demo.dalli import project_install_assurance_context

from .storage import (
    iter_jsonl_gz,
    load_jsonl_gz,
    replace_with_retry,
    write_jsonl_gz,
)

INSTALL_ASSURANCE_VERSION = "1.0"
MAX_INSTALL_POPULATION = 5_000
WATCH_PREFIX = "IAW-"
COHORT_PREFIX = "IAC-"
EPISODE_PREFIX = "IAE-"

LIFECYCLE_STATES = (
    "PENDING_BASELINE",
    "ACTIVE",
    "RECOVERING",
    "PASSED_24H",
    "PROMOTED_TO_INCIDENT",
    "INVALIDATED",
)
HEALTH_STATES = ("GREEN", "AMBER", "RED")


@dataclass(frozen=True, slots=True)
class InstallWatchRequest:
    population: int = 12
    as_of_hours: float = 24.0
    stability_tail_hours: float = 4.0
    seed: int = 0


@dataclass(frozen=True, slots=True)
class InstallWatchArtifact:
    summary: dict[str, Any]
    episodes: list[dict[str, Any]]
    observations: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    contacts: list[dict[str, Any]]
    incidents: list[dict[str, Any]]
    dalli_contexts: list[dict[str, Any]]

    @property
    def caddi_contexts(self) -> list[dict[str, Any]]:
        """Compatibility alias for artifacts created before the DALLI label fix."""

        return self.dalli_contexts


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _digest(*parts: object, length: int = 16) -> str:
    material = "|".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(material).hexdigest().upper()[:length]


def _validate_watch_id(watch_id: str) -> str:
    if not watch_id.startswith(WATCH_PREFIX) or len(watch_id) != len(WATCH_PREFIX) + 16:
        raise ValueError("invalid install assurance watch_id")
    if any(char not in "0123456789ABCDEF" for char in watch_id[len(WATCH_PREFIX) :]):
        raise ValueError("invalid install assurance watch_id")
    return watch_id


def _read_catalog(run_path: Path) -> dict[str, Any]:
    path = run_path / "catalog.json"
    if not path.is_file():
        raise FileNotFoundError("run catalog not found")
    return json.loads(path.read_text(encoding="utf-8"))


def _eligible_subscribers(run_path: Path) -> list[dict[str, Any]]:
    path = run_path / "subscriber_master.jsonl.gz"
    if not path.is_file():
        raise FileNotFoundError("subscriber master not found")
    return list(iter_jsonl_gz(path))


def _same_delimiter_pair(rows: Iterable[dict[str, Any]], technology: str) -> list[dict[str, Any]]:
    by_delimiter: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        row_technology = str(row.get("technology", ""))
        matches = row_technology == "HFC" if technology == "HFC" else row_technology != "HFC"
        if not matches:
            continue
        by_delimiter[str(row.get("delimiter_id", ""))].append(row)
    for candidates in by_delimiter.values():
        if len(candidates) >= 2:
            return candidates[:2]
    return []


def _pick_subscribers(
    rows: list[dict[str, Any]],
    population: int,
    seed: int,
) -> list[dict[str, Any]]:
    if population < 1:
        raise ValueError("population must be at least 1")
    if population > len(rows):
        raise ValueError(f"population must be between 1 and {len(rows)}")

    hfc = [row for row in rows if row.get("technology") == "HFC"]
    pon = [row for row in rows if row.get("technology") != "HFC"]
    if not hfc or not pon:
        raise ValueError("install assurance requires both HFC and PON subscribers")

    selected: list[dict[str, Any]] = []
    used: set[str] = set()
    common_pair = _same_delimiter_pair(rows, "HFC")
    common_ids = {str(row.get("service_id", "")) for row in common_pair}
    hfc_general = [
        row for row in hfc if str(row.get("service_id", "")) not in common_ids
    ] or hfc

    def add_from(pool: list[dict[str, Any]], token: int) -> None:
        if not pool:
            return
        start = abs(token) % len(pool)
        for offset in range(len(pool)):
            row = pool[(start + offset) % len(pool)]
            service_id = str(row.get("service_id", ""))
            if service_id and service_id not in used:
                selected.append(row)
                used.add(service_id)
                return

    slot_technologies = (
        "HFC",
        "PON",
        "HFC",
        "HFC",
        "PON",
        "PON",
        "COMMON_A",
        "COMMON_B",
        "HFC",
        "PON",
        "HFC",
        "PON",
    )
    for index, slot in enumerate(slot_technologies[:population]):
        if slot == "COMMON_A" and len(common_pair) >= 2:
            add_from([common_pair[0]], seed + index)
        elif slot == "COMMON_B" and len(common_pair) >= 2:
            add_from([common_pair[1]], seed + index)
        elif slot == "HFC":
            add_from(hfc_general, seed + index * 17)
        else:
            add_from(pon, seed + index * 17)

    for index, row in enumerate(rows):
        if len(selected) >= population:
            break
        add_from([row], seed + index)
    if len(selected) != population:
        raise ValueError("could not select a unique install assurance population")
    return selected


def _scenario_for(index: int, technology: str) -> str:
    scenarios = (
        "healthy_hfc",
        "healthy_pon",
        "remote_stabilized",
        "persistent_hfc_impairment",
        "persistent_pon_impairment",
        "wifi_impairment",
        "common_cause_hfc",
        "common_cause_hfc",
        "late_action_extension",
        "active_green",
        "active_amber",
        "active_red",
    )
    if index < len(scenarios):
        scenario = scenarios[index]
        if scenario.endswith("_hfc") and technology != "HFC":
            return "healthy_pon"
        if scenario == "healthy_pon" and technology == "HFC":
            return "healthy_hfc"
        return scenario
    return "healthy_hfc" if technology == "HFC" else "healthy_pon"


def _start_offset_hours(scenario: str) -> float:
    return {
        "active_green": 12.0,
        "active_amber": 18.0,
        "active_red": 20.0,
    }.get(scenario, 0.0)


def _observation_offsets(age_hours: float) -> list[int]:
    limit = max(0, math.floor(age_hours * 60))
    offsets = {0}
    offsets.update(range(5, min(limit, 120) + 1, 5))
    if limit > 120:
        offsets.update(range(135, min(limit, 360) + 1, 15))
    if limit > 360:
        offsets.update(range(390, min(limit, 1440) + 1, 30))
    if limit > 1440:
        offsets.update(range(1500, limit + 1, 60))
    offsets.add(limit)
    return sorted(offsets)


def _event_plan(scenario: str) -> dict[str, float | None]:
    plans: dict[str, dict[str, float | None]] = {
        "remote_stabilized": {
            "finding": 2.0,
            "contact": 3.0,
            "remote_action": 4.0,
            "stable": 4.5,
        },
        "wifi_impairment": {
            "finding": 1.0,
            "contact": 1.5,
            "remote_action": 2.0,
            "stable": 2.5,
        },
        "persistent_hfc_impairment": {
            "finding": 1.0,
            "contact": 4.0,
            "remote_action": 2.5,
            "incident": 3.0,
            "dispatch": 5.0,
            "mr": 7.0,
            "repair": 12.0,
            "stable": 12.5,
        },
        "persistent_pon_impairment": {
            "finding": 1.0,
            "contact": 4.0,
            "remote_action": 2.5,
            "incident": 3.0,
            "dispatch": 5.0,
            "mr": 7.0,
            "repair": 12.0,
            "stable": 12.5,
        },
        "common_cause_hfc": {
            "finding": 0.75,
            "contact": 2.0,
            "incident": 1.5,
            "dispatch": 3.0,
            "mr": 4.0,
            "repair": 8.0,
            "stable": 8.5,
        },
        "late_action_extension": {
            "finding": 20.0,
            "contact": 21.0,
            "remote_action": 23.0,
            "stable": 23.5,
        },
        "active_amber": {"finding": 2.0, "contact": 3.0},
        "active_red": {"finding": 1.0, "contact": 2.0, "incident": 3.0},
    }
    return plans.get(scenario, {})


def _health_at(scenario: str, age: float) -> tuple[str, str]:
    plan = _event_plan(scenario)
    finding = plan.get("finding")
    stable = plan.get("stable")
    incident = plan.get("incident")
    if finding is None or age < float(finding):
        return "GREEN", "commissioning baseline stable"
    if stable is not None and age >= float(stable):
        return "GREEN", "post-action telemetry stable"
    if incident is not None and age >= float(incident):
        if "pon" in scenario:
            return "RED", "persistent optical instability"
        if "common_cause" in scenario:
            return "RED", "shared tap impairment across new installs"
        return "RED", "persistent HFC access impairment"
    if scenario == "active_red":
        return "RED", "repeated loss of service during installation watch"
    if scenario == "wifi_impairment":
        return "AMBER", "in-home Wi-Fi onboarding impairment"
    if scenario == "late_action_extension":
        return "AMBER", "late service instability requires extended observation"
    return "AMBER", "short-horizon stability threshold exceeded"


def _observation(
    *,
    episode_id: str,
    service: dict[str, Any],
    scenario: str,
    started_at: datetime,
    offset_minutes: int,
) -> dict[str, Any]:
    age = offset_minutes / 60
    health, finding = _health_at(scenario, age)
    technology = str(service["technology"])
    degraded = health != "GREEN"
    row: dict[str, Any] = {
        "observation_id": f"OBS-{episode_id}-{offset_minutes:04d}",
        "episode_id": episode_id,
        "service_id": service["service_id"],
        "device_id": service["device_id"],
        "technology": technology,
        "observed_at": _iso(started_at + timedelta(minutes=offset_minutes)),
        "age_hours": round(age, 3),
        "health_state": health,
        "online": not (health == "RED" and int(age * 2) % 3 == 0),
        "registration_stable": health == "GREEN",
        "packet_loss_pct": 0.05 if health == "GREEN" else 1.5 if health == "AMBER" else 8.0,
        "latency_ms": 18.0 if health == "GREEN" else 45.0 if health == "AMBER" else 120.0,
        "throughput_ratio": 0.93 if health == "GREEN" else 0.67 if health == "AMBER" else 0.22,
        "reboot_count_delta": 0 if health == "GREEN" else 1 if health == "AMBER" else 3,
        "wifi_health": "IMPAIRED" if scenario == "wifi_impairment" and degraded else "HEALTHY",
        "leading_finding": finding,
        "source_systems": ["NXT", "Provisioning systems", "Synthetic install watch"],
        "production_write": False,
    }
    if technology == "HFC":
        row.update(
            {
                "ds_rx_dbmv": -1.0 if health == "GREEN" else -11.0 if health == "AMBER" else -16.2,
                "us_tx_dbmv": 44.0 if health == "GREEN" else 52.5 if health == "AMBER" else 56.0,
                "ds_mer_db": 38.0 if health == "GREEN" else 32.0 if health == "AMBER" else 28.5,
                "uncorrectable_ratio": (
                    2e-8 if health == "GREEN" else 7e-5 if health == "AMBER" else 2e-3
                ),
                "t3_timeouts": 0 if health == "GREEN" else 8 if health == "AMBER" else 31,
            }
        )
    else:
        row.update(
            {
                "ont_rx_dbm": -19.5 if health == "GREEN" else -25.5 if health == "AMBER" else -28.0,
                "ber": 1e-11 if health == "GREEN" else 5e-7 if health == "AMBER" else 2e-5,
                "los_events": 0 if health == "GREEN" else 1 if health == "AMBER" else 5,
                "dying_gasp_events": 0 if health == "GREEN" else 1 if health == "AMBER" else 3,
            }
        )
    return row


def _action_rows(
    *,
    episode_id: str,
    scenario: str,
    started_at: datetime,
    service: dict[str, Any],
    incident_id: str | None,
) -> list[dict[str, Any]]:
    plan = _event_plan(scenario)
    definitions: tuple[tuple[str, str, str], ...] = (
        ("remote_action", "controlled_remote_reprovision", "remote_assurance"),
        ("dispatch", "clean_boots_diagnostic", "field_operations"),
        ("mr", "create_plant_maintenance_request", "plant_operations"),
        ("repair", "complete_access_repair", "plant_operations"),
        ("stable", "validate_post_action_stability", "install_assurance"),
    )
    rows: list[dict[str, Any]] = []
    for key, action_type, owner in definitions:
        offset = plan.get(key)
        if offset is None:
            continue
        work_order_id = None
        mr_id = None
        if key == "dispatch":
            work_order_id = f"WO-{episode_id}"
        if key == "mr":
            mr_id = f"MR-{episode_id}"
        rows.append(
            {
                "action_id": f"ACT-{episode_id}-{key.upper()}",
                "episode_id": episode_id,
                "incident_id": incident_id,
                "service_id": service["service_id"],
                "action_type": action_type,
                "owner": owner,
                "scheduled_at": _iso(started_at + timedelta(hours=float(offset))),
                "status": "SIMULATED_EXECUTED",
                "service_affecting": key in {"remote_action", "repair"},
                "work_order_id": work_order_id,
                "mr_id": mr_id,
                "production_write": False,
            }
        )
    return rows


def _incident_id(
    *,
    cohort_id: str,
    episode_id: str,
    scenario: str,
    delimiter_id: str,
) -> str | None:
    if scenario in {
        "persistent_hfc_impairment",
        "persistent_pon_impairment",
        "active_red",
    }:
        return f"INC-INSTALL-{_digest(cohort_id, episode_id, length=12)}"
    if scenario == "common_cause_hfc":
        return f"INC-INSTALL-COMMON-{_digest(cohort_id, delimiter_id, length=10)}"
    return None


def _lifecycle(
    *,
    scenario: str,
    age_hours: float,
    health: str,
    effective_maturity_hours: float,
    incident_id: str | None,
) -> str:
    if incident_id is not None and age_hours >= float(_event_plan(scenario).get("incident") or 0):
        return "PROMOTED_TO_INCIDENT"
    if age_hours >= effective_maturity_hours and health == "GREEN":
        return "PASSED_24H"
    if _event_plan(scenario).get("remote_action") is not None and health == "GREEN":
        return "RECOVERING" if age_hours < effective_maturity_hours else "PASSED_24H"
    return "ACTIVE"


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": round(numerator / denominator, 5) if denominator else None,
    }


def _build_artifact(
    run_path: Path,
    request: InstallWatchRequest,
) -> InstallWatchArtifact:
    catalog = _read_catalog(run_path)
    run_id = str(catalog["run_id"])
    subscribers = _eligible_subscribers(run_path)
    selected = _pick_subscribers(subscribers, request.population, request.seed)

    cohort_id = COHORT_PREFIX + _digest(run_id, request.population, request.seed)
    watch_id = WATCH_PREFIX + _digest(
        cohort_id,
        request.as_of_hours,
        request.stability_tail_hours,
    )
    run_date_text = str(catalog.get("config", {}).get("run_date", "2026-08-26"))
    run_date = datetime.fromisoformat(run_date_text).replace(tzinfo=UTC)
    base = run_date.replace(hour=8, minute=0, second=0, microsecond=0)
    snapshot_at = base + timedelta(hours=request.as_of_hours)

    episodes: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    contacts: list[dict[str, Any]] = []
    incidents_by_id: dict[str, dict[str, Any]] = {}
    dalli_contexts: list[dict[str, Any]] = []

    for index, service in enumerate(selected):
        episode_id = f"{EPISODE_PREFIX}{_digest(cohort_id, service['service_id'], length=12)}"
        technology = str(service["technology"])
        scenario = _scenario_for(index, technology)
        start_offset = min(_start_offset_hours(scenario), request.as_of_hours)
        started_at = base + timedelta(hours=start_offset)
        age_hours = max(0.0, (snapshot_at - started_at).total_seconds() / 3600)
        plan = _event_plan(scenario)
        observation_rows = [
            _observation(
                episode_id=episode_id,
                service=service,
                scenario=scenario,
                started_at=started_at,
                offset_minutes=offset,
            )
            for offset in _observation_offsets(age_hours)
        ]
        observations.extend(observation_rows)
        latest = observation_rows[-1]
        health = str(latest["health_state"])

        planned_incident_id = _incident_id(
            cohort_id=cohort_id,
            episode_id=episode_id,
            scenario=scenario,
            delimiter_id=str(service.get("delimiter_id", "")),
        )
        incident_threshold = plan.get("incident")
        incident_id = (
            planned_incident_id
            if incident_threshold is not None and age_hours >= float(incident_threshold)
            else None
        )
        action_rows = _action_rows(
            episode_id=episode_id,
            scenario=scenario,
            started_at=started_at,
            service=service,
            incident_id=incident_id,
        )
        executed_actions = [
            row
            for row in action_rows
            if (_parse(row["scheduled_at"]) or snapshot_at) <= snapshot_at
        ]
        actions.extend(executed_actions)
        last_service_action = max(
            (
                _parse(row["scheduled_at"])
                for row in executed_actions
                if row["service_affecting"]
            ),
            default=None,
        )
        nominal_maturity_at = started_at + timedelta(hours=24)
        effective_maturity_at = nominal_maturity_at
        if last_service_action is not None:
            effective_maturity_at = max(
                effective_maturity_at,
                last_service_action + timedelta(hours=request.stability_tail_hours),
            )
        effective_maturity_hours = (
            effective_maturity_at - started_at
        ).total_seconds() / 3600
        lifecycle = _lifecycle(
            scenario=scenario,
            age_hours=age_hours,
            health=health,
            effective_maturity_hours=effective_maturity_hours,
            incident_id=incident_id,
        )

        contact = None
        contact_offset = plan.get("contact")
        if contact_offset is not None and age_hours >= float(contact_offset):
            contact_time = started_at + timedelta(hours=float(contact_offset))
            contact = {
                "contact_id": f"CON-INSTALL-{episode_id}",
                "genesys_interaction_id": f"GEN-{_digest(episode_id, 'genesys', length=12)}",
                "episode_id": episode_id,
                "incident_id": incident_id,
                "service_id": service["service_id"],
                "device_id": service["device_id"],
                "opened_at": _iso(contact_time),
                "channel": "VOICE",
                "disposition": (
                    "ATTACH_TO_EXISTING_INSTALL_INCIDENT"
                    if incident_id
                    else "ATTACH_TO_INSTALL_ASSURANCE_EPISODE"
                ),
                "diagnostics_restarted": False,
                "duplicate_incident_created": False,
                "production_write": False,
            }
            contacts.append(contact)

        finding_offset = plan.get("finding")
        network_detected_at = (
            started_at + timedelta(hours=float(finding_offset))
            if finding_offset is not None and age_hours >= float(finding_offset)
            else None
        )
        contact_at = _parse(contact["opened_at"]) if contact else None
        network_before_call = bool(
            network_detected_at is not None
            and contact_at is not None
            and network_detected_at <= contact_at
        )
        work_order_ids = [
            str(row["work_order_id"])
            for row in executed_actions
            if row.get("work_order_id")
        ]
        mr_ids = [str(row["mr_id"]) for row in executed_actions if row.get("mr_id")]
        action_types = [str(row["action_type"]) for row in executed_actions]

        last_action_at = max(
            (_parse(row["scheduled_at"]) for row in executed_actions),
            default=None,
        )
        stable_offset = plan.get("stable")
        stable_since = (
            started_at + timedelta(hours=float(stable_offset))
            if stable_offset is not None and age_hours >= float(stable_offset)
            else started_at if health == "GREEN" else None
        )
        current_owner = (
            "plant_operations"
            if incident_id and health == "RED"
            else "install_assurance"
            if lifecycle in {"ACTIVE", "RECOVERING"}
            else "closed_loop_assurance"
        )
        next_action = (
            "continue_observation"
            if health == "GREEN" and lifecycle != "PASSED_24H"
            else "close_assurance_episode"
            if lifecycle == "PASSED_24H"
            else "continue_incident_repair_and_validation"
            if incident_id
            else "collect_expanded_diagnostics"
        )
        baseline_status = "ACCEPTED"
        validation_status = (
            "PASSED"
            if lifecycle == "PASSED_24H"
            else "INCIDENT_GOVERNED"
            if lifecycle == "PROMOTED_TO_INCIDENT"
            else "PENDING"
        )
        outcome = (
            "PASSED_WITHOUT_INTERVENTION"
            if lifecycle == "PASSED_24H" and not executed_actions
            else "PASSED_AFTER_REMOTE_STABILIZATION"
            if lifecycle == "PASSED_24H"
            else "PROMOTED_TO_ROOT_INCIDENT"
            if lifecycle == "PROMOTED_TO_INCIDENT"
            else "WATCH_IN_PROGRESS"
        )
        episode = {
            "episode_id": episode_id,
            "cohort_id": cohort_id,
            "watch_id": watch_id,
            "install_work_order_id": f"INSTALL-WO-{episode_id}",
            "customer_id": service.get("customer_id"),
            "service_id": service["service_id"],
            "device_id": service["device_id"],
            "technology": technology,
            "delimiter_type": service.get("delimiter_type"),
            "delimiter_id": service.get("delimiter_id"),
            "install_type": "NEW_SERVICE_INSTALL",
            "scenario": scenario,
            "started_at": _iso(started_at),
            "nominal_maturity_at": _iso(nominal_maturity_at),
            "effective_maturity_at": _iso(effective_maturity_at),
            "as_of_at": _iso(snapshot_at),
            "age_hours": round(age_hours, 3),
            "lifecycle_state": lifecycle,
            "health_state": health,
            "baseline_status": baseline_status,
            "last_observation_at": latest["observed_at"],
            "last_action_at": _iso(last_action_at) if last_action_at else None,
            "stable_since": _iso(stable_since) if stable_since else None,
            "incident_id": incident_id,
            "care_contact_ids": [contact["contact_id"]] if contact else [],
            "work_order_ids": work_order_ids,
            "mr_ids": mr_ids,
            "action_types": action_types,
            "validation_status": validation_status,
            "outcome": outcome,
            "network_detected_at": _iso(network_detected_at) if network_detected_at else None,
            "customer_contact_at": _iso(contact_at) if contact_at else None,
            "network_before_call": network_before_call,
            "current_owner": current_owner,
            "leading_finding": latest["leading_finding"],
            "next_action": next_action,
            "next_update_at": _iso(min(snapshot_at + timedelta(hours=1), effective_maturity_at)),
            "diagnostic_confidence": (
                0.93 if health == "RED" else 0.82 if health == "AMBER" else 0.97
            ),
            "production_write": False,
        }
        episodes.append(episode)

        if incident_id is not None and lifecycle == "PROMOTED_TO_INCIDENT":
            incident_time = started_at + timedelta(hours=float(plan.get("incident") or 0))
            repair_time = plan.get("repair")
            closed = repair_time is not None and age_hours >= float(repair_time) + 0.5
            incident = incidents_by_id.setdefault(
                incident_id,
                {
                    "incident_id": incident_id,
                    "root_incident_id": incident_id,
                    "origin": "INSTALL_ASSURANCE",
                    "status": "CLOSED" if closed else "OPEN",
                    "opened_at": _iso(incident_time),
                    "closed_at": (
                        _iso(started_at + timedelta(hours=float(repair_time) + 0.5))
                        if closed and repair_time is not None
                        else None
                    ),
                    "service_ids": [],
                    "episode_ids": [],
                    "technology": technology,
                    "delimiter_id": service.get("delimiter_id"),
                    "common_cause": scenario == "common_cause_hfc",
                    "fault_domain": (
                        "pon_odp" if "pon" in scenario else "hfc_tap"
                    ),
                    "work_order_ids": [],
                    "mr_ids": [],
                    "production_write": False,
                },
            )
            incident["service_ids"].append(service["service_id"])
            incident["episode_ids"].append(episode_id)
            incident["work_order_ids"].extend(work_order_ids)
            incident["mr_ids"].extend(mr_ids)

        incident = incidents_by_id.get(incident_id or "")
        dalli_contexts.append(
            project_install_assurance_context(
                episode=episode,
                contact=contact,
                incident=incident,
            )
        )

    incidents = list(incidents_by_id.values())
    for incident in incidents:
        incident["service_ids"] = sorted(set(incident["service_ids"]))
        incident["episode_ids"] = sorted(set(incident["episode_ids"]))
        incident["work_order_ids"] = sorted(set(incident["work_order_ids"]))
        incident["mr_ids"] = sorted(set(incident["mr_ids"]))

    matured = [
        episode
        for episode in episodes
        if snapshot_at >= (_parse(episode["effective_maturity_at"]) or snapshot_at)
    ]
    passed = [episode for episode in episodes if episode["lifecycle_state"] == "PASSED_24H"]
    intervened = [episode for episode in episodes if episode["action_types"]]
    remote_stabilized = [
        episode
        for episode in episodes
        if episode["outcome"] == "PASSED_AFTER_REMOTE_STABILIZATION"
    ]
    promoted = [
        episode
        for episode in episodes
        if episode["lifecycle_state"] == "PROMOTED_TO_INCIDENT"
    ]
    network_before = [contact for contact in contacts if any(
        episode["episode_id"] == contact["episode_id"] and episode["network_before_call"]
        for episode in episodes
    )]
    stable_durations = [
        (
            (_parse(episode["stable_since"]) or snapshot_at)
            - (_parse(episode["started_at"]) or snapshot_at)
        ).total_seconds()
        / 3600
        for episode in episodes
        if episode.get("stable_since")
    ]
    lifecycle_partition = {
        state: sum(episode["lifecycle_state"] == state for episode in episodes)
        for state in LIFECYCLE_STATES
    }
    health_partition = {
        state: sum(episode["health_state"] == state for episode in episodes)
        for state in HEALTH_STATES
    }
    summary = {
        "version": INSTALL_ASSURANCE_VERSION,
        "watch_id": watch_id,
        "cohort_id": cohort_id,
        "parent_run_id": run_id,
        "created_at": _iso(snapshot_at),
        "as_of_at": _iso(snapshot_at),
        "population": request.population,
        "as_of_hours": request.as_of_hours,
        "stability_tail_hours": request.stability_tail_hours,
        "measurement_context": {
            "mode": "24_hour_install_assurance_watch",
            "source": "synthetic_run_derived",
            "primary_grain": "install_assurance_episode",
            "window": "minimum_24_hours_plus_post_action_stability_tail",
            "parent_run_id": run_id,
            "canonical_run_unchanged": True,
            "completeness": "full_child_artifact",
            "production_writes": False,
        },
        "metrics": {
            "episodes_entering_watch": request.population,
            "baseline_accepted": sum(
                episode["baseline_status"] == "ACCEPTED" for episode in episodes
            ),
            "matured_episodes": len(matured),
            "passed_24h": len(passed),
            "episodes_with_intervention": len(intervened),
            "remote_stabilized": len(remote_stabilized),
            "episodes_promoted_to_incident": len(promoted),
            "root_incidents": len(incidents),
            "care_contacts": len(contacts),
            "network_before_call_contacts": len(network_before),
            "mean_time_to_stable_service_hours": (
                round(sum(stable_durations) / len(stable_durations), 3)
                if stable_durations
                else None
            ),
            "baseline_acceptance_rate": _rate(
                sum(episode["baseline_status"] == "ACCEPTED" for episode in episodes),
                len(episodes),
            ),
            "pass_rate_24h": _rate(len(passed), len(matured)),
            "intervention_rate": _rate(len(intervened), len(episodes)),
            "remote_stabilization_rate": _rate(len(remote_stabilized), len(intervened)),
            "incident_conversion_rate": _rate(len(promoted), len(episodes)),
            "network_before_call_rate": _rate(len(network_before), len(contacts)),
        },
        "lifecycle_partition": lifecycle_partition,
        "health_partition": health_partition,
        "workload": {
            "remote_actions": sum(
                row["action_type"] == "controlled_remote_reprovision" for row in actions
            ),
            "clean_boots_work_orders": sum(bool(row.get("work_order_id")) for row in actions),
            "maintenance_requests": sum(bool(row.get("mr_id")) for row in actions),
            "open_install_incidents": sum(incident["status"] == "OPEN" for incident in incidents),
        },
        "reconciliation": {
            "healthy_passed_without_incident": all(
                episode["incident_id"] is None
                for episode in passed
            ),
            "promoted_have_incident": all(
                episode["incident_id"] is not None
                for episode in promoted
            ),
            "status_partition_balances": sum(lifecycle_partition.values()) == len(episodes),
            "health_partition_balances": sum(health_partition.values()) == len(episodes),
            "contacts_restart_no_diagnostics": all(
                not contact["diagnostics_restarted"] for contact in contacts
            ),
            "canonical_parent_run_unchanged": True,
        },
        "dalli": {
            "canonical_name": "DvSum DALLI",
            "live_connection": False,
            "contexts": len(dalli_contexts),
            "genesys_contacts": len(contacts),
        },
        "caddi": {
            "canonical_name": "DvSum DALLI",
            "compatibility_alias": True,
            "live_connection": False,
            "contexts": len(dalli_contexts),
            "genesys_contacts": len(contacts),
        },
        "production_writes": False,
    }
    return InstallWatchArtifact(
        summary=summary,
        episodes=episodes,
        observations=observations,
        actions=actions,
        contacts=contacts,
        incidents=incidents,
        dalli_contexts=dalli_contexts,
    )


def install_assurance_contract() -> dict[str, Any]:
    """Return the separate semantic contract for supervised installations."""

    return {
        "scenario": "24-Hour Install Assurance Watch",
        "primary_entity": {
            "name": "install_assurance_episode",
            "key": "episode_id",
            "not_an_incident_until": "PROMOTED_TO_INCIDENT",
        },
        "identity_chain": [
            "install_work_order_id",
            "episode_id",
            "service_id",
            "device_id",
            "genesys_interaction_id",
            "incident_id",
            "work_order_id",
            "mr_id",
        ],
        "lifecycle_states": list(LIFECYCLE_STATES),
        "health_states": list(HEALTH_STATES),
        "metrics": {
            "episodes_entering_watch": {
                "grain": "episode_id",
                "formula": "distinct episodes opened",
            },
            "baseline_acceptance_rate": {
                "grain": "episode_id",
                "formula": "accepted baselines / episodes opened",
            },
            "pass_rate_24h": {
                "grain": "episode_id",
                "formula": "PASSED_24H / effectively matured episodes",
                "denominator_excludes": "active episodes whose effective maturity is future",
            },
            "intervention_rate": {
                "grain": "episode_id",
                "formula": "episodes with one or more actions / episodes opened",
            },
            "remote_stabilization_rate": {
                "grain": "episode_id",
                "formula": "passed after remote action / intervened episodes",
            },
            "incident_conversion_rate": {
                "grain": "episode_id",
                "formula": "promoted episodes / episodes opened",
            },
            "network_before_call_rate": {
                "grain": "contact_id",
                "formula": "watch contacts preceded by a finding / watch contacts",
            },
        },
        "separation_policy": {
            "break_fix_metrics_unchanged": True,
            "healthy_installs_create_incident": False,
            "promoted_incident_grain": "root incident_id",
            "pending_approvals_are_workload_not_status": True,
        },
        "minimum_window_policy": (
            "effective maturity is the later of start + 24 hours and the last "
            "service-affecting action + the configured stability tail"
        ),
        "source_boundaries": {
            "episode_authority": "LPR Install Assurance",
            "analytical_layer": "DvSum DALLI",
            "interaction_channel": "Genesys",
            "incident_and_repair_authority": "LPR Operations and jTrack",
        },
        "production_writes": False,
    }


def create_install_assurance_watch(
    run_path: Path,
    *,
    population: int = 12,
    as_of_hours: float = 24.0,
    stability_tail_hours: float = 4.0,
    seed: int = 0,
) -> dict[str, Any]:
    """Create an immutable 24-hour install-assurance child artifact."""

    run_path = Path(run_path).resolve()
    request = InstallWatchRequest(
        population=population,
        as_of_hours=as_of_hours,
        stability_tail_hours=stability_tail_hours,
        seed=seed,
    )
    if request.population > MAX_INSTALL_POPULATION:
        raise ValueError(
            f"population must not exceed {MAX_INSTALL_POPULATION:,} for one watch"
        )
    if not 0 <= request.as_of_hours <= 72:
        raise ValueError("as_of_hours must be between 0 and 72")
    if not 1 <= request.stability_tail_hours <= 12:
        raise ValueError("stability_tail_hours must be between 1 and 12")

    artifact = _build_artifact(run_path, request)
    root = run_path / "install_assurance"
    root.mkdir(parents=True, exist_ok=True)
    final = root / artifact.summary["watch_id"]
    summary_path = final / "summary.json"
    if summary_path.is_file():
        return json.loads(summary_path.read_text(encoding="utf-8"))

    build = root / f".{artifact.summary['watch_id']}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
    build.mkdir(parents=False, exist_ok=False)
    try:
        write_jsonl_gz(build / "episodes.jsonl.gz", artifact.episodes)
        write_jsonl_gz(build / "observations.jsonl.gz", artifact.observations)
        write_jsonl_gz(build / "actions.jsonl.gz", artifact.actions)
        write_jsonl_gz(build / "contacts.jsonl.gz", artifact.contacts)
        write_jsonl_gz(build / "incidents.jsonl.gz", artifact.incidents)
        write_jsonl_gz(build / "dalli_contexts.jsonl.gz", artifact.dalli_contexts)
        (build / "summary.json").write_text(
            json.dumps(artifact.summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        replace_with_retry(build, final)
    except Exception:
        shutil.rmtree(build, ignore_errors=True)
        raise
    return artifact.summary


def list_install_assurance_watches(run_path: Path) -> list[dict[str, Any]]:
    root = Path(run_path) / "install_assurance"
    if not root.is_dir():
        return []
    result: list[dict[str, Any]] = []
    for path in root.glob(f"{WATCH_PREFIX}*/summary.json"):
        try:
            result.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(
        result,
        key=lambda row: (str(row.get("as_of_at", "")), str(row.get("watch_id", ""))),
        reverse=True,
    )


def load_install_assurance_watch(
    run_path: Path,
    watch_id: str,
    *,
    limit: int = 500,
) -> dict[str, Any]:
    watch_id = _validate_watch_id(watch_id)
    path = Path(run_path) / "install_assurance" / watch_id
    if not path.is_dir():
        raise KeyError(watch_id)
    context_path = path / "dalli_contexts.jsonl.gz"
    if not context_path.is_file():
        context_path = path / "caddi_contexts.jsonl.gz"
    dalli_contexts = load_jsonl_gz(context_path, limit=limit)
    return {
        "summary": json.loads((path / "summary.json").read_text(encoding="utf-8")),
        "episodes": load_jsonl_gz(path / "episodes.jsonl.gz", limit=limit),
        "observations": load_jsonl_gz(path / "observations.jsonl.gz", limit=limit),
        "actions": load_jsonl_gz(path / "actions.jsonl.gz", limit=limit),
        "contacts": load_jsonl_gz(path / "contacts.jsonl.gz", limit=limit),
        "incidents": load_jsonl_gz(path / "incidents.jsonl.gz", limit=limit),
        "dalli_contexts": dalli_contexts,
        "caddi_contexts": dalli_contexts,
    }


def latest_install_assurance_projection(run_path: Path) -> dict[str, Any] | None:
    watches = list_install_assurance_watches(run_path)
    if not watches:
        return None
    watch_id = str(watches[0]["watch_id"])
    detail = load_install_assurance_watch(run_path, watch_id, limit=5000)
    return {
        "summary": detail["summary"],
        "episodes": detail["episodes"],
        "contacts": detail["contacts"],
        "incidents": detail["incidents"],
        "dalli_contexts": detail["dalli_contexts"],
        "caddi_contexts": detail["dalli_contexts"],
    }
