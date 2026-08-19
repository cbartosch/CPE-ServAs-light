"""Commercial prioritisation: rank truck rolls by value at risk against cost.

The model, and why it is a product rather than a weighted sum
------------------------------------------------------------
A weighted sum of lifetime value, churn risk, contract status and payment status
is easy to write and hard to defend, because the weights are arbitrary and nothing
constrains them. What is defensible is the quantity a commercial decision actually
turns on:

    value at risk = LTV x P(churn | this fault goes unresolved)

Lifetime value is the exposure. The churn probability is what a dispatch buys back.
Contract and payment status enter through that probability rather than as free
weights, because that is how they operate: a customer twenty months into a
twenty-four month term cannot leave next week however annoyed they are, and one
already in arrears is both likelier to leave and likelier to leave owing money.

    net benefit = value at risk - cost of the truck roll

Ranking by net benefit is the operator's stated goal: prioritise where the gap
between weighted customer value and cost is largest.

The consequence that has to be measured, not assumed
----------------------------------------------------
Cost is dominated by geography. A visit in Bayamon is cheap and a visit to Culebra
involves a ferry and an overnight. So a pure net-benefit ranking will push island
and mountain customers down the queue systematically, not occasionally, and not
because of anything about those customers. `disparate_impact` computes it rather
than leaving it to be discovered in a complaint.

`PROTECTIONS` therefore override the ranking. Those are not decoration: without
them this is a system that leaves the hardest-to-reach customers unvisited and
records a commercial justification for it each time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal, Sequence

from .benchmarks import roll_cost
from .geography import SITE_BY_ID, select_base
from .plant import blast_radius

ContractStatus = Literal["in_term", "rolling", "expiring_soon", "out_of_term",
                         "pending_disconnect"]
PaymentStatus = Literal["current", "late", "arrears_30", "arrears_60",
                        "arrears_90_plus", "suspended"]
Segment = Literal["residential", "smb", "enterprise", "wholesale"]

# --------------------------------------------------------------- assumptions
# Every number below is ASSUMED. Churn multipliers are the sensitive ones: they
# decide who waits. Replace with LPR's own retention analytics.
CHURN_BASE_BY_SEGMENT: dict[str, float] = {
    "residential": 0.055, "smb": 0.038, "enterprise": 0.021, "wholesale": 0.012,
}

# How much an unresolved fault multiplies baseline churn propensity. A repeat
# unresolved fault is the single strongest driver in most retention models.
FAULT_CHURN_UPLIFT: dict[str, float] = {
    "first_fault": 2.1, "second_fault_90d": 3.4, "third_plus_90d": 5.2,
}

# Contract status scales the probability the customer CAN act on the intent.
CONTRACT_MOBILITY: dict[str, float] = {
    "in_term": 0.25,            # early termination fee bites
    "expiring_soon": 0.85,      # decision window is open
    "rolling": 1.00,            # can leave on notice
    "out_of_term": 1.10,        # already shopping
    "pending_disconnect": 1.40, # leaving unless something changes
}

# Payment status affects both churn propensity and how much of the LTV is
# collectable. Two separate effects, deliberately not merged: an arrears customer
# is likelier to leave AND worth less if they stay.
PAYMENT_CHURN_FACTOR: dict[str, float] = {
    "current": 1.00, "late": 1.15, "arrears_30": 1.35, "arrears_60": 1.55,
    "arrears_90_plus": 1.80, "suspended": 2.20,
}
PAYMENT_COLLECTABILITY: dict[str, float] = {
    "current": 1.00, "late": 0.97, "arrears_30": 0.88, "arrears_60": 0.74,
    "arrears_90_plus": 0.55, "suspended": 0.35,
}

ASSUMPTIONS_BASIS = (
    "churn baselines, fault uplift, contract mobility and collectability are "
    "ASSUMED. They decide who waits, so they are the first thing to replace with "
    "LPR retention and collections analytics"
)

# ------------------------------------------------------------------ guardrails
# Reasons that override the commercial ranking. A net-benefit queue with no floor
# leaves the most expensive-to-reach customers permanently unvisited.
# Protections are for what the commercial frame CANNOT express. Blast radius is
# not one of them: a fault behind a shared element is several accounts' value at
# risk, and the households multiplier in `rank` already expresses that. Granting
# it a protection as well double-counted it, and at realistic capacity the effect
# was severe — with 35% of candidates protected, a 40-slot day was filled entirely
# by protections and the commercial ranking never ran at all.
Protection = Literal["sla_breached", "total_loss_of_service", "medical_or_safety",
                     "regulatory_obligation", "vulnerable_customer",
                     "repeat_unresolved"]

PROTECTION_REASON: dict[str, str] = {
    "sla_breached": "the committed restoration time has passed",
    "total_loss_of_service": "the service is down, not degraded",
    "medical_or_safety": "a medical or safety dependency is recorded",
    "regulatory_obligation": "a regulatory or Lifeline obligation applies",
    "vulnerable_customer": "the account carries a vulnerability flag",
    "repeat_unresolved": "the same fault has recurred without resolution",
}

# Retained for reporting: above this many households a fault is a plant event, and
# the dashboard flags it. It is NOT a protection, because the value multiplier
# already carries it.
BLAST_RADIUS_PLANT_EVENT = 4


@dataclass(frozen=True, slots=True)
class CustomerRecord:
    """What the CRM and billing systems supply. See northbound.contracts."""

    account_id: str
    segment: Segment
    monthly_recurring_revenue: float
    tenure_months: int
    contract_status: ContractStatus
    contract_months_remaining: int
    payment_status: PaymentStatus
    balance_overdue: float = 0.0
    faults_in_last_90d: int = 0
    medical_or_safety_flag: bool = False
    vulnerable_flag: bool = False
    lifeline_subsidised: bool = False

    @property
    def expected_remaining_months(self) -> int:
        """Horizon over which lifetime value is counted.

        Contract term where one exists, because that is the period the customer is
        committed to; otherwise a churn-implied horizon from the segment baseline.
        """
        if self.contract_status == "in_term" and self.contract_months_remaining > 0:
            return max(self.contract_months_remaining, 6)
        implied = 1.0 / CHURN_BASE_BY_SEGMENT[self.segment]
        return int(min(implied, 60))

    @property
    def lifetime_value(self) -> float:
        """Gross lifetime value before collectability."""
        return round(self.monthly_recurring_revenue *
                     self.expected_remaining_months, 2)

    @property
    def collectable_value(self) -> float:
        return round(self.lifetime_value *
                     PAYMENT_COLLECTABILITY[self.payment_status], 2)


@dataclass(frozen=True, slots=True)
class ValueAtRisk:
    account_id: str
    lifetime_value: float
    collectable_value: float
    churn_probability: float
    value_at_risk: float
    components: dict[str, float] = field(default_factory=dict)


def churn_probability(customer: CustomerRecord) -> float:
    """P(churn | this fault goes unresolved), bounded to a probability."""
    base = CHURN_BASE_BY_SEGMENT[customer.segment]
    if customer.faults_in_last_90d >= 3:
        uplift = FAULT_CHURN_UPLIFT["third_plus_90d"]
    elif customer.faults_in_last_90d == 2:
        uplift = FAULT_CHURN_UPLIFT["second_fault_90d"]
    else:
        uplift = FAULT_CHURN_UPLIFT["first_fault"]
    mobility = CONTRACT_MOBILITY[customer.contract_status]
    payment = PAYMENT_CHURN_FACTOR[customer.payment_status]
    return round(min(base * uplift * mobility * payment, 0.95), 5)


def value_at_risk(customer: CustomerRecord) -> ValueAtRisk:
    probability = churn_probability(customer)
    collectable = customer.collectable_value
    return ValueAtRisk(
        account_id=customer.account_id,
        lifetime_value=customer.lifetime_value,
        collectable_value=collectable,
        churn_probability=probability,
        value_at_risk=round(collectable * probability, 2),
        components={
            "monthly_recurring_revenue": customer.monthly_recurring_revenue,
            "horizon_months": float(customer.expected_remaining_months),
            "collectability": PAYMENT_COLLECTABILITY[customer.payment_status],
            "contract_mobility": CONTRACT_MOBILITY[customer.contract_status],
            "payment_churn_factor": PAYMENT_CHURN_FACTOR[customer.payment_status],
        })


def truck_roll_cost(site_id: str, *, crew_type: str = "dirty",
                    destination: tuple[float, float] | None = None) -> float:
    """Cost of sending this crew to this customer, not an average.

    Uses the same travel model the effort ledger uses, so the number a
    prioritisation decision is made on is the number the dispatch will actually
    incur.
    """
    site = SITE_BY_ID[site_id]
    plan = select_base(site, crew_type=crew_type, destination=destination).plan
    # Technology affects the band; a site may carry both, in which case the more
    # expensive PON crew sets the cost, because that is what gets dispatched when
    # the fault is optical.
    technology = "PON" if "PON" in site.technologies else "HFC"
    band = roll_cost(site.archetype, technology)
    cost = band.per_dispatch_usd
    if plan.requires_ferry:
        cost *= 1.9                    # ferry, waiting and reduced productive hours
    if not plan.same_day_feasible:
        cost *= 1.35                   # an overnight, or a second day
    return round(cost, 2)


def protections_for(*, sla_breached: bool = False, service_down: bool = False,
                    households_affected: int = 1,
                    customer: CustomerRecord | None = None) -> tuple[str, ...]:
    """`households_affected` is accepted and deliberately unused: see Protection."""
    """Which overrides apply. Order is stable for reporting."""
    found: list[str] = []
    if sla_breached:
        found.append("sla_breached")
    if service_down:
        found.append("total_loss_of_service")
    if customer is not None:
        if customer.medical_or_safety_flag:
            found.append("medical_or_safety")
        if customer.lifeline_subsidised:
            found.append("regulatory_obligation")
        if customer.vulnerable_flag:
            found.append("vulnerable_customer")
        if customer.faults_in_last_90d >= 3:
            found.append("repeat_unresolved")
    return tuple(found)


@dataclass(frozen=True, slots=True)
class RankedDispatch:
    ticket_id: str
    account_id: str
    site_id: str
    archetype: str
    value: ValueAtRisk
    cost_usd: float
    households_affected: int
    protections: tuple[str, ...]
    band: str                       # protected | positive | marginal | negative

    @property
    def net_benefit(self) -> float:
        """The gap the operator asked to maximise."""
        return round(self.value.value_at_risk - self.cost_usd, 2)

    @property
    def benefit_ratio(self) -> float | None:
        """Return per dollar spent. None when the cost is zero, never infinity."""
        if self.cost_usd <= 0:
            return None
        return round(self.value.value_at_risk / self.cost_usd, 3)

    @property
    def rationale(self) -> str:
        if self.protections:
            reasons = "; ".join(PROTECTION_REASON[p] for p in self.protections)
            return f"Protected ahead of commercial ranking: {reasons}"
        return (f"Value at risk ${self.value.value_at_risk:,.0f} against a "
                f"${self.cost_usd:,.0f} dispatch, a gap of "
                f"${self.net_benefit:,.0f}")


def _band(net: float, protections: Sequence[str]) -> str:
    if protections:
        return "protected"
    if net > 250:
        return "positive"
    if net >= 0:
        return "marginal"
    return "negative"


def rank(candidates: Iterable[tuple[str, CustomerRecord, str, dict]]
         ) -> list[RankedDispatch]:
    """Rank dispatch candidates by net benefit, protections first.

    Each candidate is `(ticket_id, customer, site_id, context)` where context may
    carry `sla_breached`, `service_down`, `households_affected`, `crew_type` and
    `destination`.

    Protected candidates are ordered ahead of every commercial one and ranked among
    themselves by net benefit, so a protection guarantees attention without
    discarding the economics entirely.
    """
    ranked: list[RankedDispatch] = []
    for ticket_id, customer, site_id, context in candidates:
        households = int(context.get("households_affected", 1))
        protections = protections_for(
            sla_breached=bool(context.get("sla_breached")),
            service_down=bool(context.get("service_down")),
            households_affected=households, customer=customer)
        cost = truck_roll_cost(site_id,
                               crew_type=context.get("crew_type", "dirty"),
                               destination=context.get("destination"))
        risk = value_at_risk(customer)
        # A fault behind a shared element puts several accounts at risk, so
        # single-account value understates it. The multiplier is the ONLY mechanism
        # for this; granting a protection as well double-counted it.
        if households > 1:
            risk = ValueAtRisk(risk.account_id, risk.lifetime_value,
                               risk.collectable_value, risk.churn_probability,
                               round(risk.value_at_risk * households, 2),
                               dict(risk.components,
                                    households_multiplier=float(households)))
        net = risk.value_at_risk - cost
        ranked.append(RankedDispatch(
            ticket_id=ticket_id, account_id=customer.account_id, site_id=site_id,
            archetype=SITE_BY_ID[site_id].archetype, value=risk, cost_usd=cost,
            households_affected=households, protections=protections,
            band=_band(net, protections)))

    return sorted(ranked, key=lambda r: (0 if r.protections else 1,
                                         -r.net_benefit, r.ticket_id))


# ------------------------------------------------------- the measured downside
def disparate_impact(ranked: Sequence[RankedDispatch]) -> dict[str, object]:
    """Which archetypes the commercial ranking pushes down the queue.

    Computed rather than assumed, because cost is dominated by geography and a
    net-benefit queue therefore deprioritises island and mountain customers
    structurally, not occasionally. An operator deploying this needs the number,
    and a regulator will ask for it.
    """
    commercial = [r for r in ranked if not r.protections]
    if not commercial:
        return {"ranked": len(ranked), "commercial": 0,
                "note": "every candidate was protected, so no commercial ordering "
                        "was applied"}

    total = len(commercial)
    quartile = max(total // 4, 1)
    top = commercial[:quartile]
    bottom = commercial[-quartile:]

    def share(rows: Sequence[RankedDispatch]) -> dict[str, float]:
        counts: dict[str, int] = {}
        for row in rows:
            counts[row.archetype] = counts.get(row.archetype, 0) + 1
        return {k: round(v / len(rows), 3) for k, v in sorted(counts.items())}

    overall = share(commercial)
    top_share, bottom_share = share(top), share(bottom)
    skew = {}
    for archetype in overall:
        skew[archetype] = round(bottom_share.get(archetype, 0.0)
                                - top_share.get(archetype, 0.0), 3)

    negative = [r for r in commercial if r.net_benefit < 0]
    never_by_archetype: dict[str, int] = {}
    for row in negative:
        never_by_archetype[row.archetype] = never_by_archetype.get(
            row.archetype, 0) + 1

    worst = max(skew.items(), key=lambda kv: kv[1]) if skew else ("n/a", 0.0)
    return {
        "ranked": len(ranked), "commercial": total, "protected": len(ranked) - total,
        "quartile_size": quartile,
        "overall_share": overall,
        "top_quartile_share": top_share,
        "bottom_quartile_share": bottom_share,
        "bottom_minus_top": skew,
        "most_deprioritised_archetype": worst[0],
        "most_deprioritised_skew": worst[1],
        "negative_net_benefit": len(negative),
        "negative_by_archetype": never_by_archetype,
        "warning": ("A negative net benefit means the commercial case says do not "
                    "visit. Without a protection floor those customers are never "
                    "dispatched to, and the reason recorded each time is "
                    "commercial."),
    }


# --------------------------------------------------- ordering, not a threshold
@dataclass(frozen=True, slots=True)
class CapacityPlan:
    slots: int
    scheduled: tuple[RankedDispatch, ...]
    deferred: tuple[RankedDispatch, ...]
    protected_scheduled: int
    value_at_risk_addressed: float
    cost_committed: float
    protected_total: int = 0

    @property
    def commercial_scheduled(self) -> int:
        return len(self.scheduled) - self.protected_scheduled

    @property
    def slots_before_commercial_ranking_bites(self) -> int:
        """Capacity at which an unprotected ticket first gets a slot.

        The number worth taking to a capacity conversation. Measured on a
        household-weighted population of 600 faults, 136 were protected, so a
        40-slot day is filled entirely by protections and no unprotected ticket is
        visited at all. Value still orders the protected band, so the ranking is not
        inert; but no amount of commercial tuning changes the schedule until
        capacity passes this number.
        """
        return self.protected_total

    @property
    def commercial_ranking_active(self) -> bool:
        return self.slots > self.protected_total

    @property
    def deferred_value_at_risk(self) -> float:
        return round(sum(r.value.value_at_risk for r in self.deferred), 2)


def allocate_capacity(ranked: Sequence[RankedDispatch], *, slots: int) -> CapacityPlan:
    """Allocate a fixed number of crew slots down the ranking.

    THIS IS THE CORRECT USE OF NET BENEFIT, AND THE ONLY ONE.

    Measured on a household-weighted population of 1,200 faults, **87% of
    commercially ranked candidates have a NEGATIVE net benefit**: a single
    residential account's value at risk is usually 20 to 150 dollars while a truck
    roll is 212 to 654. Used as a go/no-go threshold, "dispatch when the gap is
    positive" would decline most residential repairs, which is neither lawful nor
    survivable.

    The gap is a way of ordering a queue that is shorter than the demand for it. It
    is not a test of whether a fault deserves fixing. Field capacity is the scarce
    resource; the ranking says which faults get today's slots and which wait for
    tomorrow's, not which are abandoned.
    """
    if slots < 0:
        raise ValueError("slots must be >= 0")
    scheduled = tuple(ranked[:slots])
    deferred = tuple(ranked[slots:])
    return CapacityPlan(
        slots=slots, scheduled=scheduled, deferred=deferred,
        protected_scheduled=sum(1 for r in scheduled if r.protections),
        value_at_risk_addressed=round(
            sum(r.value.value_at_risk for r in scheduled), 2),
        cost_committed=round(sum(r.cost_usd for r in scheduled), 2),
        protected_total=sum(1 for r in ranked if r.protections))


def threshold_would_decline(ranked: Sequence[RankedDispatch]) -> dict[str, object]:
    """What a positive-gap threshold would refuse, if anyone tried to use one.

    Provided so the argument against a threshold can be made with the operator's
    own data rather than in the abstract.
    """
    commercial = [r for r in ranked if not r.protections]
    declined = [r for r in commercial if r.net_benefit < 0]
    by_archetype: dict[str, int] = {}
    for row in declined:
        by_archetype[row.archetype] = by_archetype.get(row.archetype, 0) + 1
    return {
        "commercial_candidates": len(commercial),
        "would_be_declined": len(declined),
        "declined_share": (round(len(declined) / len(commercial), 3)
                           if commercial else None),
        "declined_by_archetype": by_archetype,
        "value_at_risk_abandoned": round(
            sum(r.value.value_at_risk for r in declined), 2),
        "verdict": ("A positive-gap threshold declines the majority of residential "
                    "repairs. Net benefit orders a capacity-constrained queue; it "
                    "does not decide whether a fault deserves a visit."),
    }


def assumptions() -> dict[str, object]:
    return {
        "churn_base_by_segment": dict(CHURN_BASE_BY_SEGMENT),
        "fault_churn_uplift": dict(FAULT_CHURN_UPLIFT),
        "contract_mobility": dict(CONTRACT_MOBILITY),
        "payment_churn_factor": dict(PAYMENT_CHURN_FACTOR),
        "payment_collectability": dict(PAYMENT_COLLECTABILITY),
        "blast_radius_plant_event": BLAST_RADIUS_PLANT_EVENT,
        "protections": sorted(PROTECTION_REASON),
        "basis": ASSUMPTIONS_BASIS,
    }


# ============================================================================
# The recommended rule
# ============================================================================
#
# Ranking by net benefit per VISIT was the operator's stated goal and it has three
# measured problems, all of which this rule addresses:
#
#   1. 78 to 87% of gaps are negative, so the difference cannot gate anything.
#   2. Protections-first is lexicographic, so 136 protected tickets consumed a
#      40-slot day entirely and the commercial ranking never ran.
#   3. Cost is geography, so islands sit at the bottom structurally.
#
# The rule below is a value-density scheduling rule with deadlines, which is the
# standard answer to exactly this shape of problem. Three changes carry the weight:
#
# **Divide by crew-hours, not by visits.** A Culebra visit consumes 11 crew-hours
# and a Bayamon visit 2.7. Treating them as equal claims on capacity is the single
# largest error in the per-visit rule. Under a capacity constraint the quantity to
# maximise is value per unit of the scarce resource, which makes this a ratio rather
# than a difference.
#
# **Protections become deadlines, not queue jumps.** A medical dependency does not
# mean "before everything else forever"; it means "within four hours". Expressing it
# as a deadline lets the urgency term elevate it as slack shrinks, which is what
# stops 23% of the queue from swallowing every slot.
#
# **Batch the remote runs.** One Culebra ticket cannot pay for a ferry. Six can, at
# roughly a sixth of the cost each. Holding remote tickets until a batch forms, or
# until the oldest reaches its deadline, converts a structural exclusion into a
# scheduled cadence. That is what operators actually do, and it fixes the skew at
# source rather than compensating for it.

ON_SITE_MINUTES_BY_DOMAIN: dict[str, int] = {
    "cpe": 45, "wifi_or_home": 60, "premise_wiring": 90, "provisioning": 30,
    "drop": 75, "hfc_tap": 120, "pon_odp": 135, "plant": 180,
    "shared_network": 180, "unknown": 90,
}
SHIFT_HOURS = 9.5

# Deadline by protection class, in hours from when the fault was raised. These are
# ASSUMED and are the policy dial an operator actually wants to turn: they encode
# how long each class may wait, which is a commitment, not a calculation.
DEADLINE_HOURS: dict[str, float] = {
    "medical_or_safety": 4.0,
    "sla_breached": 0.0,              # already past it
    "total_loss_of_service": 12.0,
    "regulatory_obligation": 24.0,
    "vulnerable_customer": 24.0,
    "repeat_unresolved": 36.0,
}
DEFAULT_DEADLINE_HOURS = 72.0

# How hard an approaching deadline pulls a ticket forward. At slack zero the
# multiplier is URGENCY_AT_DEADLINE; it decays towards 1.0 as slack grows.
URGENCY_AT_DEADLINE = 12.0
URGENCY_HALF_LIFE_HOURS = 18.0

# Remote batching. Below MIN_REMOTE_BATCH a remote run is held unless something in
# it is within FORCE_RUN_HOURS of its deadline.
MIN_REMOTE_BATCH = 4
FORCE_RUN_HOURS = 18.0


def crew_hours(site_id: str, domain: str, *, crew_type: str = "dirty",
               destination: tuple[float, float] | None = None) -> float:
    """Crew time consumed by one visit: round trip plus on-site work.

    A trip that cannot be completed and returned within a shift consumes the whole
    shift, because the crew is unavailable for anything else that day.
    """
    site = SITE_BY_ID[site_id]
    plan = select_base(site, crew_type=crew_type, destination=destination).plan
    on_site = ON_SITE_MINUTES_BY_DOMAIN.get(domain, 90)
    hours = (plan.total_minutes * 2 + on_site) / 60.0
    if not plan.same_day_feasible:
        hours = max(hours, SHIFT_HOURS)
    return round(hours, 2)


def deadline_hours_for(protections: Sequence[str]) -> float:
    """The strictest deadline any applicable protection imposes."""
    if not protections:
        return DEFAULT_DEADLINE_HOURS
    return min(DEADLINE_HOURS.get(p, DEFAULT_DEADLINE_HOURS) for p in protections)


def urgency(age_hours: float, deadline_hours: float) -> float:
    """Multiplier rising as slack to the deadline shrinks.

    Past the deadline the multiplier is capped rather than unbounded: an overdue
    ticket should go first, but an ancient one must not be able to justify a whole
    week of capacity on its own.
    """
    slack = deadline_hours - age_hours
    if slack <= 0:
        return URGENCY_AT_DEADLINE
    decay = 0.5 ** (slack / URGENCY_HALF_LIFE_HOURS)
    return round(1.0 + (URGENCY_AT_DEADLINE - 1.0) * decay, 4)


def aged_value_at_risk(base: ValueAtRisk, age_hours: float) -> float:
    """Value at risk grows while a fault waits, because churn propensity does.

    This is what prevents starvation without needing a quota. A low-value ticket
    that keeps being deferred rises until it outranks a high-value one that has just
    arrived, and it does so through the model rather than through an override.
    """
    days = max(age_hours, 0.0) / 24.0
    growth = min(1.0 + 0.18 * days, 2.5)
    return round(base.value_at_risk * growth, 2)


@dataclass(frozen=True, slots=True)
class Job:
    ticket_id: str
    dispatch: RankedDispatch
    domain: str
    age_hours: float
    crew_hours: float
    deadline_hours: float

    @property
    def urgency(self) -> float:
        return urgency(self.age_hours, self.deadline_hours)

    @property
    def aged_value(self) -> float:
        return aged_value_at_risk(self.dispatch.value, self.age_hours)

    @property
    def overdue(self) -> bool:
        return self.age_hours >= self.deadline_hours

    @property
    def score(self) -> float:
        """Value per crew-hour, weighted by urgency. Higher is sooner."""
        if self.crew_hours <= 0:
            return 0.0
        return round(self.aged_value * self.urgency / self.crew_hours, 3)

    @property
    def remote(self) -> bool:
        return SITE_BY_ID[self.dispatch.site_id].archetype == "remote_island"


def build_jobs(ranked: Sequence[RankedDispatch], *,
               domains: dict[str, str] | None = None,
               ages: dict[str, float] | None = None) -> list[Job]:
    domain_map = domains or {}
    age_map = ages or {}
    jobs = []
    for row in ranked:
        domain = domain_map.get(row.ticket_id, "unknown")
        age = age_map.get(row.ticket_id, 0.0)
        deadline = deadline_hours_for(row.protections)
        jobs.append(Job(row.ticket_id, row, domain, age,
                        crew_hours(row.site_id, domain,
                                   crew_type=("dirty" if domain in
                                              {"hfc_tap", "pon_odp", "plant",
                                               "shared_network"} else "clean")),
                        deadline))
    return jobs


@dataclass(frozen=True, slots=True)
class DaySchedule:
    crew_hours_available: float
    scheduled: tuple[Job, ...]
    deferred: tuple[Job, ...]
    held_remote: tuple[Job, ...]
    hours_used: float
    value_addressed: float

    @property
    def value_per_crew_hour(self) -> float:
        return round(self.value_addressed / self.hours_used, 2) if self.hours_used else 0.0

    @property
    def overdue_scheduled(self) -> int:
        return sum(1 for j in self.scheduled if j.overdue)

    @property
    def overdue_deferred(self) -> int:
        return sum(1 for j in self.deferred if j.overdue)


def schedule_day(jobs: Sequence[Job], *, crew_hours_available: float,
                 batch_remote: bool = True) -> DaySchedule:
    """Fill a day's crew-hours by value density, deadlines first.

    Ordering, in one lexicographic step and then one continuous one:

      1. Overdue jobs, by score. This is the ONLY hard precedence, and it is
         bounded: a job is overdue or it is not.
      2. Everything else by score, which is aged value times urgency per crew-hour.

    Remote jobs are held back unless the run is worth making. Batching is what turns
    a $654 island visit into roughly $150 a ticket, and it is the difference between
    an island customer being served on a cadence and never being served at all.
    """
    if crew_hours_available < 0:
        raise ValueError("crew_hours_available must be >= 0")

    remote = [j for j in jobs if j.remote]
    mainland = [j for j in jobs if not j.remote]
    held: list[Job] = []

    if batch_remote and remote:
        forced = any(j.deadline_hours - j.age_hours <= FORCE_RUN_HOURS
                     for j in remote)
        if len(remote) < MIN_REMOTE_BATCH and not forced:
            held = remote
            remote = []

    candidates = mainland + remote
    candidates.sort(key=lambda j: (0 if j.overdue else 1, -j.score, j.ticket_id))

    scheduled: list[Job] = []
    deferred: list[Job] = []
    remaining = crew_hours_available
    for job in candidates:
        if job.crew_hours <= remaining:
            scheduled.append(job)
            remaining -= job.crew_hours
        else:
            deferred.append(job)

    return DaySchedule(
        crew_hours_available=crew_hours_available,
        scheduled=tuple(scheduled), deferred=tuple(deferred),
        held_remote=tuple(held),
        hours_used=round(crew_hours_available - remaining, 2),
        value_addressed=round(sum(j.aged_value for j in scheduled), 2))


def rule_description() -> str:
    return (
        "Schedule a day's crew-hours in descending order of\n"
        "\n"
        "    score = aged value at risk x urgency / crew-hours consumed\n"
        "\n"
        "with overdue jobs taken first, remote work batched into runs, and every\n"
        "protection expressed as a deadline rather than as a place in the queue."
    )
