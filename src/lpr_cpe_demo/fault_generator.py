"""Generate synthetic faults with locations, intervention points and costs.

Two modelling points that matter
--------------------------------
**The intervention location is not the customer address.** A CPE or in-home fault
is worked at the premise; a tap or ODP fault is worked at the tap or ODP, which is
a different physical place, reached by a different crew, and serves several
households. Showing both on a map is the point: it is why "responsibility domain"
determines cost.

**Fault density follows households, not municipios.** Sampling sites uniformly
would give Culebra as many faults as San Juan. Sites are weighted by modelled
household count, so the metro dominates volume while the islands dominate unit
cost, which is the tension the archetype model exists to express.

Reproducibility
---------------
Everything is derived from an explicit seed. The same seed gives the same faults,
the same coordinates and the same costs on any machine, so a demo can be re-run and
a number quoted afterwards. Coordinate jitter is derived from a hash of the element
identifier rather than the RNG, so a given tap always sits in the same place.

Assumed, as everywhere in this model
------------------------------------
The domain mix in `DOMAIN_MIX` is shaped from the resolution-lane percentages in
the archetype planning model, not from LPR incident data. Jitter radii are
plausible spreads for a municipio, not surveyed plant positions.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field
from typing import Iterable, Literal

from .effort import EffortLedger, false_negative_cost, simulate_resolution
from .geography import SITE_BY_ID, Site, select_base, sites_in_cpe_footprint
from .plant import (DOMAIN_TO_KIND, PLANT_ASSUMPTIONS, blast_radius, chain_for,
                    households, site_plant)

Technology = Literal["HFC", "PON"]

# Domain mix by archetype. Shaped from the resolution-lane percentages in the
# archetype planning model; the metro skews to in-home and remote-fixable causes,
# the mountain and island archetypes skew to plant.
DOMAIN_MIX: dict[str, dict[str, float]] = {
    "metro": {"provisioning": 0.18, "cpe": 0.22, "wifi_or_home": 0.20,
              "premise_wiring": 0.05, "drop": 0.13, "delimiter": 0.12,
              "plant": 0.10},
    "coastal": {"provisioning": 0.15, "cpe": 0.19, "wifi_or_home": 0.15,
                "premise_wiring": 0.05, "drop": 0.16, "delimiter": 0.16,
                "plant": 0.14},
    "mountain": {"provisioning": 0.11, "cpe": 0.15, "wifi_or_home": 0.10,
                 "premise_wiring": 0.05, "drop": 0.20, "delimiter": 0.22,
                 "plant": 0.17},
    "remote_island": {"provisioning": 0.10, "cpe": 0.14, "wifi_or_home": 0.09,
                      "premise_wiring": 0.05, "drop": 0.20, "delimiter": 0.24,
                      "plant": 0.18},
}

# Jitter radius in km: how far plant sits from the municipio centroid.
JITTER_KM: dict[str, float] = {
    "metro": 3.0, "coastal": 5.5, "mountain": 7.0, "remote_island": 4.0,
}

# Extra separation between a household and its delimiter, in km.
DELIMITER_OFFSET_KM: dict[str, float] = {
    "metro": 0.25, "coastal": 0.5, "mountain": 1.2, "remote_island": 0.7,
}

PRIORITIES = ("P1", "P2", "P3")


def _stable_offset(key: str, radius_km: float) -> tuple[float, float]:
    """Deterministic offset in degrees, derived from a hash of `key`.

    Uses the hash rather than the RNG so a given tap identifier always lands in
    the same place, however many faults are generated around it.
    """
    digest = hashlib.sha256(key.encode()).digest()
    angle = (digest[0] / 255.0) * 2 * math.pi
    # sqrt for an even areal distribution rather than clustering at the centre
    distance = radius_km * math.sqrt(digest[1] / 255.0)
    dlat = (distance / 111.32) * math.cos(angle)
    dlon = (distance / (111.32 * math.cos(math.radians(18.2)))) * math.sin(angle)
    return round(dlat, 6), round(dlon, 6)


@dataclass(frozen=True, slots=True)
class GeneratedFault:
    fault_id: str
    site_id: str
    municipio: str
    archetype: str
    technology: Technology
    true_domain: str
    priority: str

    household_id: str
    household_lat: float
    household_lon: float

    delimiter_kind: str
    delimiter_id: str
    delimiter_lat: float
    delimiter_lon: float

    intervention_kind: str
    intervention_id: str
    intervention_lat: float
    intervention_lon: float
    households_affected: int

    crew_type: str
    base_id: str
    base_name: str
    travel_minutes: int
    requires_ferry: bool
    same_day_feasible: bool

    total_minutes: int
    total_cost_usd: float
    truck_rolls: int
    misdispatch_cost_usd: float
    ledger_rows: tuple[dict[str, object], ...] = field(default_factory=tuple)

    @property
    def intervention_is_at_premise(self) -> bool:
        return self.intervention_kind in {"household", "drop"}

    @property
    def misdispatch_premium_usd(self) -> float:
        return round(self.misdispatch_cost_usd - self.total_cost_usd, 2)


def _pick_domain(rng: random.Random, archetype: str, technology: Technology) -> str:
    mix = DOMAIN_MIX[archetype]
    roll = rng.random()
    cumulative = 0.0
    chosen = "cpe"
    for domain, weight in mix.items():
        cumulative += weight
        if roll <= cumulative:
            chosen = domain
            break
    if chosen == "delimiter":
        return "hfc_tap" if technology == "HFC" else "pon_odp"
    if chosen == "plant":
        return "plant" if technology == "PON" else rng.choice(
            ["plant", "shared_network"])
    return chosen


def _pick_technology(rng: random.Random, site: Site) -> Technology:
    share = float(PLANT_ASSUMPTIONS["pon_share_by_archetype"][site.archetype])  # type: ignore[index]
    return "PON" if rng.random() < share else "HFC"


def generate_faults(count: int = 25, *, seed: int = 20260817,
                    sites: Iterable[Site] | None = None) -> list[GeneratedFault]:
    """Sample `count` faults, weighting sites by modelled household count."""
    if count < 1:
        raise ValueError("count must be >= 1")
    rng = random.Random(seed)
    pool = list(sites if sites is not None else sites_in_cpe_footprint())
    weights = [max(1, households(s)) for s in pool]

    faults: list[GeneratedFault] = []
    for index in range(count):
        site = rng.choices(pool, weights=weights, k=1)[0]
        technology = _pick_technology(rng, site)
        domain = _pick_domain(rng, site.archetype, technology)
        element_index = rng.randrange(0, max(1, site_plant(site)["taps"]))
        chain = {e.kind: e for e in chain_for(site.site_id, technology, element_index)}

        household = chain["household"]
        delimiter = chain["tap"] if technology == "HFC" else chain["odp"]

        hh_dlat, hh_dlon = _stable_offset(household.element_id,
                                          JITTER_KM[site.archetype])
        hh_lat, hh_lon = site.lat + hh_dlat, site.lon + hh_dlon

        d_dlat, d_dlon = _stable_offset(delimiter.element_id,
                                        DELIMITER_OFFSET_KM[site.archetype])
        del_lat, del_lon = hh_lat + d_dlat, hh_lon + d_dlon

        kind = DOMAIN_TO_KIND.get(domain, "household")
        if kind in {"household", "drop"}:
            intervention = (kind, household.element_id if kind == "household"
                            else chain["drop"].element_id, hh_lat, hh_lon)
        elif kind in {"tap", "odp"}:
            intervention = (kind, delimiter.element_id, del_lat, del_lon)
        else:
            upstream = chain["hfc_node"] if technology == "HFC" else chain["pon_port"]
            up_dlat, up_dlon = _stable_offset(upstream.element_id,
                                             JITTER_KM[site.archetype] * 0.6)
            intervention = (upstream.kind, upstream.element_id,
                            site.lat + up_dlat, site.lon + up_dlon)

        crew = "clean" if kind in {"household", "drop"} else "dirty"
        selection = select_base(site, crew_type=crew)
        ledger: EffortLedger = simulate_resolution(
            incident_id=f"SIM-{index + 1:04d}", site_id=site.site_id,
            technology=technology, true_domain=domain)
        missed = false_negative_cost(site.site_id, domain)

        faults.append(GeneratedFault(
            fault_id=f"SIM-{index + 1:04d}",
            site_id=site.site_id, municipio=site.municipio,
            archetype=site.archetype, technology=technology,
            true_domain=domain, priority=rng.choices(PRIORITIES, [0.15, 0.35, 0.5])[0],
            household_id=household.element_id,
            household_lat=round(hh_lat, 5), household_lon=round(hh_lon, 5),
            delimiter_kind=delimiter.kind, delimiter_id=delimiter.element_id,
            delimiter_lat=round(del_lat, 5), delimiter_lon=round(del_lon, 5),
            intervention_kind=intervention[0], intervention_id=intervention[1],
            intervention_lat=round(intervention[2], 5),
            intervention_lon=round(intervention[3], 5),
            households_affected=blast_radius(domain, site.site_id, technology),
            crew_type=crew, base_id=selection.base.base_id,
            base_name=selection.base.name,
            travel_minutes=selection.plan.total_minutes,
            requires_ferry=selection.plan.requires_ferry,
            same_day_feasible=selection.plan.same_day_feasible,
            total_minutes=ledger.total_minutes, total_cost_usd=ledger.total_cost,
            truck_rolls=ledger.truck_rolls,
            misdispatch_cost_usd=round(ledger.total_cost + missed.cost_usd, 2),
            ledger_rows=tuple(ledger.as_rows()),
        ))
    return faults


def summarise(faults: Iterable[GeneratedFault]) -> dict[str, object]:
    items = list(faults)
    if not items:
        return {"faults": 0}
    dirty = [f for f in items if f.crew_type == "dirty"]
    ferry = [f for f in items if f.requires_ferry]
    overnight = [f for f in items if not f.same_day_feasible]
    total = sum(f.total_cost_usd for f in items)
    return {
        "faults": len(items),
        "total_minutes": sum(f.total_minutes for f in items),
        "total_cost_usd": round(total, 2),
        "mean_cost_usd": round(total / len(items), 2),
        "truck_rolls": sum(f.truck_rolls for f in items),
        "dirty_boots_share": round(len(dirty) / len(items), 3),
        "ferry_jobs": len(ferry),
        "overnight_jobs": len(overnight),
        "households_affected": sum(f.households_affected for f in items),
        "misdispatch_exposure_usd": round(
            sum(f.misdispatch_premium_usd for f in items), 2),
        "off_premise_interventions": sum(
            1 for f in items if not f.intervention_is_at_premise),
    }
