from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .storage import get_active_run, iter_jsonl_gz, safe_run_path


def _load_rows(run_path: Path, dataset: str) -> list[dict[str, Any]]:
    path = run_path / f"{dataset}.jsonl.gz"
    if not path.exists():
        return []
    return list(iter_jsonl_gz(path))


def _index(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {
        str(row[key]): row
        for row in rows
        if row.get(key) is not None
    }


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


def _subscriber_index(run_path: Path, service_ids: set[str]) -> dict[str, dict[str, Any]]:
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


def build_executive_projection(
    root_or_run_path: Path,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Join predictive, Care, incident and governance records for an executive view.

    ``root_or_run_path`` may be either a concrete ``RUN-*`` directory or the data
    root. When it is the data root, ``run_id`` selects a run; if omitted, the
    persisted active run (or latest recoverable catalog) is used.
    """
    run_path = _resolve_run_path(root_or_run_path, run_id)
    catalog_path = run_path / "catalog.json"
    if not catalog_path.is_file():
        raise FileNotFoundError("run catalog not found")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

    predictive_rows = _load_rows(run_path, "predictive_tickets")
    care_rows = _load_rows(run_path, "care_tickets")
    incident_rows = _load_rows(run_path, "incidents")
    review_rows = _load_rows(run_path, "care_ticket_reviews")
    manifest_rows = _load_rows(run_path, "scenario_manifests")
    deterministic_rows = _load_rows(run_path, "deterministic_decisions")
    agent_rows = _load_rows(run_path, "agent_decisions")
    reconciliation_rows = _load_rows(run_path, "reconciliation_records")
    human_rows = _load_rows(run_path, "human_decisions")
    action_rows = _load_rows(run_path, "action_events")
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

    service_ids = {
        str(row["service_id"])
        for row in care_rows
        if row.get("service_id") is not None
    }
    subscribers = _subscriber_index(run_path, service_ids)

    stories: list[dict[str, Any]] = []
    for care in sorted(
        care_rows,
        key=lambda row: (str(row.get("opened_at", "")), str(row.get("care_ticket_id", ""))),
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
                "duplicate_incident_suppressed": bool(
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

    matched = sum(bool(row.get("predictive_match")) for row in care_rows)
    duplicate_incidents_avoided = sum(
        bool(row.get("duplicate_incident_suppressed")) for row in care_rows
    )
    cases_closed = sum(row.get("status") == "CLOSED" for row in incident_rows)
    human_review_required = sum(
        bool(row.get("reconciled_human_review_required")) for row in review_rows
    )
    forecast_risks = sum(row.get("ticket_class") == "forecast" for row in predictive_rows)
    proactive_risks = sum(row.get("ticket_class") == "proactive" for row in predictive_rows)
    homes_modeled = int(catalog.get("config", {}).get("homes", 0) or 0)

    scorecard = {
        "homes_modeled": homes_modeled,
        "service_risks_found": len(predictive_rows),
        "care_contacts_pre_correlated": matched,
        "care_contacts_total": len(care_rows),
        "duplicate_incidents_avoided": duplicate_incidents_avoided,
        "cases_closed": cases_closed,
        "cases_total": len(incident_rows),
        "governed_decisions": len(review_rows),
        "human_review_required": human_review_required,
        "forecast_risks": forecast_risks,
        "proactive_risks": proactive_risks,
    }
    governance_summary = {
        "quality_gate_passed": bool(catalog.get("quality", {}).get("passed")),
        "quality_checks": int(catalog.get("quality", {}).get("checks", 0) or 0),
        "production_writes": bool(catalog.get("production_writes", False)),
        "governed_decisions": len(review_rows),
        "human_review_required": human_review_required,
    }

    return {
        "run_id": catalog.get("run_id", run_path.name),
        "release": catalog.get("release"),
        "config": catalog.get("config", {}),
        "quality": catalog.get("quality", {}),
        "scorecard": scorecard,
        "kpis": scorecard,
        "governance": governance_summary,
        "rows": stories,
        "stories": stories,
        "customer_journeys": stories,
    }
