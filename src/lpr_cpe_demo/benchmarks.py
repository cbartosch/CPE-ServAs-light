"""Third-party truck roll cost benchmark, replacing invented dollar figures.

Source
------
AEX, "Truck Roll Cost Benchmarks for Fiber Operators".
https://aexinc.com/blog/truck-roll-cost-benchmarks-fiber  (retrieved 2026-08-17)

Corroborating range: Smarty citing SightCall at $150-500 and CareAR at $200-300.
Note that SightCall separately claims the true all-in figure exceeds $1,000 once
indirect costs are loaded; that is a broader definition than used here.

What the benchmark includes, per the source
-------------------------------------------
Technician labour for the full job plus travel time, vehicle cost (lease, fuel,
maintenance, insurance), tools and equipment amortisation, parts consumed on the
visit, and dispatch and back-office allocation.

Explicitly excluded: corporate overhead, sales and marketing, and network
infrastructure depreciation. This is fully loaded *direct* cost.

Why this replaces the bottom-up model
-------------------------------------
`effort.RATES` builds a cost from assumed labour rates. That produced figures
whose magnitude nobody could check. These bands are published, attributable, and
band-selectable by operational maturity, so a number quoted from them can be
defended or disputed on its source rather than on my arithmetic.

Two honest limits
-----------------
1. The bands are for **fiber operators**, and the source's first-visit-completion
   discussion is framed around installs. LPR's CPE fault work is repair rather
   than install, so the bands are an analogue, not a like-for-like.
2. The benchmark does not contemplate a ferry crossing or an overnight stay.
   Island work therefore needs an adder that sits **outside** the cited range,
   and `island_adder_usd` keeps it separate rather than blending it in and
   implying the source covers it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SOURCE = {
    "publisher": "AEX",
    "title": "Truck Roll Cost Benchmarks for Fiber Operators",
    "url": "https://aexinc.com/blog/truck-roll-cost-benchmarks-fiber",
    "retrieved": "2026-08-17",
    "headline_range_usd": (150.0, 300.0),
    "includes": ("technician labour for the full job", "travel time",
                 "vehicle lease, fuel, maintenance, insurance",
                 "tools and equipment amortisation", "parts consumed on the visit",
                 "dispatch and back-office allocation"),
    "excludes": ("corporate overhead", "sales and marketing",
                 "network infrastructure depreciation"),
    "corroborating": ("Smarty citing SightCall at $150-500 and CareAR at $200-300",),
}

Band = Literal["low", "mid", "high"]

# Published bands, USD per dispatched visit, with the operational profile the
# source attaches to each.
BANDS: dict[Band, dict[str, object]] = {
    "low": {"range": (125.0, 175.0), "midpoint": 150.0,
            "profile": "modern field service platform, optimised routing, "
                       "real-time parts visibility, first-visit completion 90%+, "
                       "4 to 5 completed jobs per technician per day"},
    "mid": {"range": (175.0, 250.0), "midpoint": 212.5,
            "profile": "where most operators sit: some automation, manual handoffs "
                       "between CSR, dispatch and field, first-visit completion "
                       "80 to 85%, 3 to 4 jobs per day"},
    "high": {"range": (250.0, 350.0), "midpoint": 300.0,
             "profile": "spreadsheet dispatch, phone calls, paper work orders, "
                        "first-visit completion below 75%, around 3 jobs per day"},
}

# "Rural operators generally run 15 to 25 percent higher across all bands because
# drive time is longer and density is lower." Midpoint taken.
RURAL_UPLIFT = 0.20
RURAL_UPLIFT_RANGE = (0.15, 0.25)
RURAL_ARCHETYPES = frozenset({"mountain", "remote_island"})

# First-visit completion by archetype, from the LPR archetype planning model's
# FTFR figures. Operator-supplied, not from the benchmark.
FIRST_VISIT_COMPLETION: dict[str, dict[str, float]] = {
    "HFC": {"metro": 0.84, "coastal": 0.80, "mountain": 0.74, "remote_island": 0.70},
    "PON": {"metro": 0.88, "coastal": 0.85, "mountain": 0.80, "remote_island": 0.76},
}

# Outside the benchmark's scope: a ferry slot plus an overnight when the round trip
# exceeds a shift. Kept separate so the cited figure is not silently inflated.
ISLAND_ADDER_USD = 400.0


@dataclass(frozen=True, slots=True)
class RollCost:
    archetype: str
    technology: str
    band: Band
    base_usd: float              # published band midpoint
    rural_uplift_usd: float      # cited 15-25% uplift, 0 on non-rural
    island_adder_usd: float      # NOT from the benchmark
    per_dispatch_usd: float      # what one dispatched visit costs
    first_visit_completion: float
    per_completed_usd: float     # per_dispatch / FVC, the source's key metric

    @property
    def within_benchmark_scope(self) -> bool:
        return self.island_adder_usd == 0.0

    @property
    def repeat_visit_premium_usd(self) -> float:
        """What imperfect first-visit completion adds per completed job."""
        return round(self.per_completed_usd - self.per_dispatch_usd, 2)


def roll_cost(archetype: str, technology: str, *, band: Band = "mid",
              island: bool = False) -> RollCost:
    base = float(BANDS[band]["midpoint"])  # type: ignore[arg-type]
    uplift = base * RURAL_UPLIFT if archetype in RURAL_ARCHETYPES else 0.0
    adder = ISLAND_ADDER_USD if island else 0.0
    per_dispatch = base + uplift + adder
    fvc = FIRST_VISIT_COMPLETION[technology][archetype]
    return RollCost(
        archetype=archetype, technology=technology, band=band,
        base_usd=round(base, 2), rural_uplift_usd=round(uplift, 2),
        island_adder_usd=round(adder, 2),
        per_dispatch_usd=round(per_dispatch, 2), first_visit_completion=fvc,
        per_completed_usd=round(per_dispatch / fvc, 2))


def wasted_visit_cost(archetype: str, technology: str, *, band: Band = "mid",
                      island: bool = False) -> float:
    """Cost of a dispatch that completes nothing.

    This is the per-dispatch figure, not the per-completed figure. Using the
    latter would double count: dividing by first-visit completion already prices
    the repeat visits that a wasted dispatch causes.
    """
    return roll_cost(archetype, technology, band=band, island=island).per_dispatch_usd


def band_for_profile(first_visit_completion: float) -> Band:
    """Infer a band from an operator's own first-visit completion rate."""
    if first_visit_completion >= 0.90:
        return "low"
    if first_visit_completion >= 0.75:
        return "mid"
    return "high"


def citation() -> str:
    return (f"{SOURCE['publisher']}, \"{SOURCE['title']}\", {SOURCE['url']} "
            f"(retrieved {SOURCE['retrieved']}). Headline range "
            f"${SOURCE['headline_range_usd'][0]:.0f} to "
            f"${SOURCE['headline_range_usd'][1]:.0f} per roll, fully loaded direct "
            f"cost, excluding corporate overhead.")
