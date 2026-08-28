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
from collections import defaultdict
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
from .storage import (
    RUN_SCHEMA_VERSION,
    get_active_run,
    iter_jsonl_gz,
    safe_run_path,
    sha256_file,
)

DISPATCH_PROJECTION_SCHEMA_VERSION = "1.1"

PROJECTION_REQUIRED_DATASETS = frozenset(
    {
        "subscriber_master",
        "scenario_manifests",
        "incidents",
        "deterministic_decisions",
        "action_events",
        "human_decisions",
        "work_orders",
        "mrs",
        "validation_events",
        "resolution_events",
        "care_tickets",
        "predictive_tickets",
    }
)

REQUIRED_CLOSURE_CHECKS = frozenset(
    {
        "original_symptom_absent",
        "service_test_passed",
        "telemetry_stable",
        "repair_actions_documented",
        "required_measurements_captured",
    }
)

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


class MixedRegionDelimiterError(ValueError):
    """Raised when one serving TAP/ODP spans multiple planning regions."""


class DispatchProjectionIntegrityError(ValueError):
    """Raised when an immutable run fails catalog or identity integrity checks."""

    def __init__(self, issues: Iterable[str]):
        unique = tuple(dict.fromkeys(str(issue) for issue in issues if str(issue)))
        self.issues = unique
        super().__init__("; ".join(unique) or "dispatch projection integrity check failed")


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
            "municipio assignment within the delimiter's generated region",
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
                "The demo executed the action. Generated work-order timestamps, road "
                "distance, ferry use and overnight use are used when present. The "
                "planning route is comparison-only; rates remain assumed."
            ),
            "governed_forecast": (
                "The action is pending or recommended. The cost is a forecast based on "
                "the deterministic next action, modelled route and the same assumed rates."
            ),
        },
        "integrity_controls": [
            "every catalog dataset hash and row count is verified before costing",
            "every case must join to its subscriber, root incident and deterministic decision",
            "work orders, MRs, validation and resolution records must remain case-local",
            (
                "executed cost never imports ferry, overnight or vehicle charges "
                "from the planning route"
            ),
            "validation requires PASS, stable telemetry and a complete closure checklist",
            "reconciliation compares exact identifier sets rather than counts alone",
        ],
        "topology_controls": [
            "one delimiter_id must map to exactly one planning region",
            "mixed-region delimiter groups are rejected; no majority or tie-break is used",
            "runs generated before the delimiter-region fix must be regenerated",
        ],
        "production_writes": False,
    }


