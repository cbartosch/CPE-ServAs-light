"""Canonical measurement contract shared by every assurance dashboard.

The application has three legitimate evidence modes:

* an immutable Digital Twin run;
* the live operational workflow repository; and
* the legacy seeded planning model.

Those modes do not have to produce equal values. They do have to use the same
entity names, grains, denominators, status partition and provenance vocabulary so
that a reader can explain every difference. This module is deliberately free of
Streamlit, FastAPI and storage imports; adapters project their native records into
this contract.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

MEASUREMENT_SCHEMA_VERSION = "1.0"
STATUS_PARTITION_KEYS = ("open", "waiting", "closed", "escalated", "quarantined")
PROVENANCE_KINDS = (
    "observed",
    "run_derived",
    "modelled",
    "assumed",
    "benchmark",
    "unavailable",
)

ENTITY_GRAINS: dict[str, str] = {
    "service_id": "One subscribed broadband service in the measurement population.",
    "device_id": "One modem, gateway or ONT.",
    "predictive_ticket_id": "One canonical predictive risk record.",
    "contact_id": "One customer interaction; this is not a root incident.",
    "care_ticket_id": "One Care workflow record, normally contact-grain in the demo.",
    "incident_id": "One durable root incident used for executive and status KPIs.",
    "case_id": "One diagnosis/action attempt linked to a root incident.",
    "approval_id": "One human-decision object; approvals are not incident states.",
    "work_order_id": "One field-work execution record.",
    "mr_id": "One maintenance/plant handoff record.",
}

METRIC_DEFINITIONS: dict[str, dict[str, str]] = {
    "footprint_services": {
        "label": "Services in footprint",
        "grain": "service_id",
        "formula": "Distinct eligible service_id values.",
    },
    "scanned_devices": {
        "label": "Devices scanned",
        "grain": "device_id",
        "formula": "Distinct devices with a completed canonical predictive pull.",
    },
    "scan_coverage_pct": {
        "label": "Scan coverage",
        "grain": "device_id",
        "formula": "Devices scanned divided by eligible services/devices.",
    },
    "healthy_scanned_services": {
        "label": "Healthy scanned services",
        "grain": "service_id",
        "formula": "Scanned services without a canonical current risk.",
    },
    "at_risk_services": {
        "label": "At-risk services",
        "grain": "service_id",
        "formula": "Distinct services with one or more canonical predictive risks.",
    },
    "forecast_risk_services": {
        "label": "Forecast-risk services",
        "grain": "service_id",
        "formula": "At-risk services forecast to breach but not currently degraded.",
    },
    "degraded_services": {
        "label": "Currently degraded services",
        "grain": "service_id",
        "formula": "Distinct services with a current predictive threshold breach.",
    },
    "care_contacts": {
        "label": "Care contacts",
        "grain": "contact_id",
        "formula": "Distinct customer contacts in the selected window.",
    },
    "predictively_matched_contacts": {
        "label": "Predictively matched contacts",
        "grain": "contact_id",
        "formula": "Care contacts preceded by canonical predictive evidence.",
    },
    "predictive_match_rate_pct": {
        "label": "Predictive match rate",
        "grain": "contact_id",
        "formula": "Predictively matched contacts divided by all Care contacts.",
    },
    "canonical_root_attachments": {
        "label": "Contacts attached to a canonical root incident",
        "grain": "contact_id",
        "formula": "Care contacts carrying a durable incident_id reference.",
    },
    "actual_duplicate_attempts_intercepted": {
        "label": "Duplicate creation attempts intercepted",
        "grain": "contact_id",
        "formula": "Audited duplicate-creation attempts actively rejected by policy.",
    },
    "root_incidents": {
        "label": "Root incidents",
        "grain": "incident_id",
        "formula": "Distinct durable incident_id values.",
    },
    "closed_root_incidents": {
        "label": "Closed root incidents",
        "grain": "incident_id",
        "formula": "Root incidents closed after objective validation.",
    },
    "waiting_root_incidents": {
        "label": "Waiting root incidents",
        "grain": "incident_id",
        "formula": "Root incidents currently waiting for a human decision.",
    },
    "case_attempts": {
        "label": "Case attempts",
        "grain": "case_id",
        "formula": "Distinct diagnosis/action attempts; may exceed root incidents.",
    },
    "pending_approvals": {
        "label": "Pending approvals",
        "grain": "approval_id",
        "formula": "Distinct pending human-decision objects, shown outside status totals.",
    },
    "field_dispatched_root_incidents": {
        "label": "Field-dispatched root incidents",
        "grain": "incident_id",
        "formula": "Distinct root incidents with one or more field work orders.",
    },
    "work_orders": {
        "label": "Work orders",
        "grain": "work_order_id",
        "formula": "Distinct field-work records.",
    },
    "maintenance_requests": {
        "label": "Maintenance requests",
        "grain": "mr_id",
        "formula": "Distinct plant/MR handoff records.",
    },
}


def measurement_contract() -> dict[str, Any]:
    """Return the machine-readable semantic contract used by both APIs."""

    return {
        "schema_version": MEASUREMENT_SCHEMA_VERSION,
        "primary_executive_grain": "incident_id",
        "entity_grains": dict(ENTITY_GRAINS),
        "metrics": {key: dict(value) for key, value in METRIC_DEFINITIONS.items()},
        "status_partition": list(STATUS_PARTITION_KEYS),
        "provenance_kinds": list(PROVENANCE_KINDS),
        "invariants": [
            "forecast_risk_services + degraded_services = at_risk_services",
            "predictively_matched_contacts + unmatched_contacts = care_contacts",
            "open + waiting + closed + escalated + quarantined = root_incidents",
            "case_attempts >= root_incidents",
            "returned_rows <= filtered_total <= total_rows",
            "headline metrics are not calculated from paginated display rows",
            "planning-model values are not presented as active-run observations",
        ],
    }


def metric(
    key: str,
    value: int | float | None,
    *,
    provenance: str,
    numerator: int | float | None = None,
    denominator: int | float | None = None,
    available: bool = True,
    note: str = "",
) -> dict[str, Any]:
    """Create one metric value with its grain, formula and denominator."""

    definition = METRIC_DEFINITIONS[key]
    return {
        "key": key,
        "label": definition["label"],
        "grain": definition["grain"],
        "formula": definition["formula"],
        "value": value if available else None,
        "numerator": numerator,
        "denominator": denominator,
        "provenance": provenance if available else "unavailable",
        "available": available,
        "note": note,
    }


def unavailable_metric(key: str, reason: str) -> dict[str, Any]:
    """Represent a metric that the source mode cannot observe."""

    return metric(key, None, provenance="unavailable", available=False, note=reason)


def _value(record: Any, key: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        value = record.get(key, default)
    else:
        value = getattr(record, key, default)
    return getattr(value, "value", value)


def _iso(value: datetime | str | None) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat()
    if value:
        return str(value)
    return datetime.now(UTC).isoformat()


def status_partition_total(partition: Mapping[str, int]) -> int:
    return sum(int(partition.get(key, 0)) for key in STATUS_PARTITION_KEYS)


def _root_id(record: Any) -> str:
    """Resolve an operational case to its durable common-cause root."""

    return str(
        _value(record, "parent_incident_id")
        or _value(record, "incident_id")
        or ""
    )


def _root_status(records: list[Any]) -> str:
    """Collapse related case states into one mutually exclusive root state."""

    states = {str(_value(item, "status", "open")).lower() for item in records}
    for state in ("quarantined", "escalated", "waiting", "open"):
        if state in states:
            return state
    return "closed" if states == {"closed"} else "open"


def _nested_ids(
    records: Iterable[Any],
    collection: str,
    keys: tuple[str, ...],
) -> set[str]:
    identifiers: set[str] = set()
    for record in records:
        for item in _value(record, collection, []) or []:
            for key in keys:
                value = _value(item, key)
                if value not in {None, ""}:
                    identifiers.add(str(value))
                    break
    return identifiers


def build_operations_projection(
    incidents: Iterable[Any],
    approvals: Iterable[Any],
    *,
    as_of: datetime | str | None = None,
) -> dict[str, Any]:
    """Project the live workflow repository into the shared measurement schema."""

    incident_by_id = {
        str(_value(item, "incident_id")): item
        for item in incidents
        if _value(item, "incident_id")
    }
    approval_by_id = {
        str(_value(item, "approval_id")): item
        for item in approvals
        if _value(item, "approval_id")
    }

    root_groups: dict[str, list[Any]] = {}
    for item in incident_by_id.values():
        root_id = _root_id(item)
        if root_id:
            root_groups.setdefault(root_id, []).append(item)

    partition = {key: 0 for key in STATUS_PARTITION_KEYS}
    root_statuses = {
        root_id: _root_status(records)
        for root_id, records in root_groups.items()
    }
    for state in root_statuses.values():
        partition[state] += 1

    root_incidents = len(root_groups)
    case_attempts = len(incident_by_id)
    pending_approvals = sum(
        str(_value(item, "status", "")).lower() == "pending"
        for item in approval_by_id.values()
    )
    remote_attempts = sum(
        int(_value(item, "remote_attempts", 0) or 0)
        for item in incident_by_id.values()
    )
    field_visits = sum(
        int(_value(item, "field_visits", 0) or 0)
        for item in incident_by_id.values()
    )
    mr_attempts = sum(
        int(_value(item, "mr_attempts", 0) or 0)
        for item in incident_by_id.values()
    )
    returned_to_rca = sum(
        int(_value(item, "diagnostic_cycles", 0) or 0) > 1
        for item in incident_by_id.values()
    )

    work_order_ids = _nested_ids(
        incident_by_id.values(),
        "work_orders",
        ("work_order_id", "action_id"),
    )
    mr_ids = _nested_ids(
        incident_by_id.values(),
        "mr_records",
        ("mr_id", "action_id"),
    )
    dispatched_roots = {
        _root_id(item)
        for item in incident_by_id.values()
        if int(_value(item, "field_visits", 0) or 0) > 0
        or bool(_value(item, "work_orders", []))
    }
    dispatched_roots.discard("")

    latest = as_of
    if latest is None and incident_by_id:
        latest = max(
            (
                _iso(_value(item, "updated_at"))
                for item in incident_by_id.values()
            ),
            default=None,
        )

    metrics = {
        key: unavailable_metric(
            key,
            "The live workflow repository does not currently expose this population.",
        )
        for key in (
            "footprint_services",
            "scanned_devices",
            "scan_coverage_pct",
            "healthy_scanned_services",
            "at_risk_services",
            "forecast_risk_services",
            "degraded_services",
            "care_contacts",
            "predictively_matched_contacts",
            "predictive_match_rate_pct",
            "canonical_root_attachments",
            "actual_duplicate_attempts_intercepted",
        )
    }
    metrics.update(
        {
            "root_incidents": metric(
                "root_incidents", root_incidents, provenance="observed"
            ),
            "closed_root_incidents": metric(
                "closed_root_incidents", partition["closed"], provenance="observed"
            ),
            "waiting_root_incidents": metric(
                "waiting_root_incidents", partition["waiting"], provenance="observed"
            ),
            "case_attempts": metric(
                "case_attempts",
                case_attempts,
                provenance="observed",
                note=(
                    "Each IncidentState is a case attempt; parent_incident_id collapses "
                    "common-cause children into one durable root incident."
                ),
            ),
            "pending_approvals": metric(
                "pending_approvals", pending_approvals, provenance="observed"
            ),
            "field_dispatched_root_incidents": metric(
                "field_dispatched_root_incidents",
                len(dispatched_roots),
                provenance="observed",
            ),
            "work_orders": metric(
                "work_orders",
                len(work_order_ids),
                provenance="observed",
                note="Distinct work-order IDs projected from incident state.",
            ),
            "maintenance_requests": metric(
                "maintenance_requests",
                len(mr_ids),
                provenance="observed",
                note="Distinct MR IDs projected from incident state.",
            ),
        }
    )

    checks = {
        "status_partition_equals_root_incidents": (
            status_partition_total(partition) == root_incidents
        ),
        "case_attempts_cover_root_incidents": case_attempts >= root_incidents,
        "pending_approvals_outside_status_partition": True,
        "headlines_not_paginated": True,
    }
    return {
        "schema_version": MEASUREMENT_SCHEMA_VERSION,
        "measurement_context": {
            "mode": "live_operations",
            "source": "workflow_repository",
            "run_id": None,
            "linked_to_active_run": False,
            "as_of": _iso(latest),
            "window": "Since demo reset",
            "primary_grain": "incident_id",
            "completeness": "Complete repository read; not paginated",
            "planning_model": False,
        },
        "metrics": metrics,
        "status_partition": partition,
        "workload": {
            "pending_approvals": pending_approvals,
            "remote_attempts": remote_attempts,
            "field_visits": field_visits,
            "mr_attempts": mr_attempts,
            "returned_to_rca": returned_to_rca,
            "case_attempts": case_attempts,
        },
        "technology_counts": {
            "HFC": sum(
                str(_value(item, "technology", "")) == "HFC"
                for item in incident_by_id.values()
            ),
            "PON": sum(
                str(_value(item, "technology", "")) == "PON"
                for item in incident_by_id.values()
            ),
        },
        "data_completeness": {
            "headline_metrics_from_paginated_rows": False,
            "truncated": False,
            "records_read": case_attempts,
        },
        "reconciliation": {
            "passed": all(checks.values()),
            "checks": checks,
        },
        "provenance": {
            "mode": "observed",
            "note": (
                "Live operational workflow records. They use the shared metric contract "
                "but are not implicitly equated with an active Digital Twin run."
            ),
        },
    }
