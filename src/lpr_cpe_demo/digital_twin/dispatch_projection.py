"""Project one Digital Twin run into cost and dispatch records.

The legacy cost and footprint pages historically generated an unrelated seeded
fault population. This module keeps the proven geography and effort assumptions,
but takes its incident, service, technology, delimiter, action, work-order, MR
and timing inputs from an immutable Digital Twin run.

The result is intentionally explicit about mixed provenance:

* run-derived facts: service/case/incident identity, scenario, RCA, action,
  work-order and MR records, generated timestamps and lifecycle state;
* modelled geography: the run's generated region and delimiter are mapped
  deterministically to the Puerto Rico planning geography because the synthetic
  subscriber master has no surveyed latitude/longitude;
* assumed economics: labour, vehicle, ferry, overnight and parts rates remain
  the demonstration assumptions in :mod:`lpr_cpe_demo.effort`.

Nothing in this projection writes to the parent run or to an external system.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lpr_cpe_demo.benchmarks import roll_cost, wasted_visit_cost
from lpr_cpe_demo.effort import (
    DURATIONS,
    RATES,
    ROAD_KM_PER_MINUTE,
    false_negative_cost,
)
from lpr_cpe_demo.geography import (
    DISPATCH_BASES,
    SITE_BY_ID,
    Site,
    select_base,
    sites_in_cpe_footprint,
)
from lpr_cpe_demo.plant import DOMAIN_TO_KIND, blast_radius

from .care import PRIORITY
from .decision import SCENARIO_POLICIES
from .storage import get_active_run, iter_jsonl_gz, safe_run_path

DISPATCH_PROJECTION_SCHEMA_VERSION = "1.0"

JITTER_KM: dict[str, float] = {
    "metro": 3.0,
    "coastal": 5.5,
    "mountain": 7.0,
    "remote_island": 4.0,
}
DELIMITER_OFFSET_KM: dict[str, float] = {
    "metro": 0.25,
    "coastal": 0.5,
    "mountain": 1.2,
    "remote_island": 0.7,
}

DISPATCH_ACTIONS = {"dispatch_clean", "cpe_swap", "create_mr", "plant_repair"}
REMOTE_ACTIONS = {"remote_repair"}

GENERATED_SKILL_TO_PLANNING: dict[str, tuple[str, ...]] = {
    "CPE_SWAP_CERTIFIED": ("cpe_swap",),
    "CLEAN_BOOTS_CERTIFIED": ("drop_replacement",),
    "HFC_PLANT": ("hfc_plant",),
    "PON_PLANT": ("fibre_splice",),
    "REMOTE_ASSURANCE": (),
}


def _generated_parts_to_planning(
    parts: Iterable[Any],
    *,
    family: str,
) -> tuple[str, ...]:
    mapped: set[str] = set()
    for part in parts:
        source = str(part)
        if source == "replacement_cpe":
            mapped.add("cpe")
        elif source == "drop_repair_kit":
            mapped.add("drop")
        elif source in {"plant_test_kit", "repair_materials"}:
            mapped.add("splice_kit" if family == "PON" else "connectors")
        # premise_test_kit has no separate stock key in the planning hub model.
    return tuple(sorted(mapped))


def dispatch_cost_contract() -> dict[str, Any]:
    """Return the source and calculation contract used by both linked pages."""

    return {
        "schema_version": DISPATCH_PROJECTION_SCHEMA_VERSION,
        "primary_grain": "case_id",
        "run_derived_inputs": [
            "service_id",
            "device_id",
            "case_id",
            "incident_id",
            "scenario",
            "technology",
            "generated region",
            "delimiter type and identifier",
            "deterministic domain and action",
            "action lifecycle status",
            "work-order skill, parts and timestamps",
            "JTrack/MR identity",
            "validation and closure state",
        ],
        "modelled_inputs": [
            "municipio assignment within the generated region",
            "premise, delimiter and intervention coordinates",
            "dispatch hub selection and road/ferry route",
            "blast radius where not directly observed",
        ],
        "assumed_inputs": [
            "labour rates",
            "vehicle cost",
            "ferry and overnight premiums",
            "parts cost",
            "default triage, RCA, validation and closure durations",
        ],
        "cost_bases": {
            "generated_execution": (
                "The demo executed the action. Generated work-order timestamps are used "
                "when available; rates remain assumed."
            ),
            "governed_forecast": (
                "The action is pending or recommended. The cost is a forecast based on "
                "the deterministic next action and the same assumed rates."
            ),
        },
        "production_writes": False,
    }


def _load_rows(run_path: Path, dataset: str) -> list[dict[str, Any]]:
    path = run_path / f"{dataset}.jsonl.gz"
    if not path.exists():
        return []
    return list(iter_jsonl_gz(path))


def _case_subscribers(
    run_path: Path,
    service_ids: set[str],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Load only case services and the small delimiter groups they belong to.

    A board/full run may contain 500,000 subscriber rows while the case population
    is approximately 0.5% of the footprint. Loading the complete subscriber master
    solely to draw those cases would make the linked pages unnecessarily expensive.
    Two streaming passes keep memory proportional to the selected case/delimiter
    population.
    """

    path = run_path / "subscriber_master.jsonl.gz"
    if not path.exists() or not service_ids:
        return {}, []

    selected: dict[str, dict[str, Any]] = {}
    delimiter_ids: set[str] = set()
    for row in iter_jsonl_gz(path):
        service_id = str(row.get("service_id", ""))
        if service_id not in service_ids:
            continue
        selected[service_id] = row
        delimiter_id = str(row.get("delimiter_id", ""))
        if delimiter_id:
            delimiter_ids.add(delimiter_id)
        if len(selected) == len(service_ids):
            break

    grouped: list[dict[str, Any]] = []
    if delimiter_ids:
        for row in iter_jsonl_gz(path):
            if str(row.get("delimiter_id", "")) in delimiter_ids:
                grouped.append(row)
    else:
        grouped.extend(selected.values())
    return selected, grouped


