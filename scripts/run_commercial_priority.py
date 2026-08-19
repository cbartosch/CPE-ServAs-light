#!/usr/bin/env python3
"""Rank a day's dispatch queue by value at risk against cost.

    PYTHONPATH=src python3 scripts/run_commercial_priority.py
    PYTHONPATH=src python3 scripts/run_commercial_priority.py --slots 200
    PYTHONPATH=src python3 scripts/run_commercial_priority.py --assumptions

Three findings came out of measuring this rather than designing it, and all three
change what the ranking does. They are printed with the ranking, not buried.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpr_cpe_demo.commercial import (CustomerRecord, allocate_capacity,  # noqa: E402
                                     assumptions, build_jobs, crew_hours,
                                     disparate_impact, rank, rule_description,
                                     schedule_day, schedule_disparate_impact,
                                     threshold_would_decline)
from lpr_cpe_demo.geography import sites_in_cpe_footprint  # noqa: E402
from lpr_cpe_demo.plant import households  # noqa: E402


def population(count: int, seed: int):
    rng = random.Random(seed)
    sites = list(sites_in_cpe_footprint())
    weights = [households(s) for s in sites]
    out = []
    for index in range(count):
        site = rng.choices(sites, weights=weights, k=1)[0]
        segment = rng.choices(["residential", "smb", "enterprise"], [86, 11, 3])[0]
        mrr = {"residential": rng.uniform(35, 110), "smb": rng.uniform(120, 380),
               "enterprise": rng.uniform(350, 1400)}[segment]
        status = rng.choice(["in_term", "in_term", "rolling", "expiring_soon",
                             "out_of_term"])
        out.append((f"T{index:05d}", CustomerRecord(
            account_id=f"ACC-{index:06d}", segment=segment,
            monthly_recurring_revenue=round(mrr, 2),
            tenure_months=rng.randint(2, 96), contract_status=status,
            contract_months_remaining=rng.randint(1, 23) if status == "in_term" else 0,
            payment_status=rng.choices(
                ["current", "late", "arrears_30", "arrears_60", "arrears_90_plus"],
                [75, 10, 7, 5, 3])[0],
            faults_in_last_90d=rng.choices([0, 1, 2, 3], [70, 20, 7, 3])[0],
            medical_or_safety_flag=rng.random() < 0.008,
            vulnerable_flag=rng.random() < 0.02,
            lifeline_subsidised=rng.random() < 0.06), site.site_id,
            {"households_affected": rng.choices([1, 4, 6, 8], [85, 7, 5, 3])[0],
             "sla_breached": rng.random() < 0.04,
             "service_down": rng.random() < 0.09,
             "domain": rng.choice(["cpe", "wifi_or_home", "drop", "hfc_tap",
                                   "pon_odp", "provisioning"])}))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--faults", type=int, default=600)
    ap.add_argument("--slots", type=int, default=40,
                    help="legacy per-visit rule, for comparison only")
    ap.add_argument("--crew-hours", type=float, default=110.0,
                    help="capacity for the recommended rule; the real unit")
    ap.add_argument("--compare", action="store_true",
                    help="run both rules on the same queue")
    ap.add_argument("--seed", type=int, default=20260818)
    ap.add_argument("--assumptions", action="store_true")
    ap.add_argument("--json", metavar="PATH")
    args = ap.parse_args()

    if args.assumptions:
        print(json.dumps(assumptions(), indent=2))
        return 0

    pool = population(args.faults, args.seed)
    domains = {ticket: ctx.get("domain", "unknown")
               for ticket, _customer, _site, ctx in pool}
    ranked = rank([(t_, c, s, ctx) for t_, c, s, ctx in pool])

    # The recommended rule. See docs/DISPATCH_RULE.md.
    jobs = build_jobs(ranked, domains=domains)
    day = schedule_day(jobs, crew_hours_available=args.crew_hours)
    fairness = schedule_disparate_impact(day)

    print(rule_description())
    print(f"\n{args.faults} faults, {args.crew_hours:.0f} crew-hours available\n")
    print(f"  scheduled                {len(day.scheduled):>6}")
    print(f"    absolute precedence    {fairness['absolute_precedence_served']:>6}")
    print(f"  crew-hours used          {day.hours_used:>6.1f}")
    print(f"  value at risk addressed  ${day.value_addressed:>12,.0f}")
    print(f"  value per crew-hour      ${day.value_per_crew_hour:>12,.0f}")
    print(f"  overdue left unscheduled {day.overdue_deferred:>6}   "
          f"<- a capacity signal, not a prioritisation one")
    print(f"  remote runs held         {len(day.held_remote):>6}")
    print("\n  worst wait by archetype, which IS the fairness measure:")
    for archetype, hours in sorted(fairness["worst_wait_hours_by_archetype"].items()):
        print(f"    {archetype:16s} {hours/24:>5.1f} days")

    if not args.compare:
        print("\n  Every churn, mobility, collectability and deadline figure is "
              "ASSUMED. Run with --assumptions.\n")
        if args.json:
            pathlib.Path(args.json).write_text(json.dumps(
                {"rule": "value_density", "crew_hours": args.crew_hours,
                 "scheduled": len(day.scheduled),
                 "value_addressed": day.value_addressed,
                 "value_per_crew_hour": day.value_per_crew_hour,
                 "overdue_deferred": day.overdue_deferred,
                 "fairness": fairness, "assumptions": assumptions()},
                indent=2, default=str) + "\n")
            print(f"wrote {args.json}")
        return 0

    print("\n  --- comparison with the per-visit rule it replaces ---")
    plan = allocate_capacity(ranked, slots=args.slots)
    impact = disparate_impact(ranked)
    threshold = threshold_would_decline(ranked)

    pv_hours = sum(crew_hours(r.site_id, domains.get(r.ticket_id, "unknown"))
                   for r in plan.scheduled) or 1.0
    print(f"\n  per-visit rule at {args.slots} slots\n")
    print(f"  scheduled              {len(plan.scheduled):>6}")
    print(f"    of which protected   {plan.protected_scheduled:>6}")
    print(f"    ranked commercially  {plan.commercial_scheduled:>6}")
    print(f"  deferred to tomorrow   {len(plan.deferred):>6}")
    print(f"\n  value at risk addressed  ${plan.value_at_risk_addressed:>12,.0f}")
    print(f"  cost committed           ${plan.cost_committed:>12,.0f}")
    if plan.cost_committed:
        print(f"  return on the day        {plan.value_at_risk_addressed/plan.cost_committed:>12.2f}x")
    print(f"  value at risk deferred   ${plan.deferred_value_at_risk:>12,.0f}")

    print("\n  THE SCHEDULE, first 12")
    print(f"    {'':>10s} {'archetype':14s} {'hh':>3s} {'at risk':>10s} "
          f"{'cost':>8s} {'gap':>10s}")
    for row in plan.scheduled[:12]:
        tag = "PROTECTED" if row.protections else ""
        print(f"    {tag:>10s} {row.archetype:14s} {row.households_affected:>3} "
              f"${row.value.value_at_risk:>9,.0f} ${row.cost_usd:>7,.0f} "
              f"${row.net_benefit:>9,.0f}")

    print("\n  FINDING 1  the gap is an ordering, not a threshold")
    print(f"    a positive-gap rule would decline {threshold['would_be_declined']} of "
          f"{threshold['commercial_candidates']} "
          f"({threshold['declined_share']:.0%}), abandoning "
          f"${threshold['value_at_risk_abandoned']:,.0f} of value at risk")
    print(f"    a single residential account is worth $20 to $150 at risk against a "
          f"$212 to $654 visit")

    print("\n  FINDING 2  protections exceed a day's capacity")
    print(f"    {plan.slots_before_commercial_ranking_bites} of {len(ranked)} "
          f"candidates are protected, so commercial ranking only changes the "
          f"schedule above {plan.slots_before_commercial_ranking_bites} slots")
    print(f"    at {args.slots} slots the commercial ranking is "
          f"{'ACTIVE' if plan.commercial_ranking_active else 'INERT for scheduling, '
             'though value still orders the protected band'}")

    print("\n  FINDING 3  cost is geography, so the ranking skews")
    for archetype, skew in sorted(impact["bottom_minus_top"].items(),
                                  key=lambda kv: -kv[1]):
        direction = "deprioritised" if skew > 0 else "favoured"
        print(f"    {archetype:16s} {skew:+7.1%}  {direction}")
    print(f"    islands reach "
          f"{impact['top_quartile_share'].get('remote_island', 0.0):.1%} of the top "
          f"quartile and {impact['bottom_quartile_share'].get('remote_island', 0.0):.1%} "
          f"of the bottom")

    print(f"\n  value per crew-hour: per-visit ${plan.value_at_risk_addressed/pv_hours:,.0f} "
          f"against value-density ${day.value_per_crew_hour:,.0f}")
    print("\n  Every churn, mobility, collectability and deadline figure is ASSUMED. "
          "Run with --assumptions.\n")

    if args.json:
        pathlib.Path(args.json).write_text(json.dumps({
            "plan": {"slots": plan.slots, "scheduled": len(plan.scheduled),
                     "protected_scheduled": plan.protected_scheduled,
                     "commercial_scheduled": plan.commercial_scheduled,
                     "value_at_risk_addressed": plan.value_at_risk_addressed,
                     "cost_committed": plan.cost_committed,
                     "break_even_slots": plan.slots_before_commercial_ranking_bites},
            "threshold_would_decline": threshold,
            "disparate_impact": impact,
            "assumptions": assumptions()}, indent=2, default=str) + "\n")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
