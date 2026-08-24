from __future__ import annotations

from datetime import datetime, timedelta

ISSUE_TEXT = {
    "slow_wifi": "Customer reports Wi-Fi is slow or unstable inside the home.",
    "no_service": "Customer reports no broadband service.",
    "intermittent_service": "Customer reports repeated service drops.",
    "iptv_degradation": "Customer reports IPTV freezing or pixelation.",
    "fiber_cut": "Customer reports loss of service associated with an access fault.",
    "hfc_ingress": "Customer reports unstable broadband consistent with RF impairment.",
    "congestion": "Customer reports slow service during busy periods.",
    "power_outage": "Customer reports service unavailable during a power event.",
    "storm": "Customer reports service degradation during storm conditions.",
    "flooding": "Customer reports service loss during flooding conditions.",
    "hurricane": "Customer reports service loss during hurricane conditions.",
    "provisioning_error": "Customer reports service not working after activation or change.",
    "cpe_failure": "Customer reports gateway or modem malfunction.",
}

PRIORITY = {
    "no_service": "P1",
    "fiber_cut": "P1",
    "power_outage": "P1",
    "storm": "P1",
    "flooding": "P1",
    "hurricane": "P1",
    "intermittent_service": "P2",
    "hfc_ingress": "P2",
    "cpe_failure": "P2",
    "provisioning_error": "P2",
    "iptv_degradation": "P3",
    "congestion": "P3",
    "slow_wifi": "P3",
}

