"""Merge a gated predictive ticket into the main incident flow.

The operator's merge rule: **the predictive ticket stays parent, a later reactive
ticket attaches to it, and the SLA clock runs from when the scan opened the
predictive ticket, not from the customer's call.**

That rule has a consequence worth stating, because it is the opposite of the usual
instinct. A customer who calls about a modem the scan flagged three days ago
inherits an SLA that is already three days old, and may already be breached at the
moment they call. That is the point: the clock started when the operator first knew.
It also means `sla_breached_at_attach` must be surfaced, or an agent picking up the
call cannot see why the case is red.

`IncidentSeed` is the shape the main engine consumes. This module builds and
validates it; it does not import the engine, which needs pydantic. The seam is a
dataclass, so this branch stays independently runnable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal

from .config import DEFAULT_SCAN, ScanConfig
from .pipeline import Outcome
from .scanner import PredictiveTicket

MergeRole = Literal["parent", "child"]

# Predictive suspected cause to the main model's responsibility domain.
CAUSE_TO_DOMAIN: dict[str, str] = {
    "cpe_state": "cpe", "config_drift": "provisioning", "firmware": "cpe",
    "wifi_env": "wifi_or_home", "drop": "drop", "tap_or_odp": "hfc_tap",
    "plant": "plant", "stable": "unknown",
}


def domain_for(cause: str, technology: str) -> str:
    domain = CAUSE_TO_DOMAIN.get(cause, "unknown")
    if domain == "hfc_tap" and technology == "PON":
        return "pon_odp"
    return domain


@dataclass(frozen=True, slots=True)
class IncidentSeed:
    """What the main engine needs to open an incident from a predictive ticket."""

    incident_id: str
    source: str
    technology: str
    site_id: str
    modem_id: str
    title: str
    severity: str
    opened_at: datetime
    sla_due_at: datetime
    suspected_domain: str
    predictive_ticket_id: str
    predictive_class: str
    gate_reasons: tuple[str, ...]
    notify_reasons: tuple[str, ...]
    needs_truck_roll: bool
    auto_attempts: tuple[dict[str, Any], ...]
    evidence: tuple[dict[str, Any], ...]
    parent_incident_id: str | None = None
    merge_role: MergeRole = "parent"
    sla_inherited_from: str | None = None
    sla_breached_at_attach: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["opened_at"] = self.opened_at.isoformat()
        data["sla_due_at"] = self.sla_due_at.isoformat()
        return data


def seed_from(ticket: PredictiveTicket, outcome: Outcome) -> IncidentSeed:
    """Build the seed. Only a gated outcome should reach the main flow."""
    if outcome.verdict != "requires_approval":
        raise ValueError(
            f"{ticket.ticket_id} was resolved without a gate; it must not be "
            f"handed to the main flow")

    headline = ticket.headline
    evidence = tuple({
        "ref": f"pnm.{f.kpi}",
        "kpi": f.kpi, "value": f.value, "threshold": f.threshold,
        "direction": f.direction, "breached_now": f.breached_now,
        "days_to_breach": f.days_to_breach,
        "slope_per_day": f.slope_per_day, "r_squared": f.r_squared,
        "summary": (f"{f.kpi} at {f.value:g} against a {f.direction} alarm bound of "
                    f"{f.threshold:g}"
                    + (" , already breached" if f.breached_now
                       else f", reaching it in {f.days_to_breach:g} days")),
    } for f in ticket.findings)

    what = ("has already breached" if ticket.ticket_class == "proactive"
            else f"is forecast to breach in {headline.days_to_breach:g} days")
    return IncidentSeed(
        incident_id=f"INC-{ticket.ticket_id}",
        source="predictive_scan",
        technology=ticket.technology, site_id=ticket.site_id,
        modem_id=ticket.modem_id,
        title=f"{ticket.modem_id} {headline.kpi} {what}",
        severity=ticket.severity, opened_at=ticket.opened_at,
        sla_due_at=ticket.sla_due_at,
        suspected_domain=domain_for(ticket.suspected_cause, ticket.technology),
        predictive_ticket_id=ticket.ticket_id,
        predictive_class=ticket.ticket_class,
        gate_reasons=outcome.gate_reasons, notify_reasons=outcome.notify_reasons,
        needs_truck_roll=outcome.needs_truck_roll,
        auto_attempts=tuple({"action": a.action, "attempt_index": a.attempt_index,
                             "idempotency_key": a.idempotency_key,
                             "executed": a.executed, "succeeded": a.succeeded,
                             "reason": a.reason} for a in outcome.attempts),
        evidence=evidence, merge_role="parent")


@dataclass(frozen=True, slots=True)
class MergeDecision:
    reactive_incident_id: str
    parent_incident_id: str
    sla_due_at: datetime
    sla_inherited_from: str
    sla_breached_at_attach: bool
    hours_of_clock_already_spent: float
    rationale: str


def attach_customer_call(seed: IncidentSeed, *, reactive_incident_id: str,
                         called_at: datetime) -> MergeDecision:
    """A customer calls about a modem that already has a predictive incident.

    The predictive incident remains the parent and keeps its clock. The caller
    inherits an SLA that has already been running, which can be breached before
    they finish speaking, so that state is returned explicitly rather than left for
    an agent to discover.
    """
    spent = (called_at - seed.opened_at).total_seconds() / 3600.0
    breached = called_at > seed.sla_due_at
    return MergeDecision(
        reactive_incident_id=reactive_incident_id,
        parent_incident_id=seed.incident_id,
        sla_due_at=seed.sla_due_at,
        sla_inherited_from=seed.incident_id,
        sla_breached_at_attach=breached,
        hours_of_clock_already_spent=round(max(spent, 0.0), 2),
        rationale=("Predictive incident stays parent; the reactive ticket attaches. "
                   "The SLA runs from when the scan opened it, so "
                   f"{max(spent, 0.0):.1f}h were already spent before the customer "
                   "called"
                   + (" and the SLA was already breached." if breached else ".")))


def apply_merge(seed: IncidentSeed, decision: MergeDecision) -> IncidentSeed:
    """The child seed a reactive ticket becomes once attached."""
    return IncidentSeed(
        incident_id=decision.reactive_incident_id, source="customer_call",
        technology=seed.technology, site_id=seed.site_id, modem_id=seed.modem_id,
        title=f"Customer call on {seed.modem_id}",
        severity=seed.severity, opened_at=seed.opened_at,
        sla_due_at=decision.sla_due_at,
        suspected_domain=seed.suspected_domain,
        predictive_ticket_id=seed.predictive_ticket_id,
        predictive_class=seed.predictive_class,
        gate_reasons=seed.gate_reasons, notify_reasons=seed.notify_reasons,
        needs_truck_roll=seed.needs_truck_roll, auto_attempts=seed.auto_attempts,
        evidence=seed.evidence,
        parent_incident_id=decision.parent_incident_id, merge_role="child",
        sla_inherited_from=decision.sla_inherited_from,
        sla_breached_at_attach=decision.sla_breached_at_attach)
