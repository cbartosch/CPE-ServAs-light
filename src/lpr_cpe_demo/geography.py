"""Service geography for the Liberty Puerto Rico fixed footprint.

Scope, verified rather than assumed
-----------------------------------
The fixed HFC and PON footprint is Puerto Rico: 78 municipios, including the
island municipios of Vieques and Culebra. The U.S. Virgin Islands are served for
mobile under Liberty Puerto Rico, while USVI fixed broadband sits with a
separate entity following the Broadband VI acquisition, so USVI sites are
modelled but marked out of scope for CPE fault management by default.

What is ASSUMED and must be replaced
------------------------------------
Liberty does not publish operations-centre locations. Every `DispatchBase` below
is an ASSUMPTION placed at a regional municipio that would plausibly host one,
and each carries ``assumed=True``. The only externally supported anchor is a
core platform site in San Juan. Before this model is used for anything
operational, replace `DISPATCH_BASES` with actual facility locations, crew
rosters and van stock. `assumed_bases()` exists so the UI and the API can say so
out loud.

Coordinates are approximate municipio centroids, adequate for a schematic map
and a relative travel model. They are not survey grade.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Literal, NamedTuple

Archetype = Literal["metro", "coastal", "mountain", "remote_island"]
CrewType = Literal["clean", "dirty", "joint"]

# Road speeds by archetype, km/h. Metro is slowest for congestion, mountain for
# terrain. A detour factor converts straight-line distance into road distance.
ROAD_SPEED_KMH: dict[str, float] = {
    "metro": 28.0, "coastal": 45.0, "mountain": 32.0, "remote_island": 38.0,
}
DETOUR_FACTOR = 1.35

# Ferry legs from the Fajardo terminal. Crossing plus a mean wait for the next
# scheduled sailing, since cargo and passenger slots are limited.
FERRY_MINUTES: dict[str, int] = {"VIEQUES": 65 + 90, "CULEBRA": 90 + 120}


@dataclass(frozen=True, slots=True)
class Site:
    site_id: str
    municipio: str
    region: str
    archetype: Archetype
    lat: float
    lon: float
    technologies: tuple[str, ...] = ("HFC", "PON")
    island: bool = False
    ferry_from: str | None = None      # site_id of the mainland embarkation point
    in_cpe_footprint: bool = True


@dataclass(frozen=True, slots=True)
class DispatchBase:
    base_id: str
    name: str
    site_id: str
    lat: float
    lon: float
    crew_types: tuple[CrewType, ...]
    skills: tuple[str, ...]
    van_stock: tuple[str, ...]
    assumed: bool = True               # never silently present these as real
    notes: str = ""


# --------------------------------------------------------------------- sites
# Approximate centroids. Archetypes follow the four-segment planning model.
SITES: tuple[Site, ...] = (
    # Metro / MDU
    Site("PR-SJU", "San Juan", "San Juan metro", "metro", 18.4655, -66.1057),
    Site("PR-BAY", "Bayamon", "San Juan metro", "metro", 18.3985, -66.1614),
    Site("PR-CAR", "Carolina", "San Juan metro", "metro", 18.3808, -65.9574),
    Site("PR-GUY", "Guaynabo", "San Juan metro", "metro", 18.3572, -66.1110),
    Site("PR-CAG", "Caguas", "Caguas urban core", "metro", 18.2341, -66.0362),
    # Coastal city / suburb
    Site("PR-PON", "Ponce", "South coast", "coastal", 18.0111, -66.6141),
    Site("PR-MAY", "Mayaguez", "West coast", "coastal", 18.2013, -67.1397),
    Site("PR-ARE", "Arecibo", "North coast", "coastal", 18.4725, -66.7156),
    Site("PR-AGU", "Aguadilla", "Northwest coast", "coastal", 18.4274, -67.1541),
    Site("PR-HUM", "Humacao", "East coast", "coastal", 18.1494, -65.8272),
    Site("PR-FAJ", "Fajardo", "Northeast coast", "coastal", 18.3258, -65.6524),
    Site("PR-GUA", "Guayama", "South coast", "coastal", 17.9841, -66.1132),
    Site("PR-MAN", "Manati", "North coast", "coastal", 18.4297, -66.4822),
    Site("PR-CAB", "Cabo Rojo", "Southwest coast", "coastal", 18.0866, -67.1457),
    # Central mountain / rural
    Site("PR-UTU", "Utuado", "Cordillera Central", "mountain", 18.2658, -66.7005),
    Site("PR-ADJ", "Adjuntas", "Cordillera Central", "mountain", 18.1627, -66.7224),
    Site("PR-JAY", "Jayuya", "Cordillera Central", "mountain", 18.2186, -66.5916),
    Site("PR-CIA", "Ciales", "Cordillera Central", "mountain", 18.3364, -66.4685),
    Site("PR-MAR", "Maricao", "Western highlands", "mountain", 18.1808, -66.9799),
    Site("PR-LMA", "Las Marias", "Western highlands", "mountain", 18.2517, -66.9930),
    Site("PR-YAU", "Yauco", "Southern highlands", "mountain", 18.0344, -66.8499),
    # Remote / island
    Site("PR-VQS", "Vieques", "Island municipio", "remote_island", 18.1494, -65.4436,
         island=True, ferry_from="PR-FAJ"),
    Site("PR-CUL", "Culebra", "Island municipio", "remote_island", 18.3033, -65.3010,
         island=True, ferry_from="PR-FAJ"),
    # USVI: mobile under Liberty PR, fixed under a separate entity.
    Site("VI-STT", "St Thomas", "U.S. Virgin Islands", "remote_island", 18.3381, -64.8941,
         technologies=("PON",), island=True, in_cpe_footprint=False),
    Site("VI-STX", "St Croix", "U.S. Virgin Islands", "remote_island", 17.7275, -64.7799,
         technologies=("PON",), island=True, in_cpe_footprint=False),
    Site("VI-STJ", "St John", "U.S. Virgin Islands", "remote_island", 18.3336, -64.7314,
         technologies=("PON",), island=True, in_cpe_footprint=False),
)

SITE_BY_ID = {s.site_id: s for s in SITES}

_PLANT = ("hfc_plant", "coax_splice", "fibre_splice", "aerial", "underground")
_FIELD = ("cpe_swap", "in_home_wiring", "wifi_optimisation", "drop_replacement")

# ------------------------------------------------------------- dispatch bases
# EVERY ENTRY IS ASSUMED. See the module docstring.
DISPATCH_BASES: tuple[DispatchBase, ...] = (
    DispatchBase("BASE-SJU", "San Juan operations centre", "PR-SJU", 18.4655, -66.1057,
                 ("clean", "dirty", "joint"), _FIELD + _PLANT + ("noc", "headend"),
                 ("cpe", "ont", "psu", "drop", "connectors", "splice_kit"),
                 notes="Anchored on a publicly referenced core platform site in San Juan; "
                       "crew and stock composition assumed."),
    DispatchBase("BASE-CAG", "Caguas field base", "PR-CAG", 18.2341, -66.0362,
                 ("clean", "dirty"), _FIELD + _PLANT,
                 ("cpe", "ont", "psu", "drop", "connectors")),
    DispatchBase("BASE-PON", "Ponce field base", "PR-PON", 18.0111, -66.6141,
                 ("clean", "dirty"), _FIELD + _PLANT,
                 ("cpe", "ont", "psu", "drop", "connectors", "splice_kit")),
    DispatchBase("BASE-MAY", "Mayaguez field base", "PR-MAY", 18.2013, -67.1397,
                 ("clean", "dirty"), _FIELD + _PLANT,
                 ("cpe", "ont", "psu", "drop", "connectors")),
    DispatchBase("BASE-ARE", "Arecibo field base", "PR-ARE", 18.4725, -66.7156,
                 ("clean", "dirty"), _FIELD + _PLANT,
                 ("cpe", "ont", "psu", "drop", "connectors")),
    DispatchBase("BASE-HUM", "Humacao field base", "PR-HUM", 18.1494, -65.8272,
                 ("clean", "dirty"), _FIELD + _PLANT,
                 ("cpe", "ont", "psu", "drop", "connectors")),
    DispatchBase("BASE-FAJ", "Fajardo field base and ferry staging", "PR-FAJ",
                 18.3258, -65.6524, ("clean", "dirty"), _FIELD + _PLANT,
                 ("cpe", "ont", "psu", "drop", "connectors", "splice_kit"),
                 notes="Embarkation for Vieques and Culebra. No resident crew on either "
                       "island in this model, so island work is staged from here."),
)

BASE_BY_ID = {b.base_id: b for b in DISPATCH_BASES}


def assumed_bases() -> tuple[DispatchBase, ...]:
    """Bases whose location and composition are assumptions, not facts."""
    return tuple(b for b in DISPATCH_BASES if b.assumed)


# ------------------------------------------------------------------ distance
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class Leg(NamedTuple):
    kind: str          # road | ferry
    description: str
    minutes: int


class TravelPlan(NamedTuple):
    base_id: str
    site_id: str
    legs: tuple[Leg, ...]
    total_minutes: int
    requires_ferry: bool
    same_day_feasible: bool


def travel_plan(base: DispatchBase, site: Site,
                *, shift_minutes: int = 480, on_site_minutes: int = 90) -> TravelPlan:
    """Road time, plus a ferry leg when the site is an island municipio.

    Same-day feasibility assumes a round trip plus the on-site work must fit one
    shift. This is what makes the remote-island archetype expensive: the ferry
    leg alone can exceed the shift budget.
    """
    legs: list[Leg] = []
    if site.island and site.ferry_from:
        embark = SITE_BY_ID[site.ferry_from]
        road_km = haversine_km(base.lat, base.lon, embark.lat, embark.lon) * DETOUR_FACTOR
        road_min = int(round(60 * road_km / ROAD_SPEED_KMH[embark.archetype]))
        legs.append(Leg("road", f"{base.name} to {embark.municipio} terminal", road_min))
        ferry_min = FERRY_MINUTES.get(site.municipio.upper(), 120)
        legs.append(Leg("ferry", f"{embark.municipio} to {site.municipio} "
                                 "including mean wait for the next sailing", ferry_min))
    else:
        road_km = haversine_km(base.lat, base.lon, site.lat, site.lon) * DETOUR_FACTOR
        road_min = int(round(60 * road_km / ROAD_SPEED_KMH[site.archetype]))
        legs.append(Leg("road", f"{base.name} to {site.municipio}", road_min))

    one_way = sum(l.minutes for l in legs)
    requires_ferry = any(l.kind == "ferry" for l in legs)
    return TravelPlan(base.base_id, site.site_id, tuple(legs), one_way, requires_ferry,
                      (2 * one_way + on_site_minutes) <= shift_minutes)


class BaseSelection(NamedTuple):
    base: DispatchBase
    plan: TravelPlan
    considered: int
    rejected_for_skills: tuple[str, ...]
    rejected_for_parts: tuple[str, ...]


def select_base(site: Site, *, crew_type: CrewType,
                required_skills: Iterable[str] = (),
                required_parts: Iterable[str] = (),
                bases: Iterable[DispatchBase] | None = None) -> BaseSelection:
    """Nearest base by travel time that can actually do the work.

    Skills and parts filter first; travel time only orders what remains. A
    nearer base without a splice kit is not a candidate for a fibre splice.
    """
    skills, parts = set(required_skills), set(required_parts)
    pool = tuple(bases if bases is not None else DISPATCH_BASES)

    no_skills, no_parts, viable = [], [], []
    for base in pool:
        if crew_type not in base.crew_types:
            continue
        if not skills.issubset(base.skills):
            no_skills.append(base.base_id); continue
        if not parts.issubset(base.van_stock):
            no_parts.append(base.base_id); continue
        viable.append(base)

    if not viable:
        raise LookupError(
            f"no {crew_type} base can serve {site.site_id} with skills {sorted(skills)} "
            f"and parts {sorted(parts)}")

    ranked = sorted(((travel_plan(b, site), b) for b in viable),
                    key=lambda pair: (pair[0].total_minutes, pair[1].base_id))
    plan, base = ranked[0]
    return BaseSelection(base, plan, len(pool), tuple(no_skills), tuple(no_parts))


def sites_in_cpe_footprint() -> tuple[Site, ...]:
    return tuple(s for s in SITES if s.in_cpe_footprint)


def sites_by_archetype(archetype: str) -> tuple[Site, ...]:
    return tuple(s for s in sites_in_cpe_footprint() if s.archetype == archetype)
