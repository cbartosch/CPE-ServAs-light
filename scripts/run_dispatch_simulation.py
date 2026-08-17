#!/usr/bin/env python3
"""Walk each scenario to closure and report time, cost and plant affected.

    PYTHONPATH=src python3 scripts/run_dispatch_simulation.py
    PYTHONPATH=src python3 scripts/run_dispatch_simulation.py --detail INC-1003
    PYTHONPATH=src python3 scripts/run_dispatch_simulation.py --json out.json

Three columns per scenario answer the question this exists for:

  resolved    what it costs when the lane chosen first is the right one
  +2 remote   what two failed remote attempts add before the lane changes
  misdispatch what a missed gate adds: a wasted visit by the wrong crew, a
              handover, and then the correct visit

Every rate and duration is assumed. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpr_cpe_demo.effort import (assumptions, false_negative_cost,  # noqa: E402
                                 false_positive_cost, simulate_resolution)
from lpr_cpe_demo.geography import SITE_BY_ID, select_base  # noqa: E402
from lpr_cpe_demo.plant import blast_radius, chain_for, delimiter_for  # noqa: E402

FIXTURES = ROOT / "src/lpr_cpe_demo/fixtures"


def load() -> list[dict]:
    out = []
    for path in sorted(FIXTURES.glob("*.json")):
        data = json.loads(path.read_text())
        if data.get("site_id") and data.get("true_domain"):
            data["_stem"] = path.stem
            out.append(data)
    return out


def summarise(fixture: dict) -> dict[str, object]:
    site_id = fixture["site_id"]
    tech = "HFC" if str(fixture.get("technology", "")).upper() == "HFC" else "PON"
    domain = fixture["true_domain"]
    incident = fixture.get("incident_id", fixture["_stem"])

    base = simulate_resolution(incident_id=incident, site_id=site_id, technology=tech,
                               true_domain=domain)
    retried = simulate_resolution(incident_id=incident, site_id=site_id, technology=tech,
                                  true_domain=domain, remote_attempts_failed=2)
    missed = simulate_resolution(incident_id=incident, site_id=site_id, technology=tech,
                                 true_domain=domain, misdispatch=True)
    sel = select_base(SITE_BY_ID[site_id], crew_type="dirty")
    return {
        "incident": incident, "scenario": fixture["_stem"],
        "municipio": fixture.get("municipio", ""), "technology": tech,
        "true_domain": domain,
        "delimiter": delimiter_for(site_id, tech).element_id,
        "households_affected": blast_radius(domain, site_id, tech),
        "dirty_base": sel.base.base_id.replace("BASE-", ""),
        "same_day": sel.plan.same_day_feasible,
        "resolved_min": base.total_minutes, "resolved_usd": base.total_cost,
        "retry_min": retried.total_minutes, "retry_usd": retried.total_cost,
        "missed_min": missed.total_minutes, "missed_usd": missed.total_cost,
        "retry_delta_usd": round(retried.total_cost - base.total_cost, 2),
        "missed_delta_usd": round(missed.total_cost - base.total_cost, 2),
        "truck_rolls_missed": missed.truck_rolls,
    }


def detail(fixture: dict) -> None:
    site_id = fixture["site_id"]
    tech = "HFC" if str(fixture.get("technology", "")).upper() == "HFC" else "PON"
    print(f"\n{fixture.get('incident_id', fixture['_stem'])} — "
          f"{fixture.get('municipio')} — {tech} — true domain {fixture['true_domain']}")
    print("\n  plant chain")
    for element in chain_for(site_id, tech):
        mark = "  <- delimiter, MR raised here" if element.is_delimiter else ""
        print(f"    {element.kind:10s} {element.element_id:22s} "
              f"{element.serves_households:>3} hh  crew={element.crew_type}{mark}")

    for label, kwargs in (("resolved first time", {}),
                          ("two remote attempts failed", {"remote_attempts_failed": 2}),
                          ("missed gate, wrong crew first", {"misdispatch": True})):
        led = simulate_resolution(incident_id="X", site_id=site_id, technology=tech,
                                  true_domain=fixture["true_domain"], **kwargs)
        print(f"\n  {label}")
        for row in led.as_rows():
            note = f"  {row['note']}" if row["note"] else ""
            print(f"    {row['step']:26s} {row['role']:14s} {row['minutes']:>4} min "
                  f"${row['cost_usd']:>8.2f}{note}")
        print(f"    {'TOTAL':26s} {'':14s} {led.total_minutes:>4} min "
              f"${led.total_cost:>8.2f}   ({led.elapsed_hours()} h, "
              f"{led.truck_rolls} truck roll(s))")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--detail", metavar="INCIDENT", help="full ledger for one incident")
    ap.add_argument("--json", metavar="PATH")
    args = ap.parse_args()

    fixtures = load()
    rows = [summarise(f) for f in fixtures]

    if args.detail:
        match = [f for f in fixtures
                 if args.detail in (f.get("incident_id"), f["_stem"])]
        if not match:
            print(f"no scenario matching {args.detail!r}. Available: "
                  f"{', '.join(str(f.get('incident_id')) for f in fixtures)}",
                  file=sys.stderr)
            return 1
        detail(match[0])
        return 0

    print(f"Dispatch simulation — {len(rows)} located scenarios. All rates assumed.\n")
    head = (f"{'incident':9s} {'municipio':10s} {'domain':14s} {'delimiter':20s} "
            f"{'hh':>4} {'base':4s} {'day':3s} {'resolved':>14s} {'+2 remote':>14s} "
            f"{'misdispatch':>15s}")
    print(head)
    print("-" * len(head))
    for r in sorted(rows, key=lambda x: -float(x["missed_usd"])):
        print(f"{str(r['incident'])[:9]:9s} {str(r['municipio'])[:10]:10s} "
              f"{str(r['true_domain'])[:14]:14s} "
              f"{r['delimiter']:20s} {r['households_affected']:>4} {r['dirty_base']:4s} "
              f"{'yes' if r['same_day'] else 'NO':3s} "
              f"{r['resolved_min']:>5}m ${r['resolved_usd']:>6.0f} "
              f"{r['retry_min']:>5}m ${r['retry_usd']:>6.0f} "
              f"{r['missed_min']:>6}m ${r['missed_usd']:>7.0f}")

    tot_res = sum(float(r["resolved_usd"]) for r in rows)
    tot_retry = sum(float(r["retry_usd"]) for r in rows)
    tot_missed = sum(float(r["missed_usd"]) for r in rows)
    print(f"\n{'TOTAL':9s} {'':10s} {'':14s} {'':20s} {'':4s} {'':4s} {'':3s} "
          f"{sum(int(r['resolved_min']) for r in rows):>5}m ${tot_res:>6.0f} "
          f"{sum(int(r['retry_min']) for r in rows):>5}m ${tot_retry:>6.0f} "
          f"{sum(int(r['missed_min']) for r in rows):>6}m ${tot_missed:>7.0f}")

    print(f"\n  Two failed remote attempts add ${tot_retry - tot_res:,.0f} across "
          f"{len(rows)} incidents ({(tot_retry / tot_res - 1) * 100:.0f}% more).")
    print(f"  A missed gate on every one would add ${tot_missed - tot_res:,.0f} "
          f"({(tot_missed / tot_res - 1) * 100:.0f}% more).")

    fp = false_positive_cost()
    worst = max(rows, key=lambda r: false_negative_cost(
        next(f["site_id"] for f in fixtures if f.get("incident_id") == r["incident"]
             or f["_stem"] == r["scenario"]), str(r["true_domain"])).cost_usd)
    worst_site = next(f["site_id"] for f in fixtures
                      if f["_stem"] == worst["scenario"])
    fn = false_negative_cost(worst_site, str(worst["true_domain"]))
    print(f"\n  One false positive costs {fp.minutes} min and ${fp.cost_usd:.2f}.")
    print(f"  The worst false negative here, {worst['municipio']}, costs "
          f"{fn.minutes} min and ${fn.cost_usd:.2f}: {round(fn.cost_usd / fp.cost_usd)}x.")
    print("  That ratio is why a gate can be wrong often and still pay for itself.")

    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(
            {"scenarios": rows, "assumptions": assumptions()}, indent=2) + "\n")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
