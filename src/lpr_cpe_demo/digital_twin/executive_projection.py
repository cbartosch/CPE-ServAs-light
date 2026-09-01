from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from lpr_cpe_demo.measurement import (
    MEASUREMENT_SCHEMA_VERSION,
    metric,
    status_partition_total,
    unavailable_metric,
)

from .install_assurance import latest_install_assurance_projection
from .storage import get_active_run, iter_jsonl_gz, safe_run_path


def _load_rows(run_path: Path, dataset: str) -> list[dict[str, Any]]:
    path = run_path / f"{dataset}.jsonl.gz"
    if not path.exists():
        return []
    return list(iter_jsonl_gz(path))


def _index(rows: Iterable[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {str(row[key]): row for row in rows if row.get(key) is not None}


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


def _subscriber_index(
    run_path: Path,
    service_ids: set[str],
) -> dict[str, dict[str, Any]]:
    if not service_ids:
        return {}
    path = run_path / "subscriber_master.jsonl.gz"
    if not path.exists():
        return {}
    subscribers: dict[str, dict[str, Any]] = {}
    for row in iter_jsonl_gz(path):
        service_id = str(row.get("service_id", ""))
        if service_id in service_ids:
            subscribers[service_id] = row
            if len(subscribers) == len(service_ids):
                break
    return subscribers


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _ids(rows: Iterable[dict[str, Any]], key: str) -> set[str]:
    return {str(row[key]) for row in rows if row.get(key) not in {None, ""}}


def _catalog_row_count(catalog: dict[str, Any], dataset: str) -> int:
    for entry in catalog.get("datasets", []):
        if entry.get("dataset") == dataset:
            return int(entry.get("row_count", 0) or 0)
    return 0


def _latest_timestamp(*row_sets: Iterable[dict[str, Any]]) -> str:
    candidates: list[str] = []
    fields = (
        "event_timestamp",
        "collection_timestamp",
        "opened_at",
        "closed_at",
        "resolved_at",
        "decided_at",
        "validated_at",
    )
    for rows in row_sets:
        for row in rows:
            for field in fields:
                value = row.get(field)
                if value:
                    candidates.append(str(value))
    return max(candidates, default="")


def _metric_projection(
    catalog: dict[str, Any],
    *,
    predictive_rows: list[dict[str, Any]],
    pull_rows: list[dict[str, Any]],
    care_rows: list[dict[str, Any]],
    incident_rows: list[dict[str, Any]],
    manifest_rows: list[dict[str, Any]],
    human_rows: list[dict[str, Any]],
    work_order_rows: list[dict[str, Any]],
    mr_rows: list[dict[str, Any]],
    action_rows: list[dict[str, Any]],
    validation_rows: list[dict[str, Any]],
    resolution_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    footprint_services = int(
        catalog.get("operational_scale", {}).get("homes")
        or catalog.get("config", {}).get("homes")
        or _catalog_row_count(catalog, "subscriber_master")
        or 0
    )
    scanned_device_ids = _ids(pull_rows, "device_id") or _ids(pull_rows, "modem_id")
    scanned_service_ids = _ids(pull_rows, "service_id")
    if not scanned_service_ids and scanned_device_ids:
        scanned_service_ids = set(scanned_device_ids)

    degraded_services = {
        str(row["service_id"])
        for row in predictive_rows
        if row.get("service_id") and row.get("ticket_class") == "proactive"
    }
    forecast_services = {
        str(row["service_id"])
        for row in predictive_rows
        if row.get("service_id") and row.get("ticket_class") == "forecast"
    } - degraded_services
    at_risk_services = degraded_services | forecast_services
    healthy_scanned_services = scanned_service_ids - at_risk_services

    contact_ids = _ids(care_rows, "contact_id") or _ids(care_rows, "care_ticket_id")
    matched_contact_ids = {
        str(row.get("contact_id") or row.get("care_ticket_id"))
        for row in care_rows
        if row.get("predictive_match")
    }
    unmatched_contact_ids = contact_ids - matched_contact_ids
    canonical_root_attachments = {
        str(row.get("contact_id") or row.get("care_ticket_id"))
        for row in care_rows
        if row.get("incident_id")
    }
    duplicate_attempts = {
        str(row.get("contact_id") or row.get("care_ticket_id"))
        for row in care_rows
        if row.get("duplicate_creation_attempt_intercepted") is True
    }

    incident_ids = _ids(incident_rows, "incident_id")
    closed_incident_ids = {
        str(row["incident_id"])
        for row in incident_rows
        if row.get("incident_id") and str(row.get("status")).upper() == "CLOSED"
    }
    open_incident_ids = incident_ids - closed_incident_ids
    root_by_case = {
        str(row["case_id"]): str(row["root_incident_id"])
        for row in manifest_rows
        if row.get("case_id") and row.get("root_incident_id")
    }
    pending_case_ids = {
        str(row["case_id"])
        for row in human_rows
        if row.get("case_id") and str(row.get("status")).upper() == "PENDING"
    }
    waiting_incident_ids = {
        root_by_case[case_id]
        for case_id in pending_case_ids
        if case_id in root_by_case and root_by_case[case_id] in open_incident_ids
    }
    plain_open_incident_ids = open_incident_ids - waiting_incident_ids

    work_order_case_ids = _ids(work_order_rows, "case_id")
    dispatched_incident_ids = {
        root_by_case[case_id]
        for case_id in work_order_case_ids
        if case_id in root_by_case
    }
    work_order_ids = _ids(work_order_rows, "work_order_id")
    mr_ids = _ids(mr_rows, "mr_id")
    case_attempt_ids = _ids(manifest_rows, "case_id")

    scanned_devices = len(scanned_device_ids or scanned_service_ids)
    scan_coverage = (
        100.0 * scanned_devices / footprint_services if footprint_services else 0.0
    )
    care_contacts = len(contact_ids)
    predictive_match_rate = (
        100.0 * len(matched_contact_ids) / care_contacts if care_contacts else 0.0
    )

    partition = {
        "open": len(plain_open_incident_ids),
        "waiting": len(waiting_incident_ids),
        "closed": len(closed_incident_ids),
        "escalated": 0,
        "quarantined": 0,
    }
    metrics = {
        "footprint_services": metric(
            "footprint_services", footprint_services, provenance="run_derived"
        ),
        "scanned_devices": metric(
            "scanned_devices", scanned_devices, provenance="run_derived"
        ),
        "scan_coverage_pct": metric(
            "scan_coverage_pct",
            round(scan_coverage, 2),
            provenance="run_derived",
            numerator=scanned_devices,
            denominator=footprint_services,
        ),
        "healthy_scanned_services": metric(
            "healthy_scanned_services",
            len(healthy_scanned_services),
            provenance="run_derived",
        ),
        "at_risk_services": metric(
            "at_risk_services", len(at_risk_services), provenance="run_derived"
        ),
        "forecast_risk_services": metric(
            "forecast_risk_services",
            len(forecast_services),
            provenance="run_derived",
        ),
        "degraded_services": metric(
            "degraded_services",
            len(degraded_services),
            provenance="run_derived",
        ),
        "care_contacts": metric(
            "care_contacts", care_contacts, provenance="run_derived"
        ),
        "predictively_matched_contacts": metric(
            "predictively_matched_contacts",
            len(matched_contact_ids),
            provenance="run_derived",
        ),
        "predictive_match_rate_pct": metric(
            "predictive_match_rate_pct",
            round(predictive_match_rate, 2),
            provenance="run_derived",
            numerator=len(matched_contact_ids),
            denominator=care_contacts,
        ),
        "canonical_root_attachments": metric(
            "canonical_root_attachments",
            len(canonical_root_attachments),
            provenance="run_derived",
        ),
        "actual_duplicate_attempts_intercepted": unavailable_metric(
            "actual_duplicate_attempts_intercepted",
            (
                "The synthetic generator asserts canonical attachment but does not emit "
                "an audited duplicate-creation attempt."
            ),
        ),
        "root_incidents": metric(
            "root_incidents", len(incident_ids), provenance="run_derived"
        ),
        "closed_root_incidents": metric(
            "closed_root_incidents",
            len(closed_incident_ids),
            provenance="run_derived",
        ),
        "waiting_root_incidents": metric(
            "waiting_root_incidents",
            len(waiting_incident_ids),
            provenance="run_derived",
        ),
        "case_attempts": metric(
            "case_attempts", len(case_attempt_ids), provenance="run_derived"
        ),
        "pending_approvals": metric(
            "pending_approvals", len(pending_case_ids), provenance="run_derived"
        ),
        "field_dispatched_root_incidents": metric(
            "field_dispatched_root_incidents",
            len(dispatched_incident_ids),
            provenance="run_derived",
        ),
        "work_orders": metric(
            "work_orders", len(work_order_ids), provenance="run_derived"
        ),
        "maintenance_requests": metric(
            "maintenance_requests", len(mr_ids), provenance="run_derived"
        ),
    }

    checks = {
        "risk_partition": (
            len(forecast_services) + len(degraded_services) == len(at_risk_services)
        ),
        "care_partition": (
            len(matched_contact_ids) + len(unmatched_contact_ids) == care_contacts
        ),
        "status_partition": status_partition_total(partition) == len(incident_ids),
        "case_attempts_cover_root_incidents": len(case_attempt_ids) >= len(incident_ids),
        "scan_within_footprint": scanned_devices <= footprint_services,
        "attachments_within_contacts": len(canonical_root_attachments) <= care_contacts,
        "headlines_not_paginated": True,
    }
    latest = _latest_timestamp(
        predictive_rows,
        care_rows,
        incident_rows,
        human_rows,
        action_rows,
        validation_rows,
        resolution_rows,
    )
    return {
        "schema_version": MEASUREMENT_SCHEMA_VERSION,
        "measurement_context": {
            "mode": "digital_twin_run",
            "source": "canonical_run_datasets",
            "run_id": catalog.get("run_id"),
            "linked_to_active_run": True,
            "as_of": latest or str(catalog.get("config", {}).get("run_date", "")),
            "window": "Immutable run snapshot; repeat governance uses 30 days",
            "primary_grain": "incident_id",
            "completeness": "Complete canonical datasets; not paginated",
            "planning_model": False,
            "footprint_services": footprint_services,
            "scanned_devices": scanned_devices,
            "scan_coverage_pct": round(scan_coverage, 2),
        },
        "metrics": metrics,
        "status_partition": partition,
        "predictive_funnel": {
            "eligible_services": footprint_services,
            "scanned_devices": scanned_devices,
            "healthy_scanned_services": len(healthy_scanned_services),
            "forecast_risk_services": len(forecast_services),
            "degraded_services": len(degraded_services),
            "at_risk_services": len(at_risk_services),
        },
        "care_funnel": {
            "contacts": care_contacts,
            "predictively_matched": len(matched_contact_ids),
            "reactive_only": len(unmatched_contact_ids),
            "canonical_root_attachments": len(canonical_root_attachments),
            "actual_duplicate_attempts_intercepted": (
                len(duplicate_attempts) if duplicate_attempts else None
            ),
        },
        "operational_funnel": {
            "case_attempts": len(case_attempt_ids),
            "root_incidents": len(incident_ids),
            "field_dispatched_root_incidents": len(dispatched_incident_ids),
            "validated_events": len(validation_rows),
            "closed_root_incidents": len(closed_incident_ids),
        },
        "workload": {
            "pending_approvals": len(pending_case_ids),
            "work_orders": len(work_order_ids),
            "maintenance_requests": len(mr_ids),
        },
        "data_completeness": {
            "headline_metrics_from_paginated_rows": False,
            "truncated": False,
            "dataset_counts": {
                entry.get("dataset"): int(entry.get("row_count", 0) or 0)
                for entry in catalog.get("datasets", [])
            },
        },
        "reconciliation": {
            "passed": all(checks.values()),
            "checks": checks,
        },
        "provenance": {
            "mode": "run_derived",
            "note": (
                "All headline values are aggregated from complete immutable run datasets. "
                "Display tables may be paginated without changing these totals."
            ),
        },
    }


def build_executive_projection(
    root_or_run_path: Path,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Join run evidence and publish the canonical executive measurement projection."""

    run_path = _resolve_run_path(root_or_run_path, run_id)
    catalog_path = run_path / "catalog.json"
    if not catalog_path.is_file():
        raise FileNotFoundError("run catalog not found")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

    predictive_rows = _load_rows(run_path, "predictive_tickets")
    pull_rows = _load_rows(run_path, "predictive_modem_pulls")
    care_rows = _load_rows(run_path, "care_tickets")
    incident_rows = _load_rows(run_path, "incidents")
    review_rows = _load_rows(run_path, "care_ticket_reviews")
    manifest_rows = _load_rows(run_path, "scenario_manifests")
    deterministic_rows = _load_rows(run_path, "deterministic_decisions")
    agent_rows = _load_rows(run_path, "agent_decisions")
    reconciliation_rows = _load_rows(run_path, "reconciliation_records")
    human_rows = _load_rows(run_path, "human_decisions")
    action_rows = _load_rows(run_path, "action_events")
    work_order_rows = _load_rows(run_path, "work_orders")
    mr_rows = _load_rows(run_path, "mrs")
    validation_rows = _load_rows(run_path, "validation_events")
    resolution_rows = _load_rows(run_path, "resolution_events")

    predictive = _index(predictive_rows, "ticket_id")
    incidents = _index(incident_rows, "incident_id")
    reviews = _index(review_rows, "care_ticket_id")
    manifests = _index(manifest_rows, "case_id")
    deterministic = _index(deterministic_rows, "case_id")
    agents = _index(agent_rows, "case_id")
    reconciliations = _index(reconciliation_rows, "case_id")
    humans = _index(human_rows, "case_id")
    actions = _index(action_rows, "case_id")
    validations = _index(validation_rows, "case_id")
    resolutions = _index(resolution_rows, "case_id")

    service_ids = _ids(care_rows, "service_id")
    subscribers = _subscriber_index(run_path, service_ids)

    stories: list[dict[str, Any]] = []
    for care in sorted(
        care_rows,
        key=lambda row: (
            str(row.get("opened_at", "")),
            str(row.get("care_ticket_id", "")),
        ),
    ):
        care_ticket_id = str(care.get("care_ticket_id", ""))
        case_id = str(care.get("case_id", ""))
        incident_id = str(care.get("incident_id", ""))
        service_id = str(care.get("service_id", ""))
        predictive_ticket_id = care.get("predictive_ticket_id")

        predictive_ticket = (
            predictive.get(str(predictive_ticket_id))
            if predictive_ticket_id is not None
            else None
        )
        incident = incidents.get(incident_id)
        review = reviews.get(care_ticket_id)
        manifest = manifests.get(case_id)
        deterministic_decision = deterministic.get(case_id)
        agent_decision = agents.get(case_id)
        reconciliation = reconciliations.get(case_id)
        human_decision = humans.get(case_id)
        action = actions.get(case_id)

        governance = {
            **(review or {}),
            "care_ticket_id": care_ticket_id,
            "case_id": case_id,
            "incident_id": incident_id,
            "service_id": service_id,
            "predictive_ticket_id": predictive_ticket_id,
            "review": review,
            "care_review": review,
            "deterministic": deterministic_decision,
            "deterministic_decision": deterministic_decision,
            "agent": agent_decision,
            "agent_decision": agent_decision,
            "reconciliation": reconciliation,
            "human_decision": human_decision,
            "action": action,
            "deterministic_domain": _coalesce(
                (deterministic_decision or {}).get("recommended_domain"),
                (review or {}).get("deterministic_domain"),
            ),
            "deterministic_action": _coalesce(
                (deterministic_decision or {}).get("best_action"),
                (review or {}).get("deterministic_action"),
            ),
            "agent_source": _coalesce(
                (agent_decision or {}).get("source"),
                (review or {}).get("agent_source"),
            ),
            "agent_action": _coalesce(
                (agent_decision or {}).get("best_action"),
                (review or {}).get("agent_action"),
            ),
            "human_review_required": _coalesce(
                (reconciliation or {}).get("human_review_required"),
                (review or {}).get("reconciled_human_review_required"),
            ),
            "human_status": (human_decision or {}).get("status"),
            "action_status": (action or {}).get("status"),
            "production_write": (action or {}).get("production_write"),
            "review_status": (review or {}).get("review_status"),
            "reconciliation_reason": _coalesce(
                (reconciliation or {}).get("reason"),
                (review or {}).get("reconciliation_reason"),
            ),
        }

        stories.append(
            {
                **care,
                "story_id": care_ticket_id,
                "care_ticket_id": care_ticket_id,
                "case_id": case_id,
                "root_case_id": care.get("root_case_id"),
                "incident_id": incident_id,
                "service_id": service_id,
                "device_id": care.get("device_id"),
                "predictive_ticket_id": predictive_ticket_id,
                "predictive_match": bool(care.get("predictive_match")),
                "network_saw_it_first": bool(care.get("predictive_match")),
                "canonical_root_attachment": bool(care.get("incident_id")),
                "legacy_suppression_assertion": bool(
                    care.get("duplicate_incident_suppressed")
                ),
                "subscriber": subscribers.get(service_id),
                "manifest": manifest,
                "care": care,
                "care_ticket": care,
                "predictive": predictive_ticket,
                "predictive_ticket": predictive_ticket,
                "incident": incident,
                "root_incident": incident,
                "governance": governance,
                "validation": validations.get(case_id),
                "resolution": resolutions.get(case_id),
            }
        )

    semantic = _metric_projection(
        catalog,
        predictive_rows=predictive_rows,
        pull_rows=pull_rows,
        care_rows=care_rows,
        incident_rows=incident_rows,
        manifest_rows=manifest_rows,
        human_rows=human_rows,
        work_order_rows=work_order_rows,
        mr_rows=mr_rows,
        action_rows=action_rows,
        validation_rows=validation_rows,
        resolution_rows=resolution_rows,
    )
    metrics = semantic["metrics"]
    scorecard = {
        "homes_modeled": metrics["footprint_services"]["value"],
        "services_in_footprint": metrics["footprint_services"]["value"],
        "modems_scanned": metrics["scanned_devices"]["value"],
        "scan_coverage_pct": metrics["scan_coverage_pct"]["value"],
        "service_risks_found": metrics["at_risk_services"]["value"],
        "at_risk_services": metrics["at_risk_services"]["value"],
        "care_contacts_pre_correlated": metrics[
            "predictively_matched_contacts"
        ]["value"],
        "care_contacts_total": metrics["care_contacts"]["value"],
        "predictive_match_rate_pct": metrics["predictive_match_rate_pct"]["value"],
        "canonical_root_attachments": metrics[
            "canonical_root_attachments"
        ]["value"],
        "duplicate_incidents_avoided": None,
        "duplicate_metric_status": "not_observed",
        "cases_closed": metrics["closed_root_incidents"]["value"],
        "cases_total": metrics["root_incidents"]["value"],
        "root_incidents": metrics["root_incidents"]["value"],
        "governed_decisions": len(review_rows),
        "human_review_required": sum(
            bool(row.get("reconciled_human_review_required")) for row in review_rows
        ),
        "pending_approvals": metrics["pending_approvals"]["value"],
        "forecast_risks": metrics["forecast_risk_services"]["value"],
        "proactive_risks": metrics["degraded_services"]["value"],
    }
    governance_summary = {
        "data_integrity_gate_passed": bool(catalog.get("quality", {}).get("passed")),
        "data_integrity_controls": int(
            catalog.get("quality", {}).get("checks", 0) or 0
        ),
        "quality_gate_passed": bool(catalog.get("quality", {}).get("passed")),
        "quality_checks": int(catalog.get("quality", {}).get("checks", 0) or 0),
        "production_writes": bool(catalog.get("production_writes", False)),
        "governed_decisions": len(review_rows),
        "human_review_required": scorecard["human_review_required"],
        "pending_approvals": scorecard["pending_approvals"],
    }

    result = {
        "run_id": catalog.get("run_id", run_path.name),
        "release": catalog.get("release"),
        "config": catalog.get("config", {}),
        "quality": catalog.get("quality", {}),
        **semantic,
        "scorecard": scorecard,
        "kpis": scorecard,
        "governance": governance_summary,
        "rows": stories,
        "stories": stories,
        "customer_journeys": stories,
    }
    install_assurance = latest_install_assurance_projection(run_path, skip_incomplete=True)
    if install_assurance is not None:
        result["install_assurance"] = install_assurance
    return result