SLA_HOURS = {"P1": 8, "P2": 24, "P3": 48}


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def build_care_records(
    *,
    contacts: list[dict],
    manifests: list[dict],
    incidents: list[dict],
    subscribers: dict[str, dict],
    predictive_tickets: list[dict],
    deterministic: list[dict],
    agent: list[dict],
    reconciliation: list[dict],
) -> tuple[list[dict], list[dict]]:
    manifests_by_case = {row["case_id"]: row for row in manifests}
    incidents_by_id = {row["incident_id"]: row for row in incidents}
    deterministic_by_case = {row["case_id"]: row for row in deterministic}
    agent_by_case = {row["case_id"]: row for row in agent}
    reconciliation_by_case = {row["case_id"]: row for row in reconciliation}

    predictive_by_service: dict[str, list[dict]] = {}
    for ticket in predictive_tickets:
        predictive_by_service.setdefault(str(ticket["service_id"]), []).append(ticket)
    for tickets in predictive_by_service.values():
        tickets.sort(
            key=lambda row: (
                0 if row["ticket_class"] == "proactive" else 1,
                0 if row["severity"] in {"critical", "high"} else 1,
                row["opened_at"],
            )
        )

    care_tickets: list[dict] = []
    reviews: list[dict] = []
    for contact in contacts:
        case_id = contact["case_id"]
        manifest = manifests_by_case[case_id]
        scenario = manifest["scenario"]
        incident = incidents_by_id[manifest["root_incident_id"]]
        sub = subscribers[str(contact["service_id"])]
        opened_at = _parse(contact["contact_timestamp"])
        candidates = [
            row
            for row in predictive_by_service.get(str(contact["service_id"]), [])
            if _parse(row["opened_at"]) <= opened_at
        ]
        predictive = candidates[0] if candidates else None
        priority = PRIORITY.get(scenario, "P3")
        care_ticket_id = f"CARE-{contact['contact_id']}"
        if predictive is not None:
            disposition = "ATTACH_TO_PREDICTIVE_ROOT_INCIDENT"
            incident["origin"] = "PREDICTIVE"
            incident["predictive_ticket_id"] = predictive["ticket_id"]
            predictive_opened = _parse(predictive["opened_at"])
            incident_opened = _parse(incident["opened_at"])
            if predictive_opened < incident_opened:
                incident["opened_at"] = predictive["opened_at"]
        else:
            disposition = "ATTACH_TO_REACTIVE_ROOT_INCIDENT"
            incident.setdefault("origin", "REACTIVE")
            incident.setdefault("predictive_ticket_id", None)

        ticket = {
            "care_ticket_id": care_ticket_id,
            "contact_id": contact["contact_id"],
            "case_id": case_id,
            "root_case_id": manifest["root_case_id"],
            "incident_id": manifest["root_incident_id"],
            "service_id": contact["service_id"],
            "device_id": sub["device_id"],
            "opened_at": contact["contact_timestamp"],
            "closed_at": incident.get("closed_at"),
            "status": "CLOSED" if incident.get("status") == "CLOSED" else "OPEN",
            "channel": contact.get("channel", "VOICE"),
            "category": scenario,
            "issue_summary": ISSUE_TEXT.get(scenario, "Customer reports broadband service issue."),
            "priority": priority,
            "sla_due_at": (opened_at + timedelta(hours=SLA_HOURS[priority])).isoformat(),
            "repeat_contact": bool(contact.get("repeat_contact")),
            "repeat_sequence": int(contact.get("repeat_sequence", 0)),
            "predictive_match": predictive is not None,
            "predictive_ticket_id": predictive["ticket_id"] if predictive else None,
            "predictive_class": predictive["ticket_class"] if predictive else None,
            "predictive_severity": predictive["severity"] if predictive else None,
            "correlation_disposition": disposition,
            "duplicate_incident_suppressed": True,
            "production_write": False,
        }
        care_tickets.append(ticket)

        det = deterministic_by_case[case_id]
        agent_row = agent_by_case[case_id]
        rec = reconciliation_by_case[case_id]
        reviews.append(
            {
                "care_ticket_id": care_ticket_id,
                "case_id": case_id,
                "incident_id": manifest["root_incident_id"],
                "service_id": contact["service_id"],
                "review_status": "REVIEWED",
                "incident_status": incident.get("status"),
                "deterministic_domain": det["recommended_domain"],
                "deterministic_action": det["best_action"],
                "eligible_actions": det["eligible_actions"],
                "agent_source": agent_row["source"],
                "agent_provider_status": agent_row["provider_status"],
                "agent_domain": agent_row["recommended_domain"],
                "agent_action": agent_row["best_action"],
                "agent_confidence": agent_row["confidence"],
                "agent_rationale": agent_row["concise_rationale"],
                "reconciled_human_review_required": rec["human_review_required"],
                "reconciliation_reason": rec["reason"],
                "predictive_match": predictive is not None,
                "predictive_ticket_id": predictive["ticket_id"] if predictive else None,
                "recommended_disposition": disposition,
                "evidence_refs": [
                    f"TEL-{case_id}-PRE",
                    f"ALM-{case_id}",
                    *([predictive["ticket_id"]] if predictive else []),
                ],
            }
        )
    return care_tickets, reviews


def refresh_care_status(
    care_tickets: list[dict], care_reviews: list[dict], incidents: list[dict]
) -> tuple[set[str], set[str]]:
    incidents_by_id = {row["incident_id"]: row for row in incidents}
    changed_tickets: set[str] = set()
    changed_reviews: set[str] = set()
    for ticket in care_tickets:
        incident = incidents_by_id.get(ticket["incident_id"])
        if not incident:
            continue
        status = "CLOSED" if incident.get("status") == "CLOSED" else "OPEN"
        closed_at = incident.get("closed_at") if status == "CLOSED" else None
        if ticket.get("status") != status or ticket.get("closed_at") != closed_at:
            ticket["status"] = status
            ticket["closed_at"] = closed_at
            changed_tickets.add(ticket["care_ticket_id"])
    if changed_tickets:
        for review in care_reviews:
            if review["care_ticket_id"] in changed_tickets:
                review["incident_status"] = incidents_by_id[review["incident_id"]]["status"]
                changed_reviews.add(review["care_ticket_id"])
    return changed_tickets, changed_reviews
