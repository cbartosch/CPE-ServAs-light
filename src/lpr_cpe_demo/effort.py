"""Time and cost of resolving an incident, including the cost of getting it wrong.

Every rate and duration here is ASSUMED
---------------------------------------
`RATES` and `DURATIONS` are placeholders of the right order of magnitude for a
Caribbean fixed-access operator. They are not LPR figures. Replace both before
any number leaves a demonstration. `assumptions()` returns them so the UI and the
API can print what they are being computed from.

What this module is for
-----------------------
The A/B harness reports that retrieval catches four rules errors at the cost of
three false alarms, with gate precision 0.571. That is defensible but abstract.
This module converts each outcome into technician minutes and money, so the
trade-off can be argued about in the units an operations manager uses.

Two costs, asymmetric by roughly an order of magnitude:

false positive
    A gate fires and the deterministic classifier was right. Cost is an L2 review
    plus delay against the SLA clock. Minutes, not truck rolls.

false negative
    The classifier is wrong and nothing catches it, so the wrong crew is
    dispatched. A clean-boots technician drives to a premise whose fault is at the
    tap, finds nothing, raises a handover, and a dirty-boots crew makes a second
    visit. The avoidable portion is the entire wasted visit plus the handover.

Because a truck roll costs one to two orders of magnitude more than a review, an
arm can afford to be wrong about a gate quite often and still come out ahead.
Whether it does is an empirical question, which is what `compare_arms` answers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal

from .geography import SITE_BY_ID, DispatchBase, select_base
from .plant import blast_radius

# ------------------------------------------------------------------ rates
# Fully loaded hourly cost in USD, and per-incident fixed costs.
RATES: dict[str, float] = {
    "noc_analyst_hour": 45.0,
    "l2_sme_hour": 65.0,
    "dispatcher_hour": 50.0,
    "clean_boots_hour": 55.0,        # one technician
    "dirty_boots_hour": 140.0,       # two technicians plus bucket or splice truck
    "vehicle_km": 0.60,
    "ferry_round_trip": 180.0,       # vehicle and cargo slot, assumed
    "overnight_premium": 220.0,      # per crew, when a round trip exceeds one shift
    "parts_cpe": 85.0,
    "parts_drop": 40.0,
    "parts_tap": 120.0,
    "parts_odp": 260.0,
}

# Minutes.
DURATIONS: dict[str, int] = {
    "triage": 10,
    "rca_cycle": 15,
    "remote_attempt": 25,
    "self_help_guided": 20,
    "gate_review": 12,               # L2/SME looking at a raised gate
    "dispatch_planning": 8,
    "clean_boots_on_site": 90,
    "dirty_boots_on_site": 180,
    "handover_package": 25,          # sending crew assembling evidence
    "handover_review": 15,           # dispatcher approving it
    "verification": 12,
    "closure": 8,
}

ROAD_KM_PER_MINUTE = 0.75           # implied by the archetype road speeds


def assumptions() -> dict[str, object]:
    return {"rates_usd": dict(RATES), "durations_minutes": dict(DURATIONS),
            "basis": "placeholder figures of plausible magnitude, not LPR actuals"}


@dataclass(frozen=True, slots=True)
class LedgerLine:
    step: str
    role: str
    minutes: int
    cost_usd: float
    note: str = ""


@dataclass(slots=True)
class EffortLedger:
    incident_id: str
    site_id: str
    lines: list[LedgerLine] = field(default_factory=list)

    def add(self, step: str, role: str, minutes: int, cost: float, note: str = "") -> None:
        self.lines.append(LedgerLine(step, role, minutes, round(cost, 2), note))

    @property
    def total_minutes(self) -> int:
        return sum(l.minutes for l in self.lines)

    @property
    def total_cost(self) -> float:
        return round(sum(l.cost_usd for l in self.lines), 2)

    @property
    def truck_rolls(self) -> int:
        return sum(1 for l in self.lines if l.step.endswith("on site"))

    def elapsed_hours(self) -> float:
        return round(self.total_minutes / 60.0, 2)

    def as_rows(self) -> list[dict[str, object]]:
        return [{"step": l.step, "role": l.role, "minutes": l.minutes,
                 "cost_usd": l.cost_usd, "note": l.note} for l in self.lines]


def _labour(role_hour_key: str, minutes: int) -> float:
    return RATES[role_hour_key] * minutes / 60.0


def _visit(ledger: EffortLedger, *, crew: Literal["clean", "dirty"], site_id: str,
           required_skills: tuple[str, ...] = (), required_parts: tuple[str, ...] = (),
           parts_cost_key: str | None = None, label: str = "") -> None:
    """One truck roll: planning, travel both ways, on-site work, parts."""
    site = SITE_BY_ID[site_id]
    sel = select_base(site, crew_type=crew, required_skills=required_skills,
                      required_parts=required_parts)
    hour_key = "clean_boots_hour" if crew == "dirty" and False else (
        "clean_boots_hour" if crew == "clean" else "dirty_boots_hour")

    ledger.add("dispatch planning", "dispatcher", DURATIONS["dispatch_planning"],
               _labour("dispatcher_hour", DURATIONS["dispatch_planning"]),
               f"staged from {sel.base.base_id}")

    travel = sel.plan.total_minutes * 2
    road_minutes = sum(l.minutes for l in sel.plan.legs if l.kind == "road") * 2
    vehicle = road_minutes * ROAD_KM_PER_MINUTE * RATES["vehicle_km"]
    ledger.add("travel", f"{crew} boots", travel,
               _labour(hour_key, travel) + vehicle,
               f"{sel.plan.total_minutes} min each way from {sel.base.name}")

    if sel.plan.requires_ferry:
        ledger.add("ferry", f"{crew} boots", 0, RATES["ferry_round_trip"],
                   "vehicle and cargo slot")
    if not sel.plan.same_day_feasible:
        ledger.add("overnight", f"{crew} boots", 0, RATES["overnight_premium"],
                   "round trip plus on-site work exceeds one shift")

    on_site = DURATIONS["clean_boots_on_site" if crew == "clean" else "dirty_boots_on_site"]
    ledger.add(f"{label or crew} boots on site", f"{crew} boots", on_site,
               _labour(hour_key, on_site))

    if parts_cost_key:
        ledger.add("parts", "inventory", 0, RATES[parts_cost_key], parts_cost_key)


def simulate_resolution(*, incident_id: str, site_id: str, technology: str,
                        true_domain: str, remote_attempts_failed: int = 0,
                        gate_raised: bool = False,
                        misdispatch: bool = False) -> EffortLedger:
    """Walk one incident to closure and record what it consumed.

    `remote_attempts_failed` bills each unsuccessful remote attempt before the
    lane changes. `misdispatch` bills a wasted visit by the wrong crew, followed
    by a handover and the correct visit, which is the false-negative path.
    """
    ledger = EffortLedger(incident_id, site_id)
    ledger.add("triage", "noc analyst", DURATIONS["triage"],
               _labour("noc_analyst_hour", DURATIONS["triage"]))
    ledger.add("rca", "noc analyst", DURATIONS["rca_cycle"],
               _labour("noc_analyst_hour", DURATIONS["rca_cycle"]))

    if gate_raised:
        ledger.add("gate review", "l2 sme", DURATIONS["gate_review"],
                   _labour("l2_sme_hour", DURATIONS["gate_review"]),
                   "human decision required before the lane opens")

    for attempt in range(remote_attempts_failed):
        ledger.add("remote attempt", "noc analyst", DURATIONS["remote_attempt"],
                   _labour("noc_analyst_hour", DURATIONS["remote_attempt"]),
                   f"attempt {attempt + 1}, unsuccessful")
        ledger.add("rca", "noc analyst", DURATIONS["rca_cycle"],
                   _labour("noc_analyst_hour", DURATIONS["rca_cycle"]),
                   "new evidence required before retry")

    crew_needed = "dirty" if true_domain in {"hfc_tap", "pon_odp", "plant",
                                             "shared_network"} else "clean"
    parts_key = {"hfc_tap": "parts_tap", "pon_odp": "parts_odp",
                 "drop": "parts_drop", "cpe": "parts_cpe"}.get(true_domain)

    if misdispatch:
        # The wasted visit: wrong crew, finds nothing in its domain.
        wrong = "clean" if crew_needed == "dirty" else "dirty"
        _visit(ledger, crew=wrong, site_id=site_id, label=f"{wrong} (wasted)")
        ledger.add("handover package", f"{wrong} boots", DURATIONS["handover_package"],
                   _labour("clean_boots_hour" if wrong == "clean" else "dirty_boots_hour",
                           DURATIONS["handover_package"]),
                   "evidence and exclusions for the receiving crew")
        ledger.add("handover review", "dispatcher", DURATIONS["handover_review"],
                   _labour("dispatcher_hour", DURATIONS["handover_review"]))

    if true_domain in {"cpe", "wifi_or_home", "provisioning"} and not misdispatch \
            and remote_attempts_failed == 0:
        ledger.add("remote fix", "noc analyst", DURATIONS["remote_attempt"],
                   _labour("noc_analyst_hour", DURATIONS["remote_attempt"]),
                   "resolved without dispatch")
    else:
        skills = ("fibre_splice",) if true_domain == "pon_odp" else ()
        parts = ("splice_kit",) if true_domain == "pon_odp" else ()
        _visit(ledger, crew=crew_needed, site_id=site_id, required_skills=skills,
               required_parts=parts, parts_cost_key=parts_key)

    ledger.add("verification", "noc analyst", DURATIONS["verification"],
               _labour("noc_analyst_hour", DURATIONS["verification"]))
    ledger.add("closure", "noc analyst", DURATIONS["closure"],
               _labour("noc_analyst_hour", DURATIONS["closure"]),
               f"blast radius {blast_radius(true_domain, site_id, technology)} household(s)")
    return ledger


# ------------------------------------------------------- false positive / negative
@dataclass(frozen=True, slots=True)
class ErrorCost:
    kind: Literal["false_positive", "false_negative"]
    minutes: int
    cost_usd: float
    detail: str


def false_positive_cost() -> ErrorCost:
    """A gate fired and the rules were right. An L2 review and a delay."""
    minutes = DURATIONS["gate_review"] + DURATIONS["dispatch_planning"]
    cost = (_labour("l2_sme_hour", DURATIONS["gate_review"])
            + _labour("dispatcher_hour", DURATIONS["dispatch_planning"]))
    return ErrorCost("false_positive", minutes, round(cost, 2),
                     "L2 review plus re-planning; the SLA clock keeps running")


def false_negative_cost(site_id: str, true_domain: str) -> ErrorCost:
    """No gate fired and the rules were wrong, so the wrong crew went out.

    The avoidable portion is the wasted visit plus the handover: what a correctly
    raised gate would have prevented. The correct visit still has to happen and is
    therefore not counted here.
    """
    site = SITE_BY_ID[site_id]
    needs_dirty = true_domain in {"hfc_tap", "pon_odp", "plant", "shared_network"}
    wrong = "clean" if needs_dirty else "dirty"
    hour_key = "clean_boots_hour" if wrong == "clean" else "dirty_boots_hour"

    sel = select_base(site, crew_type=wrong)
    travel = sel.plan.total_minutes * 2
    on_site = DURATIONS["clean_boots_on_site" if wrong == "clean"
                        else "dirty_boots_on_site"]
    road_minutes = sum(l.minutes for l in sel.plan.legs if l.kind == "road") * 2

    minutes = (DURATIONS["dispatch_planning"] + travel + on_site
               + DURATIONS["handover_package"] + DURATIONS["handover_review"])
    cost = (_labour("dispatcher_hour", DURATIONS["dispatch_planning"])
            + _labour(hour_key, travel + on_site + DURATIONS["handover_package"])
            + road_minutes * ROAD_KM_PER_MINUTE * RATES["vehicle_km"]
            + _labour("dispatcher_hour", DURATIONS["handover_review"]))
    if sel.plan.requires_ferry:
        cost += RATES["ferry_round_trip"]
    if not sel.plan.same_day_feasible:
        cost += RATES["overnight_premium"]

    return ErrorCost("false_negative", minutes, round(cost, 2),
                     f"wasted {wrong}-boots visit to {site.municipio} from "
                     f"{sel.base.base_id} plus handover; the correct visit still "
                     f"has to happen")


@dataclass(frozen=True, slots=True)
class ArmCost:
    arm: str
    false_positives: int
    false_negatives: int
    fp_minutes: int
    fp_cost: float
    fn_minutes: int
    fn_cost: float

    @property
    def total_minutes(self) -> int:
        return self.fp_minutes + self.fn_minutes

    @property
    def total_cost(self) -> float:
        return round(self.fp_cost + self.fn_cost, 2)


def cost_arm(arm: str, cases: Iterable[dict[str, object]]) -> ArmCost:
    """Aggregate the error cost of one A/B arm.

    Each case needs `gate_raised`, `rules_wrong`, `crew_would_differ`, `site_id`
    and `true_domain`.
    """
    fp = fn = 0
    fp_min = fn_min = 0
    fp_cost = fn_cost = 0.0
    for case in cases:
        gated = bool(case["gate_raised"])
        wrong = bool(case["rules_wrong"])
        if gated and not wrong:
            err = false_positive_cost()
            fp += 1; fp_min += err.minutes; fp_cost += err.cost_usd
        elif wrong and not gated and bool(case.get("crew_would_differ")):
            err = false_negative_cost(str(case["site_id"]), str(case["true_domain"]))
            fn += 1; fn_min += err.minutes; fn_cost += err.cost_usd
    return ArmCost(arm, fp, fn, fp_min, round(fp_cost, 2), fn_min, round(fn_cost, 2))
