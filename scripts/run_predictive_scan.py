#!/usr/bin/env python3
"""Run one daily predictive modem scan.

    PYTHONPATH=src python3 scripts/run_predictive_scan.py
    PYTHONPATH=src python3 scripts/run_predictive_scan.py --population 50000 --detail
    PYTHONPATH=src python3 scripts/run_predictive_scan.py --hour 14   # outside the window
    PYTHONPATH=src python3 scripts/run_predictive_scan.py --days 3    # three runs, repeat offenders build

This is the separate branch of the stack. It scans, auto-remediates, gates, and
hands the gated tickets to the main flow as `IncidentSeed` records. It does not
schedule itself: a cron entry, a Kubernetes CronJob or a compose service with a
sleep loop calls this, so the timing lives in configuration rather than in code.

Every threshold, rate and window is assumed. `--assumptions` prints them.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpr_cpe_demo.predictive.config import DEFAULT_SCAN, ScanConfig, assumptions  # noqa: E402
from lpr_cpe_demo.predictive.handoff import attach_customer_call, apply_merge  # noqa: E402
from lpr_cpe_demo.predictive.service import FlagHistory, RunReport, run_once  # noqa: E402


def print_run(report: RunReport, *, detail: bool) -> None:
    s = report.summary()
    print(f"\nRun {s['run_id']} at {s['ran_at']}")
    if s.get("suppressed_as_duplicate"):
        print(f"  {s['suppressed_as_duplicate']} finding(s) suppressed: a ticket is "
              f"already open for that modem")
    print(f"  scanned {s['scanned']:,}   healthy {s['healthy']:,}   "
          f"tickets {s['tickets']}   flag rate {s['flag_rate']:.2%}")
    if s["suppressed_by_cap"]:
        print(f"  {s['suppressed_by_cap']} ticket(s) suppressed by the per-run cap, "
              f"least urgent first")
    print(f"  classes: {s['by_class']}")
    print(f"\n  auto-remediation")
    print(f"    closed with no human      {s['auto_closed']:>5}  "
          f"({s['auto_close_rate']:.0%})")
    print(f"    handed to a human         {s['gated']:>5}")
    print(f"    truck roll needed         {s['truck_rolls']:>5}")
    print(f"    customer notification     {s['notifications']:>5}")
    print(f"    service interruption      {s['service_interruption_minutes']:>5} min "
          f"total, from reboots inside the window")

    gates = Counter(r for o in report.outcomes for r in o.gate_reasons)
    notes = Counter(r for o in report.outcomes for r in o.notify_reasons)
    print(f"\n  gate reasons      {dict(gates)}")
    print(f"  notify reasons    {dict(notes)}")

    if detail and report.seeds:
        print(f"\n  handed to the main flow, first 8 of {len(report.seeds)}:")
        for seed in report.seeds[:8]:
            print(f"    {seed.incident_id}")
            print(f"      {seed.predictive_class:9s} {seed.severity:8s} "
                  f"{seed.technology}  domain={seed.suspected_domain}  "
                  f"truck_roll={seed.needs_truck_roll}")
            print(f"      gate={list(seed.gate_reasons)}  "
                  f"notify={list(seed.notify_reasons)}")
            print(f"      {seed.evidence[0]['summary']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--population", type=int, default=DEFAULT_SCAN.population)
    ap.add_argument("--hour", type=int, default=DEFAULT_SCAN.scan_hour_local,
                    help="hour of the run; outside the maintenance window reboots defer")
    ap.add_argument("--days", type=int, default=1,
                    help="consecutive daily runs, so repeat offenders accumulate")
    ap.add_argument("--seed", type=int, default=20260818)
    ap.add_argument("--history", default="", help="path to persist flag history")
    ap.add_argument("--detail", action="store_true")
    ap.add_argument("--json", metavar="PATH")
    ap.add_argument("--backlog", action="store_true",
                    help="first run after deployment: scan a population that has "
                         "been degrading unobserved, rather than the daily inflow")
    ap.add_argument("--assumptions", action="store_true")
    args = ap.parse_args()

    if args.assumptions:
        print(json.dumps(assumptions(), indent=2))
        return 0

    config = ScanConfig(population=args.population, scan_hour_local=args.hour)
    history = FlagHistory(path=pathlib.Path(args.history) if args.history else None).load()

    start = datetime(2026, 8, 18, args.hour, tzinfo=timezone.utc)
    # Two different questions. The steady state is the daily inflow and tells you
    # the standing workload. The backlog is the first run after deployment, when
    # every modem that has been quietly degrading surfaces at once, and it tells you
    # the capacity the launch needs. They differ by more than an order of magnitude.
    base_day = 60 if args.backlog else 0
    reports = []
    for day in range(args.days):
        report = run_once(ran_at=start + timedelta(days=day), history=history,
                          scan_config=config, rng_seed=args.seed,
                          day_index=base_day + day)
        reports.append(report)
        print_run(report, detail=args.detail and day == args.days - 1)

    if args.days > 1:
        print("\nAcross the run window")
        print(f"  repeat offenders by day: "
              f"{[sum(1 for t in r.scan.tickets if t.repeat_offender) for r in reports]}")
        print(f"  notifications by day:    {[r.notifications for r in reports]}")
        print("  Repeat status is a notification trigger, so it grows as history "
              "accumulates. That is the intended behaviour, not drift.")

    # Show the merge rule on one real seed.
    last = reports[-1]
    if last.seeds:
        seed = last.seeds[0]
        called = seed.opened_at + timedelta(hours=30)
        decision = attach_customer_call(seed, reactive_incident_id="INC-CALL-DEMO",
                                        called_at=called)
        child = apply_merge(seed, decision)
        print(f"\nMerge rule, applied to {seed.incident_id}")
        print(f"  a customer calls {decision.hours_of_clock_already_spent:.0f}h after "
              f"the scan opened it")
        print(f"  parent stays {decision.parent_incident_id}, "
              f"child {child.incident_id} attaches")
        print(f"  SLA inherited from the parent, due {decision.sla_due_at.isoformat()}")
        print(f"  already breached at attach: {decision.sla_breached_at_attach}")
        print(f"  {decision.rationale}")

    print(f"\nEvery threshold, success rate and window above is ASSUMED. "
          f"Run with --assumptions to print them.")

    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(
            {"runs": [r.summary() for r in reports],
             "seeds": [s.to_dict() for s in reports[-1].seeds],
             "assumptions": assumptions()}, indent=2, default=str) + "\n")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
