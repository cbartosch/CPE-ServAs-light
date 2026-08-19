"""Process a predictive ticket: auto-remediate first, gate second.

This is the branch that behaves differently from the main engine. `WorkflowEngine`
requires approval for every action; here the operator chose to auto-remediate and
gate only on failure or notification, which is what finally gives
`PolicyVerdict.ALLOWED` a code path.

Gate conditions, exactly as specified:

* auto-remediation did not succeed, or
* the customer must be notified, which is true when a truck roll will be needed,
  a hard failure is forecast inside the horizon, or the modem is a repeat offender.

A service-affecting remediation on its own is deliberately NOT a notification
trigger. That was chosen, and it has a consequence: a working modem can be
rebooted with no notice. The maintenance window is the control that makes that
defensible, so `execute_allowed` refuses a service-affecting action outside it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Sequence

from ..agents.base import AgentDecision
from ..agents.decisions import (baseline_triage_for, triage_agent,
                                triage_prompt)
from ..agents.guards import ActionRequest, evaluate as evaluate_policy
from ..agents.provider import Provider, provider_from_env
from ..commercial import CustomerRecord, RankedDispatch, rank
from .config import (DEFAULT_REMEDIATION, DEFAULT_SCAN,
                     HARD_FAILURE_KPIS, PHYSICAL_CAUSES,
                     RemediationConfig, ScanConfig)
from .scanner import PredictiveTicket

Verdict = Literal["allowed", "requires_approval", "blocked"]
ActionType = Literal["remote_reboot", "remote_reprovision", "monitor"]

# Actions that interrupt service, so they may only run inside the window.
SERVICE_AFFECTING = frozenset({"remote_reboot"})

# Predictive suspected cause to the responsibility domain policy reasons about.
_DOMAIN_FOR_CAUSE = {
    "cpe_state": "cpe", "config_drift": "provisioning", "firmware": "cpe",
    "wifi_env": "wifi_or_home", "drop": "drop", "tap_or_odp": "hfc_tap",
    "plant": "plant", "stable": "unknown",
}

NOTIFY_TRUCK_ROLL = "truck_roll_required"
NOTIFY_HARD_FAILURE = "hard_failure_forecast"
NOTIFY_REPEAT = "repeat_offender"


@dataclass(frozen=True, slots=True)
class Attempt:
    action: ActionType
    attempt_index: int
    idempotency_key: str
    executed: bool
    succeeded: bool
    reason: str


@dataclass(frozen=True, slots=True)
class Outcome:
    ticket_id: str
    modem_id: str
    attempts: tuple[Attempt, ...]
    resolved: bool
    verdict: Verdict
    gate_reasons: tuple[str, ...]
    notify_reasons: tuple[str, ...]
    needs_truck_roll: bool
    escalated: bool
    service_interruption_minutes: int
    # Populated when a triage agent ran. `None` means the deterministic path was
    # used, which is the default and needs no provider.
    triage: str | None = None
    triage_source: str | None = None
    triage_agrees_with_baseline: bool | None = None
    policy_blocked: tuple[str, ...] = ()
    # Commercial ranking, populated when a customer record is supplied. A dispatch
    # decision without one still works; it simply carries no priority.
    priority: RankedDispatch | None = None

    @property
    def notification_required(self) -> bool:
        return bool(self.notify_reasons)

    @property
    def handed_to_human(self) -> bool:
        return self.verdict == "requires_approval"


def action_key(ticket: PredictiveTicket, action: str, attempt_index: int) -> str:
    """Derived from durable state, never from a clock or a uuid.

    Same construction as `controls.derive_action_key`: re-running the branch after
    a crash must reproduce the key so the effect store recognises the replay.
    """
    material = "|".join(("prd_v1", ticket.ticket_id, ticket.modem_id, action,
                         str(int(attempt_index))))
    return "idem-" + hashlib.sha256(material.encode()).hexdigest()[:40]


def plan_actions(ticket: PredictiveTicket) -> list[ActionType]:
    """Which remote actions to try, in order, given the suspected cause.

    A physical cause gets no remote attempt at all. Rebooting a modem behind a
    corroded tap interrupts a customer's service and cannot fix anything, so the
    branch goes straight to the gate.
    """
    if ticket.suspected_cause in PHYSICAL_CAUSES:
        return []
    if ticket.suspected_cause == "config_drift":
        return ["remote_reprovision", "remote_reboot"]
    return ["remote_reboot", "remote_reprovision"]


def execute_allowed(action: ActionType, hour: int,
                    config: ScanConfig = DEFAULT_SCAN) -> tuple[bool, str]:
    """A service-affecting action runs only inside the maintenance window."""
    if action not in SERVICE_AFFECTING:
        return True, "not service affecting"
    if config.in_maintenance_window(hour):
        return True, "inside the maintenance window"
    return False, (f"deferred: {action} interrupts service and the window is "
                   f"{config.maintenance_window_start_hour:02d}:00 to "
                   f"{config.maintenance_window_end_hour:02d}:00")


def _succeeds(action: ActionType, cause: str, roll: float,
              config: RemediationConfig) -> bool:
    return roll < config.success_by_cause.get(cause, {}).get(action, 0.0)


def notification_reasons(ticket: PredictiveTicket, *, needs_truck_roll: bool,
                         resolved: bool = False,
                         config: ScanConfig = DEFAULT_SCAN) -> list[str]:
    """The three triggers the operator selected, assessed on RESIDUAL risk.

    `resolved` matters. Evaluating the triggers against the original finding meant
    a forecast failure that remediation had already averted still demanded a
    customer notification: there is nothing left to tell them about. Truck roll and
    hard failure are therefore conditional on the ticket still being open.

    Repeat offender is not. A modem flagged three times in a month is worth telling
    the customer about even when tonight's reboot worked, because the pattern is
    the message.
    """
    reasons: list[str] = []
    if needs_truck_roll:
        reasons.append(NOTIFY_TRUCK_ROLL)
    if not resolved and ticket.ticket_class == "forecast":
        # A hard failure is loss of service, not any breach. Without this the
        # trigger fires on every forecast ticket and stops discriminating, since
        # the scanner only raises one when the breach is inside the horizon.
        hard = [f for f in ticket.findings
                if f.kpi in HARD_FAILURE_KPIS and f.days_to_breach is not None
                and f.days_to_breach <= config.forecast_horizon_days]
        if hard:
            reasons.append(NOTIFY_HARD_FAILURE)
    if ticket.repeat_offender:
        reasons.append(NOTIFY_REPEAT)
    return reasons


def process(ticket: PredictiveTicket, *, hour: int, rolls: Sequence[float],
            scan_config: ScanConfig = DEFAULT_SCAN,
            remediation: RemediationConfig = DEFAULT_REMEDIATION,
            provider: Provider | None = None,
            households_affected: int = 1,
            customer: CustomerRecord | None = None,
            sla_breached: bool = False) -> Outcome:
    """Run one ticket to a verdict.

    `rolls` supplies the random draws, so a run is reproducible and a test can
    force success or failure rather than retrying until it sees both.

    `provider` opts the triage agent in. Without one the deterministic triage
    stands, which is the default: the branch must run with no key and no network.
    """
    triage: str | None = None
    triage_source: str | None = None
    triage_agrees: bool | None = None
    if provider is not None:
        decision: AgentDecision[str] = triage_agent(
            provider, baseline_triage=baseline_triage_for(ticket)).decide(
                triage_prompt(ticket, households_affected=households_affected))
        triage = decision.decision
        triage_source = decision.source
        triage_agrees = decision.agrees_with_baseline
        # The agent may dismiss a finding as noise, but it may not do so for a
        # breach that is already in effect.
        #
        # Red-team finding: an injected `suppress` on a critical proactive ticket
        # returned before `evaluate_policy` was reached, and cleared
        # `needs_truck_roll` and every notification reason along with it. A
        # suppression therefore erased the customer notification that the
        # un-suppressed path would have produced. Suppression is now refused
        # outright when a threshold has already been crossed, and otherwise still
        # goes to a human.
        if triage == "suppress":
            already_breached = [f for f in ticket.findings if f.breached_now]
            if already_breached:
                return Outcome(
                    ticket.ticket_id, ticket.modem_id, (), False, "blocked",
                    ("agent_suppression_refused_breach_in_effect",), (),
                    True, True, 0, triage, triage_source, triage_agrees,
                    (f"{already_breached[0].kpi} has already crossed its alarm "
                     f"threshold, so the finding cannot be dismissed as noise",))
            return Outcome(ticket.ticket_id, ticket.modem_id, (), False,
                           "requires_approval",
                           ("agent_suppressed_as_noise",), (), False, True, 0,
                           triage, triage_source, triage_agrees, ())

    attempts: list[Attempt] = []
    resolved = False
    interruption = 0

    for index, action in enumerate(plan_actions(ticket)[:remediation.max_auto_attempts]):
        key = action_key(ticket, action, index)
        may_run, why = execute_allowed(action, hour, scan_config)
        if not may_run:
            attempts.append(Attempt(action, index, key, False, False, why))
            continue
        roll = rolls[index] if index < len(rolls) else 1.0
        won = _succeeds(action, ticket.suspected_cause, roll, remediation)
        if action in SERVICE_AFFECTING:
            interruption += remediation.reboot_service_interruption_minutes
        attempts.append(Attempt(action, index, key, True, won,
                                "resolved" if won else "did not clear the condition"))
        if won:
            resolved = True
            break

    # A physical cause, or an exhausted remote path, means someone drives out.
    needs_truck_roll = (not resolved
                        and (ticket.suspected_cause in PHYSICAL_CAUSES
                             or all(a.executed for a in attempts)))
    # Nothing attempted because everything was deferred is not a truck roll yet.
    if attempts and not any(a.executed for a in attempts):
        needs_truck_roll = False

    notify = notification_reasons(ticket, needs_truck_roll=needs_truck_roll,
                                  resolved=resolved, config=scan_config)

    gate_reasons: list[str] = []
    if not resolved:
        gate_reasons.append("auto_remediation_unsuccessful")
    if notify:
        gate_reasons.append("customer_notification_required")
    deferred = [a for a in attempts if not a.executed]
    if deferred and not resolved:
        gate_reasons.append("deferred_to_maintenance_window")

    # A hard stop the branch previously could not express. `Verdict` declared
    # "blocked" and no code path returned it, so an unsafe predictive action could
    # only ever be approved by a human rather than refused outright.
    blocked: tuple[str, ...] = ()
    if needs_truck_roll:
        policy = evaluate_policy(ActionRequest(
            domain=_DOMAIN_FOR_CAUSE.get(ticket.suspected_cause, "unknown"),
            action="dirty_boots_mr" if ticket.suspected_cause in PHYSICAL_CAUSES
                   else "clean_boots",
            technology=ticket.technology, site_id=ticket.site_id,
            evidence_count=len(ticket.findings),
            agent_agrees_with_baseline=triage_agrees,
            agent_is_fallback=triage_source == "deterministic_fallback"))
        if policy.verdict == "blocked":
            blocked = policy.reasons

    # Rank the dispatch commercially, but only once it is established that a
    # dispatch is needed. Ranking a ticket that will be fixed remotely would put a
    # customer's value into a decision that never involves a crew.
    priority: RankedDispatch | None = None
    if customer is not None and needs_truck_roll:
        ranked = rank([(ticket.ticket_id, customer, ticket.site_id,
                        {"households_affected": households_affected,
                         "sla_breached": sla_breached,
                         "service_down": any(f.breached_now
                                             for f in ticket.findings),
                         "crew_type": ("dirty" if ticket.suspected_cause
                                       in PHYSICAL_CAUSES else "clean")})])
        priority = ranked[0]

    verdict: Verdict = ("blocked" if blocked else
                        "requires_approval" if gate_reasons else "allowed")
    return Outcome(
        ticket_id=ticket.ticket_id, modem_id=ticket.modem_id,
        attempts=tuple(attempts), resolved=resolved, verdict=verdict,
        gate_reasons=tuple(gate_reasons), notify_reasons=tuple(notify),
        needs_truck_roll=needs_truck_roll,
        escalated=bool(gate_reasons) or bool(blocked),
        service_interruption_minutes=interruption,
        triage=triage, triage_source=triage_source,
        triage_agrees_with_baseline=triage_agrees, policy_blocked=blocked,
        priority=priority)