def _resolve_run_path(root_or_run_path: Path, run_id: str | None) -> Path:
    path = Path(root_or_run_path)
    if run_id is not None:
        return safe_run_path(path, run_id)
    if (path / "catalog.json").is_file():
        return path.resolve()
    active_run_id = get_active_run(path)
    if active_run_id is None:
        raise FileNotFoundError("no active run")
    return safe_run_path(path, active_run_id)


def _index(rows: Iterable[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {str(row[key]): row for row in rows if row.get(key) not in {None, ""}}


def _records_by_case(
    rows: Iterable[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        case_id = str(row.get("case_id", ""))
        if case_id:
            grouped[case_id].append(row)
    for values in grouped.values():
        values.sort(key=_record_time)
    return dict(grouped)


def _record_time(row: Mapping[str, Any]) -> str:
    for field in (
        "event_timestamp",
        "dispatched_at",
        "created_at",
        "opened_at",
        "completed_at",
    ):
        if row.get(field):
            return str(row[field])
    return ""


def _parse_ts(value: Any) -> datetime | None:
    if value in {None, ""}:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _duration_minutes(row: Mapping[str, Any], start: str, end: str) -> int | None:
    left = _parse_ts(row.get(start))
    right = _parse_ts(row.get(end))
    if left is None or right is None or right < left:
        return None
    return max(0, round((right - left).total_seconds() / 60.0))


def _technology_family(value: Any) -> str:
    technology = str(value or "HFC").upper().replace("-", "_")
    return "HFC" if technology == "HFC" else "PON"


def _stable_index(key: str, size: int) -> int:
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % size


def _stable_offset(key: str, radius_km: float) -> tuple[float, float]:
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    angle = (digest[0] / 255.0) * 2 * math.pi
    distance = radius_km * math.sqrt(digest[1] / 255.0)
    dlat = (distance / 111.32) * math.cos(angle)
    dlon = (distance / (111.32 * math.cos(math.radians(18.2)))) * math.sin(angle)
    return round(dlat, 6), round(dlon, 6)


def _site_candidates(archetype: str, technology: str) -> list[Site]:
    family = _technology_family(technology)
    candidates = [
        site
        for site in sites_in_cpe_footprint()
        if site.archetype == archetype and family in site.technologies
    ]
    if candidates:
        return candidates
    candidates = [
        site
        for site in sites_in_cpe_footprint()
        if family in site.technologies
    ]
    return candidates or list(sites_in_cpe_footprint())


def _site_assignments(
    subscribers: Iterable[dict[str, Any]],
) -> dict[str, Site]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in subscribers:
        group_id = str(row.get("delimiter_id") or row.get("service_id") or "")
        if group_id:
            grouped[group_id].append(row)

    assignments: dict[str, Site] = {}
    for group_id, rows in grouped.items():
        regions = Counter(str(row.get("region") or "coastal") for row in rows)
        largest_group = max(regions.values())
        candidate_regions = sorted(
            region for region, count in regions.items() if count == largest_group
        )
        archetype = candidate_regions[
            _stable_index(group_id, len(candidate_regions))
        ]
        technology = str(rows[0].get("technology") or "HFC")
        candidates = _site_candidates(archetype, technology)
        assignments[group_id] = candidates[_stable_index(group_id, len(candidates))]
    return assignments


def _coordinates(
    subscriber: Mapping[str, Any],
    site: Site,
    domain: str,
) -> dict[str, Any]:
    premise_id = str(subscriber.get("premise_id") or subscriber.get("service_id"))
    delimiter_id = str(subscriber.get("delimiter_id") or premise_id)
    access_port_id = str(subscriber.get("access_port_id") or delimiter_id)

    hh_dlat, hh_dlon = _stable_offset(premise_id, JITTER_KM[site.archetype])
    household_lat = site.lat + hh_dlat
    household_lon = site.lon + hh_dlon

    del_dlat, del_dlon = _stable_offset(
        delimiter_id,
        DELIMITER_OFFSET_KM[site.archetype],
    )
    delimiter_lat = household_lat + del_dlat
    delimiter_lon = household_lon + del_dlon

    kind = DOMAIN_TO_KIND.get(domain, "household")
    family = _technology_family(subscriber.get("technology"))
    if kind == "hfc_node" and family == "PON":
        kind = "pon_port"

    if kind == "household":
        intervention_id = premise_id
        intervention_lat = household_lat
        intervention_lon = household_lon
    elif kind == "drop":
        intervention_id = f"DROP-{subscriber.get('service_id', premise_id)}"
        intervention_lat = (household_lat + delimiter_lat) / 2
        intervention_lon = (household_lon + delimiter_lon) / 2
    elif kind in {"tap", "odp"}:
        intervention_id = delimiter_id
        intervention_lat = delimiter_lat
        intervention_lon = delimiter_lon
    else:
        up_dlat, up_dlon = _stable_offset(
            access_port_id,
            JITTER_KM[site.archetype] * 0.6,
        )
        intervention_id = access_port_id
        intervention_lat = site.lat + up_dlat
        intervention_lon = site.lon + up_dlon

    return {
        "household_id": premise_id,
        "household_lat": round(household_lat, 5),
        "household_lon": round(household_lon, 5),
        "delimiter_kind": str(subscriber.get("delimiter_type", "")).lower(),
        "delimiter_id": delimiter_id,
        "delimiter_lat": round(delimiter_lat, 5),
        "delimiter_lon": round(delimiter_lon, 5),
        "intervention_kind": kind,
        "intervention_id": intervention_id,
        "intervention_lat": round(intervention_lat, 5),
        "intervention_lon": round(intervention_lon, 5),
        "intervention_is_at_premise": kind in {"household", "drop"},
    }


def _priority(rows: Iterable[dict[str, Any]], scenario: str) -> str:
    ranking = {"P1": 0, "P2": 1, "P3": 2}
    values = [str(row.get("priority")) for row in rows if row.get("priority")]
    if values:
        return min(values, key=lambda value: ranking.get(value, 9))
    return PRIORITY.get(scenario, "P3")


def _field_requirements(
    action: str,
    family: str,
    work_orders: list[dict[str, Any]],
) -> tuple[str, tuple[str, ...], tuple[str, ...], str]:
    if work_orders:
        source = work_orders[0]
        crew = (
            "dirty"
            if str(source.get("crew_domain")).upper() == "PLANT"
            else "clean"
        )
        generated_skill = str(source.get("required_skill") or "")
        skills = GENERATED_SKILL_TO_PLANNING.get(generated_skill, ())
        parts = _generated_parts_to_planning(
            source.get("parts_required", []) or [],
            family=family,
        )
        if skills or parts:
            return crew, skills, parts, "generated_work_order_readiness_adapter"

    if action in {"create_mr", "plant_repair"}:
        crew = "dirty"
    elif action in {"dispatch_clean", "cpe_swap"}:
        crew = "clean"
    else:
        return "remote", (), (), "no_field_dispatch"

    if crew == "dirty" and family == "PON":
        return crew, ("fibre_splice",), ("splice_kit",), "action_forecast"
    if crew == "dirty":
        return crew, ("hfc_plant",), ("connectors",), "action_forecast"
    if action == "cpe_swap":
        return crew, ("cpe_swap",), ("cpe",), "action_forecast"
    return crew, ("drop_replacement",), ("drop",), "action_forecast"


def _route_projection(
    *,
    site: Site,
    destination: tuple[float, float],
    crew: str,
    required_skills: tuple[str, ...],
    required_parts: tuple[str, ...],
    generated_one_way_minutes: int | None,
    generated_on_site_minutes: int | None,
) -> dict[str, Any]:
    if crew not in {"clean", "dirty"}:
        return {
            "available": False,
            "reason": "The generated or recommended action does not require field dispatch.",
            "base_id": "",
            "base_name": "No field dispatch",
            "modelled_one_way_minutes": 0,
            "generated_one_way_minutes": generated_one_way_minutes,
            "display_one_way_minutes": 0,
            "requires_ferry": False,
            "same_day_feasible": True,
            "legs": [],
            "path_record": None,
            "rejected_for_skills": [],
            "rejected_for_parts": [],
            "warning": "",
        }

    warning = ""
    try:
        selection = select_base(
            site,
            crew_type=crew,
            required_skills=required_skills,
            required_parts=required_parts,
            destination=destination,
        )
    except LookupError as exc:
        selection = select_base(site, crew_type=crew, destination=destination)
        warning = f"Generated readiness requirements could not be staged exactly: {exc}"

    path = [[selection.base.lon, selection.base.lat]]
    if selection.plan.requires_ferry and site.ferry_from:
        terminal = SITE_BY_ID[site.ferry_from]
        path.append([terminal.lon, terminal.lat])
    path.append([destination[1], destination[0]])

    on_site = generated_on_site_minutes
    if on_site is None:
        on_site = DURATIONS[
            "clean_boots_on_site" if crew == "clean" else "dirty_boots_on_site"
        ]
    same_day = (2 * selection.plan.total_minutes + on_site) <= 480
    display_minutes = (
        generated_one_way_minutes
        if generated_one_way_minutes is not None
        else selection.plan.total_minutes
    )
    return {
        "available": True,
        "reason": "",
        "base_id": selection.base.base_id,
        "base_name": selection.base.name,
        "modelled_one_way_minutes": selection.plan.total_minutes,
        "generated_one_way_minutes": generated_one_way_minutes,
        "display_one_way_minutes": display_minutes,
        "requires_ferry": selection.plan.requires_ferry,
        "same_day_feasible": same_day,
        "legs": [
            {
                "kind": leg.kind,
                "description": leg.description,
                "minutes": leg.minutes,
            }
            for leg in selection.plan.legs
        ],
        "path_record": {
            "path": path,
            "colour": [12, 84, 87, 220],
            "label": (
                f"{selection.base.name} to {site.municipio}: "
                f"{selection.plan.total_minutes} modelled min one way"
            ),
        },
        "rejected_for_skills": list(selection.rejected_for_skills),
        "rejected_for_parts": list(selection.rejected_for_parts),
        "warning": warning,
    }


def _labour(rate_key: str, minutes: int) -> float:
    return RATES[rate_key] * minutes / 60.0


def _append_line(
    lines: list[dict[str, Any]],
    *,
    step: str,
    role: str,
    minutes: int,
    cost_usd: float,
    duration_provenance: str,
    note: str = "",
) -> None:
    lines.append(
        {
            "step": step,
            "role": role,
            "minutes": int(minutes),
            "cost_usd": round(float(cost_usd), 2),
            "duration_provenance": duration_provenance,
            "rate_provenance": "assumed_demo_rate",
            "note": note,
        }
    )


def _parts_cost_key(action: str, domain: str, family: str) -> str | None:
    if action == "cpe_swap" or domain == "cpe":
        return "parts_cpe"
    if domain in {"drop", "premise_wiring"}:
        return "parts_drop"
    if domain == "pon_odp" or (domain in {"plant", "shared_network"} and family == "PON"):
        return "parts_odp"
    if domain == "hfc_tap" or domain in {"plant", "shared_network"}:
        return "parts_tap"
    return None


def _cost_projection(
    *,
    case_id: str,
    action: str,
    action_status: str,
    domain: str,
    family: str,
    route: Mapping[str, Any],
    work_orders: list[dict[str, Any]],
    human_required: bool,
    validated: bool,
    closed: bool,
) -> dict[str, Any]:
    executed = action_status == "SIMULATED_EXECUTED"
    basis = "generated_execution" if executed else "governed_forecast"
    lines: list[dict[str, Any]] = []

    _append_line(
        lines,
        step="triage",
        role="noc analyst",
        minutes=DURATIONS["triage"],
        cost_usd=_labour("noc_analyst_hour", DURATIONS["triage"]),
        duration_provenance="assumed_standard_duration",
    )
    _append_line(
        lines,
        step="RCA",
        role="noc analyst",
        minutes=DURATIONS["rca_cycle"],
        cost_usd=_labour("noc_analyst_hour", DURATIONS["rca_cycle"]),
        duration_provenance="assumed_standard_duration",
    )
    if human_required:
        _append_line(
            lines,
            step="governance review",
            role="l2 sme",
            minutes=DURATIONS["gate_review"],
            cost_usd=_labour("l2_sme_hour", DURATIONS["gate_review"]),
            duration_provenance="assumed_standard_duration",
            note="Required by the generated reconciliation/human-decision record.",
        )

    truck_rolls = 0
    generated_travel_minutes: list[int] = []
    generated_on_site_minutes: list[int] = []

    if action in REMOTE_ACTIONS:
        _append_line(
            lines,
            step="remote action",
            role="noc analyst",
            minutes=DURATIONS["remote_attempt"],
            cost_usd=_labour("noc_analyst_hour", DURATIONS["remote_attempt"]),
            duration_provenance="assumed_standard_duration",
            note=f"{action} · {action_status or 'recommended'}",
        )
    elif action == "collect_evidence":
        _append_line(
            lines,
            step="expanded evidence collection",
            role="noc analyst",
            minutes=DURATIONS["rca_cycle"],
            cost_usd=_labour("noc_analyst_hour", DURATIONS["rca_cycle"]),
            duration_provenance="assumed_standard_duration",
        )
    elif action in DISPATCH_ACTIONS:
        visits = work_orders if executed and work_orders else [{}]
        truck_rolls = len(visits)
        crew = "clean" if action in {"dispatch_clean", "cpe_swap"} else "dirty"
        if work_orders:
            crew = (
                "dirty"
                if str(work_orders[0].get("crew_domain")).upper() == "PLANT"
                else "clean"
            )
        rate_key = "clean_boots_hour" if crew == "clean" else "dirty_boots_hour"

        if action in {"create_mr", "plant_repair"}:
            _append_line(
                lines,
                step="MR handoff package",
                role="field/plant handoff",
                minutes=DURATIONS["handover_package"],
                cost_usd=_labour(rate_key, DURATIONS["handover_package"]),
                duration_provenance="assumed_standard_duration",
            )
            _append_line(
                lines,
                step="MR handoff review",
                role="dispatcher",
                minutes=DURATIONS["handover_review"],
                cost_usd=_labour("dispatcher_hour", DURATIONS["handover_review"]),
                duration_provenance="assumed_standard_duration",
            )

        for position, work_order in enumerate(visits, start=1):
            _append_line(
                lines,
                step="dispatch planning",
                role="dispatcher",
                minutes=DURATIONS["dispatch_planning"],
                cost_usd=_labour("dispatcher_hour", DURATIONS["dispatch_planning"]),
                duration_provenance="assumed_standard_duration",
                note=f"visit {position}",
            )
            generated_one_way = _duration_minutes(work_order, "dispatched_at", "arrived_at")
            generated_on_site = _duration_minutes(work_order, "arrived_at", "completed_at")
            if generated_one_way is not None:
                generated_travel_minutes.append(generated_one_way)
            if generated_on_site is not None:
                generated_on_site_minutes.append(generated_on_site)

            one_way = generated_one_way
            duration_source = "generated_work_order_timestamps"
            if one_way is None:
                one_way = int(route.get("modelled_one_way_minutes", 0) or 0)
                duration_source = "modelled_dispatch_route"
            round_trip = 2 * one_way
            road_minutes = sum(
                int(leg.get("minutes", 0))
                for leg in route.get("legs", [])
                if leg.get("kind") == "road"
            )
            vehicle_cost = 2 * road_minutes * ROAD_KM_PER_MINUTE * RATES["vehicle_km"]
            _append_line(
                lines,
                step="travel",
                role=f"{crew} boots",
                minutes=round_trip,
                cost_usd=_labour(rate_key, round_trip) + vehicle_cost,
                duration_provenance=duration_source,
                note=f"{one_way} min each way; vehicle distance remains modelled.",
            )
            if route.get("requires_ferry"):
                _append_line(
                    lines,
                    step="ferry",
                    role=f"{crew} boots",
                    minutes=0,
                    cost_usd=RATES["ferry_round_trip"],
                    duration_provenance="modelled_route_condition",
                )
            on_site = generated_on_site
            on_site_source = "generated_work_order_timestamps"
            if on_site is None:
                on_site = DURATIONS[
                    "clean_boots_on_site"
                    if crew == "clean"
                    else "dirty_boots_on_site"
                ]
                on_site_source = "assumed_standard_duration"
            _append_line(
                lines,
                step=f"{crew} boots on site",
                role=f"{crew} boots",
                minutes=on_site,
                cost_usd=_labour(rate_key, on_site),
                duration_provenance=on_site_source,
            )
            if not route.get("same_day_feasible", True):
                _append_line(
                    lines,
                    step="overnight",
                    role=f"{crew} boots",
                    minutes=0,
                    cost_usd=RATES["overnight_premium"],
                    duration_provenance="modelled_route_condition",
                )

        parts_key = _parts_cost_key(action, domain, family)
        if parts_key:
            _append_line(
                lines,
                step="parts",
                role="inventory",
                minutes=0,
                cost_usd=RATES[parts_key],
                duration_provenance="not_applicable",
                note=parts_key,
            )
    else:
        _append_line(
            lines,
            step="manual review",
            role="l2 sme",
            minutes=DURATIONS["gate_review"],
            cost_usd=_labour("l2_sme_hour", DURATIONS["gate_review"]),
            duration_provenance="assumed_standard_duration",
            note=f"Unknown or missing action: {action or 'none'}",
        )

    if validated or not executed:
        _append_line(
            lines,
            step="validation",
            role="noc analyst",
            minutes=DURATIONS["verification"],
            cost_usd=_labour("noc_analyst_hour", DURATIONS["verification"]),
            duration_provenance="assumed_standard_duration",
            note="Generated validation exists." if validated else "Forecast validation.",
        )
    if closed or not executed:
        _append_line(
            lines,
            step="closure",
            role="noc analyst",
            minutes=DURATIONS["closure"],
            cost_usd=_labour("noc_analyst_hour", DURATIONS["closure"]),
            duration_provenance="assumed_standard_duration",
            note="Generated closed incident." if closed else "Forecast closure.",
        )

    total_minutes = sum(int(line["minutes"]) for line in lines)
    total_cost = round(sum(float(line["cost_usd"]) for line in lines), 2)
    return {
        "basis": basis,
        "ledger_rows": lines,
        "total_minutes": total_minutes,
        "total_cost_usd": total_cost,
        "truck_rolls": truck_rolls,
        "generated_travel_minutes": generated_travel_minutes,
        "generated_on_site_minutes": generated_on_site_minutes,
        "all_rates_assumed": True,
        "production_writes": False,
        "case_id": case_id,
    }


def _latest_timestamp(row_sets: Iterable[Iterable[dict[str, Any]]]) -> str:
    timestamps: list[str] = []
    fields = (
        "event_timestamp",
        "opened_at",
        "resolved_at",
        "closed_at",
        "dispatched_at",
        "arrived_at",
        "completed_at",
        "decided_at",
    )
    for rows in row_sets:
        for row in rows:
            for field in fields:
                if row.get(field):
                    timestamps.append(str(row[field]))
    return max(timestamps, default="")


def _summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    total_cost = round(sum(float(row["total_cost_usd"]) for row in cases), 2)
    generated_cost = round(
        sum(
            float(row["total_cost_usd"])
            for row in cases
            if row["cost_basis"] == "generated_execution"
        ),
        2,
    )
    forecast_cost = round(total_cost - generated_cost, 2)
    root_incidents = {str(row["incident_id"]) for row in cases if row.get("incident_id")}
    work_orders = {
        work_order_id
        for row in cases
        for work_order_id in row.get("work_order_ids", [])
    }
    mrs = {mr_id for row in cases for mr_id in row.get("mr_ids", [])}
    dirty_cases = [row for row in cases if row.get("crew_type") == "dirty"]
    dispatched = [row for row in cases if int(row.get("truck_rolls", 0)) > 0]
    return {
        "case_attempts": len(cases),
        "root_incidents": len(root_incidents),
        "generated_execution_cases": sum(
            row["cost_basis"] == "generated_execution" for row in cases
        ),
        "governed_forecast_cases": sum(
            row["cost_basis"] == "governed_forecast" for row in cases
        ),
        "combined_modelled_cost_usd": total_cost,
        "generated_execution_cost_usd": generated_cost,
        "governed_forecast_cost_usd": forecast_cost,
        "mean_cost_per_case_usd": round(total_cost / len(cases), 2) if cases else 0.0,
        "truck_rolls": sum(int(row.get("truck_rolls", 0)) for row in cases),
        "field_dispatched_cases": len(dispatched),
        "work_orders": len(work_orders),
        "maintenance_requests": len(mrs),
        "households_affected": sum(int(row.get("households_affected", 0)) for row in cases),
        "off_premise_interventions": sum(
            not bool(row.get("intervention_is_at_premise")) for row in cases
        ),
        "dirty_boots_share_pct": (
            round(100.0 * len(dirty_cases) / len(cases), 2) if cases else 0.0
        ),
        "ferry_jobs": sum(bool(row.get("requires_ferry")) for row in dispatched),
        "overnight_jobs": sum(
            not bool(row.get("same_day_feasible", True)) for row in dispatched
        ),
    }


def build_dispatch_cost_projection(
    root_or_run_path: Path,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Build the complete cost/dispatch projection for one immutable run."""

    run_path = _resolve_run_path(root_or_run_path, run_id)
    catalog_path = run_path / "catalog.json"
    if not catalog_path.is_file():
        raise FileNotFoundError("run catalog not found")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

    manifests = _load_rows(run_path, "scenario_manifests")
    service_ids = {
        str(row["service_id"])
        for row in manifests
        if row.get("service_id") not in {None, ""}
    }
    subscriber_by_service, subscriber_groups = _case_subscribers(
        run_path,
        service_ids,
    )
    incidents = _load_rows(run_path, "incidents")
    decisions = _load_rows(run_path, "deterministic_decisions")
    actions = _load_rows(run_path, "action_events")
    humans = _load_rows(run_path, "human_decisions")
    work_orders = _load_rows(run_path, "work_orders")
    mrs = _load_rows(run_path, "mrs")
    validations = _load_rows(run_path, "validation_events")
    resolutions = _load_rows(run_path, "resolution_events")
    care = _load_rows(run_path, "care_tickets")
    predictive = _load_rows(run_path, "predictive_tickets")

    incident_by_id = _index(incidents, "incident_id")
    decision_by_case = _index(decisions, "case_id")
    action_by_case = _index(actions, "case_id")
    human_by_case = _index(humans, "case_id")
    validation_by_case = _index(validations, "case_id")
    resolution_by_case = _index(resolutions, "case_id")
    work_by_case = _records_by_case(work_orders)
    mr_by_case = _records_by_case(mrs)
    care_by_case = _records_by_case(care)
    predictive_by_service: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in predictive:
        service_id = str(row.get("service_id", ""))
        if service_id:
            predictive_by_service[service_id].append(row)

    site_assignments = _site_assignments(subscriber_groups)
    cases: list[dict[str, Any]] = []

    for manifest in sorted(manifests, key=_record_time):
        case_id = str(manifest.get("case_id", ""))
        service_id = str(manifest.get("service_id", ""))
        incident_id = str(manifest.get("root_incident_id", ""))
        subscriber = subscriber_by_service.get(service_id, {})
        group_id = str(subscriber.get("delimiter_id") or service_id)
        site = site_assignments.get(group_id)
        if site is None:
            candidates = _site_candidates(
                str(subscriber.get("region") or "coastal"),
                str(subscriber.get("technology") or manifest.get("technology")),
            )
            site = candidates[_stable_index(group_id or case_id, len(candidates))]

        scenario = str(manifest.get("scenario", "unknown"))
        decision = decision_by_case.get(case_id, {})
        policy = SCENARIO_POLICIES.get(scenario, {})
        domain = str(
            decision.get("recommended_domain")
            or policy.get("domain")
            or "unknown"
        )
        recommended_action = str(
            decision.get("best_action")
            or policy.get("best_action")
            or "collect_evidence"
        )
        action_record = action_by_case.get(case_id, {})
        action = str(action_record.get("action") or recommended_action)
        action_status = str(action_record.get("status") or "RECOMMENDED")
        case_work_orders = work_by_case.get(case_id, [])
        case_mrs = mr_by_case.get(case_id, [])
        case_care = care_by_case.get(case_id, [])
        incident = incident_by_id.get(incident_id, {})
        human = human_by_case.get(case_id, {})
        validation = validation_by_case.get(case_id)
        resolution = resolution_by_case.get(case_id)
        technology = str(
            subscriber.get("technology")
            or manifest.get("technology")
            or "HFC"
        )
        family = _technology_family(technology)
        coords = _coordinates(subscriber, site, domain)
        generated_one_way = (
            _duration_minutes(case_work_orders[0], "dispatched_at", "arrived_at")
            if case_work_orders
            else None
        )
        generated_on_site = (
            _duration_minutes(case_work_orders[0], "arrived_at", "completed_at")
            if case_work_orders
            else None
        )
        crew, geometry_skills, geometry_parts, readiness_source = (
            _field_requirements(
                action,
                family,
                case_work_orders,
            )
        )
        route = _route_projection(
            site=site,
            destination=(coords["intervention_lat"], coords["intervention_lon"]),
            crew=crew,
            required_skills=geometry_skills,
            required_parts=geometry_parts,
            generated_one_way_minutes=generated_one_way,
            generated_on_site_minutes=generated_on_site,
        )
        cost = _cost_projection(
            case_id=case_id,
            action=action,
            action_status=action_status,
            domain=domain,
            family=family,
            route=route,
            work_orders=case_work_orders,
            human_required=bool(human.get("required")),
            validated=validation is not None,
            closed=str(incident.get("status", "")).upper() == "CLOSED",
        )
        missed = false_negative_cost(
            site.site_id,
            domain,
            destination=(coords["intervention_lat"], coords["intervention_lon"]),
        )
        benchmark = roll_cost(site.archetype, family, island=site.island)
        priority = _priority(case_care, scenario)
        region = str(subscriber.get("region") or site.archetype)
        work_order_ids = [str(row.get("work_order_id")) for row in case_work_orders]
        mr_ids = [str(row.get("mr_id")) for row in case_mrs]
        predictive_rows = predictive_by_service.get(service_id, [])
        source_skill = [
            str(row.get("required_skill"))
            for row in case_work_orders
            if row.get("required_skill")
        ]
        source_parts = sorted(
            {
                str(part)
                for row in case_work_orders
                for part in row.get("parts_required", []) or []
            }
        )
        total_cost = float(cost["total_cost_usd"])
        misdispatch_cost = round(total_cost + missed.cost_usd, 2)
        cases.append(
            {
                "run_id": catalog.get("run_id", run_path.name),
                "fault_id": case_id,
                "case_id": case_id,
                "root_case_id": manifest.get("root_case_id"),
                "incident_id": incident_id,
                "service_id": service_id,
                "device_id": subscriber.get("device_id"),
                "premise_id": subscriber.get("premise_id"),
                "scenario": scenario,
                "lifecycle_mode": manifest.get("lifecycle_mode"),
                "incident_status": incident.get("status", "UNKNOWN"),
                "incident_origin": incident.get("origin"),
                "technology": technology,
                "technology_family": family,
                "region": region,
                "site_id": site.site_id,
                "municipio": site.municipio,
                "archetype": site.archetype,
                "location_provenance": (
                    "Generated delimiter and majority generated region mapped "
                    "deterministically to the planning geography."
                ),
                "location_warning": (
                    "Subscriber region differs from the delimiter group's mapped region."
                    if region != site.archetype
                    else ""
                ),
                "true_domain": domain,
                "recommended_domain": domain,
                "recommended_action": recommended_action,
                "executed_or_forecast_action": action,
                "action_status": action_status,
                "priority": priority,
                "predictive_match": any(row.get("predictive_match") for row in case_care),
                "predictive_risk_count": len(predictive_rows),
                "care_contact_count": len(case_care),
                "human_decision_status": human.get("status"),
                "human_review_required": bool(human.get("required")),
                "work_order_ids": work_order_ids,
                "work_order_id": work_order_ids[0] if work_order_ids else None,
                "work_order_types": [
                    str(row.get("work_order_type"))
                    for row in case_work_orders
                    if row.get("work_order_type")
                ],
                "mr_ids": mr_ids,
                "mr_id": mr_ids[0] if mr_ids else None,
                "generated_required_skills": source_skill,
                "generated_parts_required": source_parts,
                "dispatch_required_skills": list(geometry_skills),
                "dispatch_required_parts": list(geometry_parts),
                "dispatch_readiness_source": readiness_source,
                "crew_type": crew,
                "base_id": str(route.get("base_id") or ""),
                "base_name": str(route.get("base_name") or "No field dispatch"),
                "travel_minutes": int(route.get("display_one_way_minutes", 0) or 0),
                "modelled_route_minutes": int(
                    route.get("modelled_one_way_minutes", 0) or 0
                ),
                "generated_route_minutes": route.get("generated_one_way_minutes"),
                "requires_ferry": bool(route.get("requires_ferry")),
                "same_day_feasible": bool(route.get("same_day_feasible", True)),
                "route": route,
                **coords,
                "households_affected": blast_radius(domain, site.site_id, family),
                "cost_basis": cost["basis"],
                "cost_provenance": (
                    "Demo-generated case/action/work-order inputs with modelled geography "
                    "and assumed economic rates."
                ),
                "total_minutes": int(cost["total_minutes"]),
                "total_cost_usd": total_cost,
                "truck_rolls": int(cost["truck_rolls"]),
                "misdispatch_cost_usd": misdispatch_cost,
                "misdispatch_premium_usd": round(misdispatch_cost - total_cost, 2),
                "benchmark_per_dispatch_usd": benchmark.per_dispatch_usd,
                "benchmark_per_completed_usd": benchmark.per_completed_usd,
                "benchmark_wasted_usd": wasted_visit_cost(
                    site.archetype,
                    family,
                    island=site.island,
                ),
                "benchmark_in_scope": benchmark.within_benchmark_scope,
                "ledger_rows": cost["ledger_rows"],
                "generated_travel_minutes": cost["generated_travel_minutes"],
                "generated_on_site_minutes": cost["generated_on_site_minutes"],
                "validated": validation is not None,
                "validation_id": (validation or {}).get("validation_id"),
                "resolution_id": (resolution or {}).get("resolution_id"),
                "production_write": False,
            }
        )

    summary = _summary(cases)
    return {
        "schema_version": DISPATCH_PROJECTION_SCHEMA_VERSION,
        "run_id": catalog.get("run_id", run_path.name),
        "release": catalog.get("release"),
        "measurement_context": {
            "mode": "digital_twin_run",
            "source": "immutable Digital Twin run",
            "run_id": catalog.get("run_id", run_path.name),
            "as_of": _latest_timestamp(
                (
                    manifests,
                    incidents,
                    actions,
                    work_orders,
                    mrs,
                    validations,
                    resolutions,
                )
            ),
            "window": "complete run snapshot",
            "primary_grain": "case_id",
            "completeness": "complete canonical run datasets; not paginated",
            "production_writes": False,
        },
        "summary": summary,
        "cases": cases,
        "provenance": {
            "run_derived": dispatch_cost_contract()["run_derived_inputs"],
            "modelled": dispatch_cost_contract()["modelled_inputs"],
            "assumed": dispatch_cost_contract()["assumed_inputs"],
            "hub_locations_assumed": all(base.assumed for base in DISPATCH_BASES),
        },
        "reconciliation": {
            "case_attempts_equal_manifest_rows": len(cases) == len(manifests),
            "work_order_ids_projected": summary["work_orders"],
            "source_work_order_ids": len(
                {
                    str(row.get("work_order_id"))
                    for row in work_orders
                    if row.get("work_order_id")
                }
            ),
            "mr_ids_projected": summary["maintenance_requests"],
            "source_mr_ids": len(
                {str(row.get("mr_id")) for row in mrs if row.get("mr_id")}
            ),
        },
    }
