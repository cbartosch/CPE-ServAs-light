"""The four decision agents.

Each decides; the deterministic function it replaced becomes its baseline, its
fallback and the dissent check the gate reads. The rules did not go away, they
changed job.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Sequence

from ..controls import fuse_and_gate
from ..geography import SITE_BY_ID, DispatchBase, select_base
from ..plant import DOMAIN_TO_KIND, blast_radius
from .base import (Agent, AgentDecision, AgentError, Alternative, one_of,
                   require)
from .provider import Provider

DOMAINS = ("cpe", "wifi_or_home", "premise_wiring", "provisioning", "drop",
           "hfc_tap", "pon_odp", "plant", "shared_network", "unknown")
ACTIONS = ("remote_reprovision", "remote_reboot", "self_help", "clean_boots",
           "dirty_boots_mr", "joint_dispatch", "plant_action", "manual_review",
           "monitor")
TRIAGE = ("act_now", "schedule", "monitor", "suppress")

_JSON_ONLY = ("Return one JSON object and nothing else. No prose, no code fence.")


def _alternatives(payload: dict[str, Any], key: str, allowed: Sequence[str],
                  field_name: str) -> tuple[Alternative, ...]:
    """Parse the second-best options. A missing `why_not_chosen` is rejected.

    An alternative without a reason it lost is a list entry. With one it is a
    decision an operator can overturn at the gate, which is the only reason to
    show it.
    """
    raw = payload.get(key) or []
    if not isinstance(raw, list):
        raise AgentError(f"{key!r} must be a list")
    out = []
    for item in raw[:3]:
        if not isinstance(item, dict):
            raise AgentError(f"{key!r} entries must be objects")
        out.append(Alternative(
            choice=one_of(require(item, "choice", str), allowed, field_name),
            confidence=float(require(item, "confidence", float)),
            rationale=require(item, "rationale", str),
            why_not_chosen=require(item, "why_not_chosen", str)))
    return tuple(out)


# --------------------------------------------------------------------- RCA
RCA_SYSTEM = (
    "You are a fixed-access fault diagnosis agent for an HFC and PON network. "
    "Decide the single responsibility domain most likely at fault. "
    "A deterministic classifier runs alongside you and its answer is shown; it no "
    "longer decides, but a disagreement between you and it routes the incident to "
    "a human, so differ only when the evidence warrants it. "
    "Blast radius is the strongest discriminator: a fault affecting one household "
    "is a drop or premise issue, several households on one tap or splitter is a "
    "delimiter issue, and hundreds is plant. " + _JSON_ONLY +
    ' Schema: {"domain": str, "confidence": 0..1, "rationale": str, '
    '"alternatives": [{"choice": str, "confidence": 0..1, "rationale": str, '
    '"why_not_chosen": str}], "notes": [str]}')


def rca_agent(provider: Provider, *, baseline_domain: str) -> Agent[str]:
    def parse(payload):
        return (one_of(require(payload, "domain", str), DOMAINS, "domain"),
                require(payload, "confidence", float),
                require(payload, "rationale", str),
                _alternatives(payload, "alternatives", DOMAINS, "domain"),
                tuple(payload.get("notes") or []))
    return Agent("rca", RCA_SYSTEM, provider, parse, lambda: baseline_domain)


def rca_prompt(*, technology: str, site: str, evidence: Sequence[dict],
               households_affected: int, baseline_domain: str,
               baseline_confidence: float) -> str:
    return json.dumps({
        "technology": technology, "site": site,
        "households_affected": households_affected,
        "deterministic_classifier": {"domain": baseline_domain,
                                     "confidence": baseline_confidence},
        "evidence": list(evidence)[:24],
    }, indent=1, default=str)


# ------------------------------------------------------------ recommendation
RECOMMEND_SYSTEM = (
    "You are a remediation planning agent. Given a confirmed fault domain, choose "
    "the action to take now and the next-best alternative. "
    "Prefer the least invasive action that can plausibly resolve the domain: a "
    "remote action before a visit, a clean-boots visit before plant work. "
    "A remote action cannot repair physical plant, so never propose one for a tap, "
    "ODP or plant domain. "
    "You must return at least one alternative with the reason it lost, because an "
    "operator at the approval gate needs something to overturn to. " + _JSON_ONLY +
    ' Schema: {"action": str, "confidence": 0..1, "rationale": str, '
    '"alternatives": [{"choice": str, "confidence": 0..1, "rationale": str, '
    '"why_not_chosen": str}], "notes": [str]}')


def recommendation_agent(provider: Provider, *,
                         baseline_action: str) -> Agent[str]:
    def parse(payload):
        alternatives = _alternatives(payload, "alternatives", ACTIONS, "action")
        if not alternatives:
            raise AgentError("at least one alternative with why_not_chosen is "
                             "required; a recommendation with no second best "
                             "gives the approver nothing to weigh")
        return (one_of(require(payload, "action", str), ACTIONS, "action"),
                require(payload, "confidence", float),
                require(payload, "rationale", str), alternatives,
                tuple(payload.get("notes") or []))
    return Agent("recommendation", RECOMMEND_SYSTEM, provider, parse,
                 lambda: baseline_action)


def recommendation_prompt(*, domain: str, technology: str, households: int,
                          remote_attempts: int, field_visits: int,
                          baseline_action: str, constraints: dict) -> str:
    return json.dumps({
        "confirmed_domain": domain, "technology": technology,
        "households_affected": households,
        "attempts_so_far": {"remote": remote_attempts, "field": field_visits},
        "deterministic_ranking_top": baseline_action,
        "constraints": constraints,
    }, indent=1, default=str)


# ------------------------------------------------------------------- routing
ROUTE_SYSTEM = (
    "You are a dispatch routing agent. Choose which base a crew should be sent "
    "from. You are given every candidate base with its computed travel time, "
    "skills, van stock, ferry requirement and whether the round trip fits one "
    "shift. "
    "The travel times are computed from a road-speed model and are not yours to "
    "revise; your job is to weigh them against skills, parts, shift feasibility "
    "and SLA, which is where the nearest base is often the wrong one. "
    "Never choose a base that lacks a required skill or part. " + _JSON_ONLY +
    ' Schema: {"base_id": str, "confidence": 0..1, "rationale": str, '
    '"alternatives": [{"choice": str, "confidence": 0..1, "rationale": str, '
    '"why_not_chosen": str}], "notes": [str]}')


def route_agent(provider: Provider, *, candidates: Sequence[str],
                baseline_base: str) -> Agent[str]:
    def parse(payload):
        return (one_of(require(payload, "base_id", str), candidates, "base_id"),
                require(payload, "confidence", float),
                require(payload, "rationale", str),
                _alternatives(payload, "alternatives", candidates, "base_id"),
                tuple(payload.get("notes") or []))
    return Agent("routing", ROUTE_SYSTEM, provider, parse, lambda: baseline_base)


def route_prompt(*, site_id: str, crew_type: str, required_skills: Sequence[str],
                 required_parts: Sequence[str], options: Sequence[dict],
                 sla_hours_remaining: float | None = None) -> str:
    return json.dumps({
        "site_id": site_id, "municipio": SITE_BY_ID[site_id].municipio,
        "archetype": SITE_BY_ID[site_id].archetype,
        "crew_type": crew_type, "required_skills": list(required_skills),
        "required_parts": list(required_parts),
        "sla_hours_remaining": sla_hours_remaining,
        "candidate_bases": list(options),
    }, indent=1, default=str)


def route_options(site_id: str, *, crew_type: str,
                  required_skills: Sequence[str] = (),
                  required_parts: Sequence[str] = (),
                  bases: Sequence[DispatchBase] | None = None) -> list[dict]:
    """Every candidate with its computed facts, so the agent weighs rather than
    estimates."""
    from ..geography import DISPATCH_BASES, travel_plan
    site = SITE_BY_ID[site_id]
    out = []
    for base in (bases or DISPATCH_BASES):
        if crew_type not in base.crew_types:
            continue
        plan = travel_plan(base, site)
        out.append({
            "base_id": base.base_id, "name": base.name,
            "likelihood": base.likelihood,
            "one_way_minutes": plan.total_minutes,
            "requires_ferry": plan.requires_ferry,
            "fits_one_shift": plan.same_day_feasible,
            "has_required_skills": set(required_skills).issubset(base.skills),
            "has_required_parts": set(required_parts).issubset(base.van_stock),
            "missing_skills": sorted(set(required_skills) - set(base.skills)),
            "missing_parts": sorted(set(required_parts) - set(base.van_stock)),
        })
    return sorted(out, key=lambda o: o["one_way_minutes"])


# ---------------------------------------------------------------- predictive
TRIAGE_SYSTEM = (
    "You are a predictive maintenance triage agent. A nightly scan has flagged a "
    "modem. Decide whether to act now, schedule the work, keep monitoring, or "
    "suppress the ticket as not worth acting on. "
    "A trend fit with low r-squared is noise, not a forecast, and suppressing it "
    "is correct. A breach already in effect on a service-critical measurement is "
    "act_now. Weigh how many households sit behind the element, since a tap or "
    "splitter fault reaches several. " + _JSON_ONLY +
    ' Schema: {"triage": str, "confidence": 0..1, "rationale": str, '
    '"alternatives": [{"choice": str, "confidence": 0..1, "rationale": str, '
    '"why_not_chosen": str}], "notes": [str]}')


def triage_agent(provider: Provider, *, baseline_triage: str) -> Agent[str]:
    def parse(payload):
        return (one_of(require(payload, "triage", str), TRIAGE, "triage"),
                require(payload, "confidence", float),
                require(payload, "rationale", str),
                _alternatives(payload, "alternatives", TRIAGE, "triage"),
                tuple(payload.get("notes") or []))
    return Agent("predictive_triage", TRIAGE_SYSTEM, provider, parse,
                 lambda: baseline_triage)


def triage_prompt(ticket: Any, *, households_affected: int) -> str:
    return json.dumps({
        "ticket_class": ticket.ticket_class, "severity": ticket.severity,
        "technology": ticket.technology,
        "repeat_offender": ticket.repeat_offender,
        "previous_flags": ticket.previous_flags,
        "households_behind_element": households_affected,
        "findings": [{"kpi": f.kpi, "value": f.value, "threshold": f.threshold,
                      "breached_now": f.breached_now,
                      "days_to_breach": f.days_to_breach,
                      "slope_per_day": f.slope_per_day,
                      "r_squared": f.r_squared} for f in ticket.findings],
    }, indent=1, default=str)


def baseline_triage_for(ticket: Any) -> str:
    """The deterministic triage the agent replaces, kept as its check."""
    if ticket.ticket_class == "proactive":
        return "act_now"
    eta = ticket.headline.days_to_breach
    if eta is not None and eta <= 3:
        return "act_now"
    return "schedule" if ticket.severity in {"high", "medium"} else "monitor"