def _catalog_entries(catalog: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    issues: list[str] = []
    entries: dict[str, dict[str, Any]] = {}
    raw_entries = catalog.get("datasets")
    if not isinstance(raw_entries, list):
        raise DispatchProjectionIntegrityError(["catalog datasets must be a list"])
    for position, raw in enumerate(raw_entries, start=1):
        if not isinstance(raw, dict):
            issues.append(f"catalog dataset entry {position} is not an object")
            continue
        dataset = str(raw.get("dataset") or "")
        if not dataset:
            issues.append(f"catalog dataset entry {position} has no dataset name")
            continue
        if dataset in entries:
            issues.append(f"catalog contains duplicate dataset entry {dataset}")
            continue
        entries[dataset] = raw
    missing = sorted(PROJECTION_REQUIRED_DATASETS - set(entries))
    issues.extend(f"catalog is missing required dataset {dataset}" for dataset in missing)
    if issues:
        raise DispatchProjectionIntegrityError(issues)
    return entries


def _verify_catalog_datasets(
    run_path: Path,
    catalog: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify every catalogued immutable file before producing financial output."""

    issues: list[str] = []
    checks: list[dict[str, Any]] = []
    entries = _catalog_entries(catalog)
    root = run_path.resolve()
    for dataset, entry in sorted(entries.items()):
        relative_path = str(entry.get("path") or f"{dataset}.jsonl.gz")
        path = (root / relative_path).resolve()
        if path.parent != root:
            issues.append(f"dataset path escapes run directory: {dataset}")
            continue
        if not path.is_file():
            issues.append(f"catalogued dataset file is missing: {dataset}")
            continue
        expected_hash = str(entry.get("sha256") or "")
        actual_hash = sha256_file(path)
        expected_rows = entry.get("row_count")
        try:
            actual_rows = sum(1 for _ in iter_jsonl_gz(path))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            issues.append(f"dataset {dataset} cannot be read: {exc}")
            continue
        if expected_hash != actual_hash:
            issues.append(
                f"dataset hash mismatch for {dataset}: expected {expected_hash}, "
                f"actual {actual_hash}"
            )
        try:
            expected_rows_int = int(expected_rows)
        except (TypeError, ValueError):
            issues.append(f"catalog row count is invalid for {dataset}: {expected_rows!r}")
            expected_rows_int = -1
        if expected_rows_int != actual_rows:
            issues.append(
                f"dataset row-count mismatch for {dataset}: expected "
                f"{expected_rows_int}, actual {actual_rows}"
            )
        checks.append(
            {
                "dataset": dataset,
                "row_count": actual_rows,
                "sha256": actual_hash,
                "hash_matches": expected_hash == actual_hash,
                "row_count_matches": expected_rows_int == actual_rows,
            }
        )
    if issues:
        raise DispatchProjectionIntegrityError(issues)
    return {
        "catalog_hashes_verified": True,
        "catalog_row_counts_verified": True,
        "datasets_verified": len(checks),
        "rows_verified": sum(int(check["row_count"]) for check in checks),
        "dataset_checks": checks,
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


def _duplicate_values(rows: Iterable[dict[str, Any]], key: str) -> list[str]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        value = str(row.get(key) or "")
        if value:
            counts[value] += 1
    return sorted(value for value, count in counts.items() if count > 1)


def _validate_case_graph(
    *,
    manifests: list[dict[str, Any]],
    subscribers: Mapping[str, dict[str, Any]],
    incidents: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    work_orders: list[dict[str, Any]],
    mrs: list[dict[str, Any]],
    validations: list[dict[str, Any]],
    resolutions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Require all economic records to remain on one canonical case graph."""

    issues: list[str] = []
    duplicate_cases = _duplicate_values(manifests, "case_id")
    issues.extend(f"duplicate scenario manifest case_id {value}" for value in duplicate_cases)
    duplicate_work_orders = _duplicate_values(work_orders, "work_order_id")
    issues.extend(
        f"duplicate work_order_id {value}" for value in duplicate_work_orders
    )
    manifest_by_case = _index(manifests, "case_id")
    incident_by_id = _index(incidents, "incident_id")
    decision_by_case = _index(decisions, "case_id")
    action_by_case = _index(actions, "case_id")
    work_by_id = _index(work_orders, "work_order_id")
    validation_by_id = _index(validations, "validation_id")

    for case_id, manifest in manifest_by_case.items():
        service_id = str(manifest.get("service_id") or "")
        incident_id = str(manifest.get("root_incident_id") or "")
        if not service_id:
            issues.append(f"case {case_id} has no service_id")
            continue
        if not str(manifest.get("scenario_truth_domain") or ""):
            issues.append(f"case {case_id} has no immutable scenario truth domain")
        subscriber = subscribers.get(service_id)
        if subscriber is None:
            issues.append(f"case {case_id} has no subscriber row for {service_id}")
        else:
            if str(subscriber.get("delimiter_id") or "") != str(
                manifest.get("delimiter_id") or ""
            ):
                issues.append(f"case {case_id} delimiter disagrees with subscriber")
            if str(subscriber.get("technology") or "") != str(
                manifest.get("technology") or ""
            ):
                issues.append(f"case {case_id} technology disagrees with subscriber")
        incident = incident_by_id.get(incident_id)
        if incident is None:
            issues.append(f"case {case_id} has no root incident {incident_id}")
        else:
            if str(incident.get("service_id") or "") != service_id:
                issues.append(f"case {case_id} root incident service mismatch")
            if str(incident.get("case_id") or "") != str(
                manifest.get("root_case_id") or ""
            ):
                issues.append(f"case {case_id} root incident case mismatch")
        if case_id not in decision_by_case:
            issues.append(f"case {case_id} has no deterministic decision")
        if case_id not in action_by_case:
            issues.append(f"case {case_id} has no action event")

    def check_case_local(dataset: str, rows: Iterable[dict[str, Any]]) -> None:
        for row in rows:
            case_id = str(row.get("case_id") or "")
            manifest = manifest_by_case.get(case_id)
            if manifest is None:
                issues.append(f"{dataset} contains orphan case {case_id or '<missing>'}")
                continue
            expected_service = str(manifest.get("service_id") or "")
            expected_incident = str(manifest.get("root_incident_id") or "")
            service_id = row.get("service_id")
            incident_id = row.get("incident_id")
            if service_id not in {None, ""} and str(service_id) != expected_service:
                issues.append(f"{dataset} case {case_id} has a cross-case service")
            if incident_id not in {None, ""} and str(incident_id) != expected_incident:
                issues.append(f"{dataset} case {case_id} has a cross-case incident")

    check_case_local("work_orders", work_orders)
    check_case_local("mrs", mrs)
    check_case_local("validation_events", validations)
    check_case_local("resolution_events", resolutions)

    for mr in mrs:
        work_order_id = str(mr.get("work_order_id") or "")
        if work_order_id and work_order_id not in work_by_id:
            issues.append(f"MR {mr.get('mr_id')} cites missing work order {work_order_id}")
    for resolution in resolutions:
        validation_id = str(resolution.get("validation_ref") or "")
        validation = validation_by_id.get(validation_id)
        if validation is None:
            issues.append(
                f"resolution {resolution.get('resolution_id')} cites missing validation "
                f"{validation_id}"
            )
        elif str(validation.get("case_id") or "") != str(
            resolution.get("case_id") or ""
        ):
            issues.append(
                f"resolution {resolution.get('resolution_id')} cites cross-case validation"
            )
        else:
            passed, validation_issues = _validation_result(validation)
            if not passed:
                issues.append(
                    f"resolution {resolution.get('resolution_id')} cites non-passing "
                    f"validation {validation_id}: {','.join(validation_issues)}"
                )

    resolution_by_incident = {
        str(row.get("incident_id") or ""): row
        for row in resolutions
        if row.get("incident_id")
    }
    for incident_id, incident in incident_by_id.items():
        if str(incident.get("status") or "").upper() != "CLOSED":
            continue
        resolution = resolution_by_incident.get(incident_id)
        if resolution is None:
            issues.append(f"closed incident {incident_id} has no resolution record")

    if issues:
        raise DispatchProjectionIntegrityError(issues)
    return {
        "case_graph_verified": True,
        "manifest_cases_verified": len(manifest_by_case),
        "subscriber_joins_verified": len(manifest_by_case),
        "root_incident_joins_verified": len(manifest_by_case),
        "deterministic_decision_joins_verified": len(manifest_by_case),
        "action_event_joins_verified": len(manifest_by_case),
    }


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
        regions = {str(row.get("region") or "") for row in rows}
        if "" in regions:
            raise MixedRegionDelimiterError(
                f"delimiter {group_id} has a subscriber without a planning region; "
                "regenerate the run"
            )
        if len(regions) != 1:
            raise MixedRegionDelimiterError(
                f"mixed-region delimiter {group_id}: {sorted(regions)}; "
                "regenerate the run with the delimiter-region topology fix"
            )
        archetype = next(iter(regions))
        if archetype not in JITTER_KM:
            raise MixedRegionDelimiterError(
                f"delimiter {group_id} has unsupported planning region "
                f"{archetype!r}; regenerate the run"
            )
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


def _validation_result(
    validation: Mapping[str, Any] | None,
) -> tuple[bool, list[str]]:
    if validation is None:
        return False, ["validation_record_missing"]
    issues: list[str] = []
    if str(validation.get("service_test") or "").upper() != "PASS":
        issues.append("service_test_not_passed")
    if validation.get("stable") is not True:
        issues.append("telemetry_not_stable")
    checklist = validation.get("closure_checklist")
    if not isinstance(checklist, Mapping):
        issues.append("closure_checklist_missing")
    else:
        missing = sorted(REQUIRED_CLOSURE_CHECKS - set(checklist))
        failed = sorted(
            key
            for key in REQUIRED_CLOSURE_CHECKS
            if key in checklist and checklist.get(key) is not True
        )
        issues.extend(f"closure_check_missing:{key}" for key in missing)
        issues.extend(f"closure_check_failed:{key}" for key in failed)
    return not issues, issues


def _work_order_execution_economics(
    work_order: Mapping[str, Any],
) -> dict[str, Any]:
    """Read generated execution economics without importing the planning route."""

    generated_one_way = _duration_minutes(work_order, "dispatched_at", "arrived_at")
    generated_on_site = _duration_minutes(work_order, "arrived_at", "completed_at")
    distance_raw = work_order.get("road_distance_km_one_way")
    try:
        road_distance = float(distance_raw) if distance_raw not in {None, ""} else None
    except (TypeError, ValueError):
        road_distance = None
    complete = (
        generated_one_way is not None
        and generated_on_site is not None
        and road_distance is not None
        and road_distance >= 0
        and isinstance(work_order.get("ferry_used"), bool)
        and isinstance(work_order.get("overnight_used"), bool)
    )
    missing: list[str] = []
    if generated_one_way is None:
        missing.append("generated_one_way_minutes")
    if generated_on_site is None:
        missing.append("generated_on_site_minutes")
    if road_distance is None or road_distance < 0:
        missing.append("road_distance_km_one_way")
    if not isinstance(work_order.get("ferry_used"), bool):
        missing.append("ferry_used")
    if not isinstance(work_order.get("overnight_used"), bool):
        missing.append("overnight_used")
    return {
        "complete": complete,
        "missing": missing,
        "one_way_minutes": generated_one_way,
        "on_site_minutes": generated_on_site,
        "road_distance_km_one_way": road_distance,
        "ferry_used": work_order.get("ferry_used") is True,
        "overnight_used": work_order.get("overnight_used") is True,
        "source": str(work_order.get("travel_economics_source") or "unavailable"),
    }


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
    executed_truck_rolls = 0
    forecast_truck_roll_equivalents = 0
    executed_ferry_uses = 0
    forecast_ferry_equivalents = 0
    executed_overnight_uses = 0
    forecast_overnight_equivalents = 0
    generated_travel_minutes: list[int] = []
    generated_on_site_minutes: list[int] = []
    execution_economics_complete = True
    execution_economics_missing: set[str] = set()

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
        if executed:
            executed_truck_rolls = truck_rolls
        else:
            forecast_truck_roll_equivalents = truck_rolls
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
            if executed:
                economics = _work_order_execution_economics(work_order)
                execution_economics_complete &= bool(economics["complete"])
                execution_economics_missing.update(economics["missing"])
                generated_one_way = economics["one_way_minutes"]
                generated_on_site = economics["on_site_minutes"]
                if generated_one_way is not None:
                    generated_travel_minutes.append(int(generated_one_way))
                if generated_on_site is not None:
                    generated_on_site_minutes.append(int(generated_on_site))
                one_way = int(generated_one_way or 0)
                round_trip = 2 * one_way
                road_distance = economics["road_distance_km_one_way"]
                vehicle_cost = (
                    2 * float(road_distance) * RATES["vehicle_km"]
                    if road_distance is not None and road_distance >= 0
                    else 0.0
                )
                note = (
                    f"{one_way} generated min each way; "
                    f"{road_distance:.1f} generated road km each way."
                    if road_distance is not None
                    else (
                        f"{one_way} generated min each way; source road distance is "
                        "missing, so vehicle cost is excluded."
                    )
                )
                _append_line(
                    lines,
                    step="travel",
                    role=f"{crew} boots",
                    minutes=round_trip,
                    cost_usd=_labour(rate_key, round_trip) + vehicle_cost,
                    duration_provenance="generated_work_order_economics",
                    note=note,
                )
                if economics["ferry_used"]:
                    executed_ferry_uses += 1
                    _append_line(
                        lines,
                        step="ferry",
                        role=f"{crew} boots",
                        minutes=0,
                        cost_usd=RATES["ferry_round_trip"],
                        duration_provenance="generated_work_order_economics",
                    )
                on_site = generated_on_site
                on_site_source = "generated_work_order_timestamps"
                if on_site is None:
                    on_site = DURATIONS[
                        "clean_boots_on_site"
                        if crew == "clean"
                        else "dirty_boots_on_site"
                    ]
                    on_site_source = "assumed_missing_execution_duration"
                overnight_required = bool(economics["overnight_used"])
            else:
                one_way = int(route.get("modelled_one_way_minutes", 0) or 0)
                round_trip = 2 * one_way
                road_minutes = sum(
                    int(leg.get("minutes", 0))
                    for leg in route.get("legs", [])
                    if leg.get("kind") == "road"
                )
                vehicle_cost = (
                    2 * road_minutes * ROAD_KM_PER_MINUTE * RATES["vehicle_km"]
                )
                _append_line(
                    lines,
                    step="travel",
                    role=f"{crew} boots",
                    minutes=round_trip,
                    cost_usd=_labour(rate_key, round_trip) + vehicle_cost,
                    duration_provenance="modelled_dispatch_route",
                    note=f"{one_way} modelled min each way.",
                )
                if route.get("requires_ferry"):
                    forecast_ferry_equivalents += 1
                    _append_line(
                        lines,
                        step="ferry",
                        role=f"{crew} boots",
                        minutes=0,
                        cost_usd=RATES["ferry_round_trip"],
                        duration_provenance="modelled_route_condition",
                    )
                on_site = DURATIONS[
                    "clean_boots_on_site"
                    if crew == "clean"
                    else "dirty_boots_on_site"
                ]
                on_site_source = "assumed_standard_duration"
                overnight_required = not bool(route.get("same_day_feasible", True))
            _append_line(
                lines,
                step=f"{crew} boots on site",
                role=f"{crew} boots",
                minutes=on_site,
                cost_usd=_labour(rate_key, on_site),
                duration_provenance=on_site_source,
            )
            if overnight_required:
                if executed:
                    executed_overnight_uses += 1
                else:
                    forecast_overnight_equivalents += 1
                _append_line(
                    lines,
                    step="overnight",
                    role=f"{crew} boots",
                    minutes=0,
                    cost_usd=RATES["overnight_premium"],
                    duration_provenance=(
                        "generated_work_order_economics"
                        if executed
                        else "modelled_route_condition"
                    ),
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
        "executed_truck_rolls": executed_truck_rolls,
        "forecast_truck_roll_equivalents": forecast_truck_roll_equivalents,
        "executed_ferry_uses": executed_ferry_uses,
        "forecast_ferry_equivalents": forecast_ferry_equivalents,
        "executed_overnight_uses": executed_overnight_uses,
        "forecast_overnight_equivalents": forecast_overnight_equivalents,
        "generated_travel_minutes": generated_travel_minutes,
        "generated_on_site_minutes": generated_on_site_minutes,
        "execution_economics_complete": execution_economics_complete,
        "execution_economics_missing": sorted(execution_economics_missing),
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
    dirty_dispatched = [row for row in dispatched if row.get("crew_type") == "dirty"]
    executed_truck_rolls = sum(
        int(row.get("executed_truck_rolls", 0)) for row in cases
    )
    forecast_truck_rolls = sum(
        int(row.get("forecast_truck_roll_equivalents", 0)) for row in cases
    )
    household_by_root: dict[str, int] = {}
    for row in cases:
        incident_id = str(row.get("incident_id") or row.get("case_id") or "")
        household_by_root[incident_id] = max(
            household_by_root.get(incident_id, 0),
            int(row.get("households_affected", 0)),
        )
    case_weighted_households = sum(
        int(row.get("households_affected", 0)) for row in cases
    )
    executed_ferry_uses = sum(
        int(row.get("executed_ferry_uses", 0)) for row in cases
    )
    forecast_ferry_equivalents = sum(
        int(row.get("forecast_ferry_equivalents", 0)) for row in cases
    )
    executed_overnight_uses = sum(
        int(row.get("executed_overnight_uses", 0)) for row in cases
    )
    forecast_overnight_equivalents = sum(
        int(row.get("forecast_overnight_equivalents", 0)) for row in cases
    )
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
        "executed_truck_rolls": executed_truck_rolls,
        "forecast_truck_roll_equivalents": forecast_truck_rolls,
        "total_scenario_truck_roll_exposure": (
            executed_truck_rolls + forecast_truck_rolls
        ),
        # Compatibility alias for consumers predating the explicit basis split.
        "truck_rolls": executed_truck_rolls + forecast_truck_rolls,
        "field_dispatched_cases": len(dispatched),
        "work_orders": len(work_orders),
        "maintenance_requests": len(mrs),
        "case_weighted_households_affected": case_weighted_households,
        "root_incident_households_affected": sum(household_by_root.values()),
        # Compatibility alias; the grain is now stated explicitly above.
        "households_affected": case_weighted_households,
        "off_premise_interventions": sum(
            not bool(row.get("intervention_is_at_premise")) for row in cases
        ),
        "dirty_boots_case_share_pct": (
            round(100.0 * len(dirty_cases) / len(cases), 2) if cases else 0.0
        ),
        "dirty_boots_field_share_pct": (
            round(100.0 * len(dirty_dispatched) / len(dispatched), 2)
            if dispatched
            else 0.0
        ),
        "dirty_boots_cases": len(dirty_cases),
        "dirty_boots_field_cases": len(dirty_dispatched),
        "dirty_boots_case_denominator": len(cases),
        "dirty_boots_field_denominator": len(dispatched),
        # Compatibility alias for the historical all-case denominator.
        "dirty_boots_share_pct": (
            round(100.0 * len(dirty_cases) / len(cases), 2) if cases else 0.0
        ),
        "execution_economics_incomplete_cases": sum(
            row.get("cost_basis") == "generated_execution"
            and not bool(row.get("execution_economics_complete", True))
            for row in cases
        ),
        "executed_ferry_uses": executed_ferry_uses,
        "forecast_ferry_equivalents": forecast_ferry_equivalents,
        "total_scenario_ferry_exposure": (
            executed_ferry_uses + forecast_ferry_equivalents
        ),
        "executed_overnight_uses": executed_overnight_uses,
        "forecast_overnight_equivalents": forecast_overnight_equivalents,
        "total_scenario_overnight_exposure": (
            executed_overnight_uses + forecast_overnight_equivalents
        ),
        # Compatibility aliases; explicit bases are above.
        "ferry_jobs": executed_ferry_uses + forecast_ferry_equivalents,
        "overnight_jobs": (
            executed_overnight_uses + forecast_overnight_equivalents
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
    run_schema_version = str(catalog.get("run_schema_version") or "")
    if run_schema_version != RUN_SCHEMA_VERSION:
        raise DispatchProjectionIntegrityError(
            [
                "run schema is incompatible with generated-execution costing: "
                f"expected {RUN_SCHEMA_VERSION}, actual "
                f"{run_schema_version or '<missing>'}; regenerate the run"
            ]
        )
    catalog_integrity = _verify_catalog_datasets(run_path, catalog)

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

    case_graph_integrity = _validate_case_graph(
        manifests=manifests,
        subscribers=subscriber_by_service,
        incidents=incidents,
        decisions=decisions,
        actions=actions,
        work_orders=work_orders,
        mrs=mrs,
        validations=validations,
        resolutions=resolutions,
    )

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
        subscriber = subscriber_by_service[service_id]
        group_id = str(subscriber.get("delimiter_id") or service_id)
        site = site_assignments.get(group_id)
        if site is None:
            raise DispatchProjectionIntegrityError(
                [f"case {case_id} has no planning-site assignment for {group_id}"]
            )

        scenario = str(manifest.get("scenario", "unknown"))
        decision = decision_by_case.get(case_id, {})
        policy = SCENARIO_POLICIES.get(scenario, {})
        recommended_domain = str(
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
        validation_passed, validation_issues = _validation_result(validation)
        scenario_truth_domain = str(
            manifest.get("scenario_truth_domain")
            or policy.get("domain")
            or "unknown"
        )
        actual_domain = str(
            (resolution or {}).get("fault_domain")
            if resolution is not None and validation_passed
            else scenario_truth_domain
        )
        actual_domain_source = (
            "validated_resolution"
            if resolution is not None and validation_passed
            else "immutable_scenario_truth"
        )
        technology = str(
            subscriber.get("technology")
            or manifest.get("technology")
            or "HFC"
        )
        family = _technology_family(technology)
        coords = _coordinates(subscriber, site, actual_domain)
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
            domain=actual_domain,
            family=family,
            route=route,
            work_orders=case_work_orders,
            human_required=bool(human.get("required")),
            validated=validation_passed,
            closed=str(incident.get("status", "")).upper() == "CLOSED",
        )
        domain_mismatch = recommended_domain != actual_domain
        missed = (
            false_negative_cost(
                site.site_id,
                actual_domain,
                destination=(
                    coords["intervention_lat"],
                    coords["intervention_lon"],
                ),
            )
            if domain_mismatch
            else None
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
        misdispatch_premium = round(missed.cost_usd, 2) if missed else 0.0
        misdispatch_cost = round(total_cost + misdispatch_premium, 2)
        if cost["basis"] == "generated_execution":
            cost_provenance = (
                "Demo-generated action and work-order timing/economics with assumed "
                "labour, vehicle, ferry, overnight and parts rates. The planning "
                "route is comparison-only and does not contribute to executed cost."
            )
            if not cost["execution_economics_complete"]:
                cost_provenance += (
                    " Missing source execution fields are excluded or explicitly "
                    "filled with a labelled duration assumption."
                )
        else:
            cost_provenance = (
                "Governed forecast using the deterministic action, modelled planning "
                "route and assumed economic rates."
            )
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
                    "Generated delimiter and its single generated region mapped "
                    "deterministically to the planning geography."
                ),
                "location_warning": (
                    "No technology-compatible planning site exists in the generated "
                    "region; a fallback planning site was used."
                    if region != site.archetype
                    else ""
                ),
                "actual_domain": actual_domain,
                "actual_domain_source": actual_domain_source,
                # Compatibility alias; unlike earlier releases, it is independent
                # of the deterministic recommendation.
                "true_domain": actual_domain,
                "recommended_domain": recommended_domain,
                "domain_match": not domain_mismatch,
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
                "requires_ferry": (
                    int(cost["executed_ferry_uses"]) > 0
                    if cost["basis"] == "generated_execution"
                    else bool(route.get("requires_ferry"))
                ),
                "same_day_feasible": (
                    int(cost["executed_overnight_uses"]) == 0
                    if cost["basis"] == "generated_execution"
                    else bool(route.get("same_day_feasible", True))
                ),
                "modelled_requires_ferry": bool(route.get("requires_ferry")),
                "modelled_same_day_feasible": bool(
                    route.get("same_day_feasible", True)
                ),
                "route": route,
                **coords,
                "households_affected": blast_radius(actual_domain, site.site_id, family),
                "cost_basis": cost["basis"],
                "cost_provenance": cost_provenance,
                "total_minutes": int(cost["total_minutes"]),
                "total_cost_usd": total_cost,
                "truck_rolls": int(cost["truck_rolls"]),
                "executed_truck_rolls": int(cost["executed_truck_rolls"]),
                "forecast_truck_roll_equivalents": int(
                    cost["forecast_truck_roll_equivalents"]
                ),
                "executed_ferry_uses": int(cost["executed_ferry_uses"]),
                "forecast_ferry_equivalents": int(
                    cost["forecast_ferry_equivalents"]
                ),
                "executed_overnight_uses": int(
                    cost["executed_overnight_uses"]
                ),
                "forecast_overnight_equivalents": int(
                    cost["forecast_overnight_equivalents"]
                ),
                "misdispatch_cost_usd": misdispatch_cost,
                "misdispatch_premium_usd": misdispatch_premium,
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
                "execution_economics_complete": cost[
                    "execution_economics_complete"
                ],
                "execution_economics_missing": cost[
                    "execution_economics_missing"
                ],
                "validated": validation_passed,
                "validation_issues": validation_issues,
                "validation_id": (validation or {}).get("validation_id"),
                "resolution_id": (resolution or {}).get("resolution_id"),
                "production_write": False,
            }
        )

    summary = _summary(cases)
    projected_work_order_ids = {
        str(work_order_id)
        for case in cases
        for work_order_id in case.get("work_order_ids", [])
        if work_order_id
    }
    source_work_order_ids = {
        str(row.get("work_order_id"))
        for row in work_orders
        if row.get("work_order_id")
    }
    projected_mr_ids = {
        str(mr_id)
        for case in cases
        for mr_id in case.get("mr_ids", [])
        if mr_id
    }
    source_mr_ids = {str(row.get("mr_id")) for row in mrs if row.get("mr_id")}
    reconciliation = {
        "case_attempts_equal_manifest_rows": len(cases) == len(manifests),
        "work_order_ids_projected": len(projected_work_order_ids),
        "source_work_order_ids": len(source_work_order_ids),
        "missing_work_order_ids": sorted(
            source_work_order_ids - projected_work_order_ids
        ),
        "orphaned_work_order_ids": sorted(
            projected_work_order_ids - source_work_order_ids
        ),
        "duplicate_work_order_ids": _duplicate_values(work_orders, "work_order_id"),
        "mr_ids_projected": len(projected_mr_ids),
        "source_mr_ids": len(source_mr_ids),
        "missing_mr_ids": sorted(source_mr_ids - projected_mr_ids),
        "orphaned_mr_ids": sorted(projected_mr_ids - source_mr_ids),
        "mr_revision_ids": _duplicate_values(mrs, "mr_id"),
        "passing_validations": sum(bool(case.get("validated")) for case in cases),
        "failing_or_incomplete_validations": sum(
            not bool(case.get("validated")) and case.get("validation_id") is not None
            for case in cases
        ),
    }
    reconciliation["all_identifier_sets_match"] = not any(
        reconciliation[key]
        for key in (
            "missing_work_order_ids",
            "orphaned_work_order_ids",
            "duplicate_work_order_ids",
            "missing_mr_ids",
            "orphaned_mr_ids",
        )
    )
    return {
        "schema_version": DISPATCH_PROJECTION_SCHEMA_VERSION,
        "run_id": catalog.get("run_id", run_path.name),
        "release": catalog.get("release"),
        "run_schema_version": catalog.get("run_schema_version"),
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
            "completeness": (
                "catalog hashes, row counts and mandatory case-graph joins verified; "
                "complete canonical run datasets; not paginated"
            ),
            "run_schema_version": catalog.get("run_schema_version"),
            "production_writes": False,
        },
        "summary": summary,
        "cases": cases,
        "data_integrity": {
            **catalog_integrity,
            **case_graph_integrity,
            "passed": True,
        },
        "provenance": {
            "run_derived": dispatch_cost_contract()["run_derived_inputs"],
            "modelled": dispatch_cost_contract()["modelled_inputs"],
            "assumed": dispatch_cost_contract()["assumed_inputs"],
            "hub_locations_assumed": all(base.assumed for base in DISPATCH_BASES),
        },
        "reconciliation": reconciliation,
    }
