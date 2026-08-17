"""Plant topology: households, drops, taps, ODPs, nodes and OLT ports.

Everything here is ASSUMED and deliberately parameterised
---------------------------------------------------------
Liberty publishes neither plant records nor per-municipio subscriber counts. What
this module contains is:

* Household counts per site, approximated from published municipal populations at
  an assumed 2.7 persons per household. Order-of-magnitude, not actuals.
* Serving ratios (homes per tap, per ODP splitter, per node, per PON port) taken
  from conventional HFC and PON design practice, not from LPR's build.
* Deterministic synthetic identifiers, so `TAP-ARE-0142` is stable across runs and
  can be referenced in a scenario, a work order and an MR without a database.

The FCC's Stage 2 authorisation covers approximately 1.22 million locations across
Puerto Rico's 78 municipios, which is the one externally supported anchor. The
modelled total is reported by `footprint_totals()` so the scale can be sanity
checked against it, and `PLANT_ASSUMPTIONS` states every ratio in one place for
replacement with real records.

Why synthetic plant matters for the demo
----------------------------------------
Blast radius is what separates a drop fault from a tap fault operationally. One
household behind a bad drop is a clean-boots visit; eight households behind an
oxidised tap port is plant work, an MR, and a different crew. Without modelled
plant, "responsibility domain" is an abstract label; with it, each domain implies
a countable number of affected customers.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from .geography import SITE_BY_ID, Site, sites_in_cpe_footprint

Technology = Literal["HFC", "PON"]

# --------------------------------------------------------------- assumptions
PLANT_ASSUMPTIONS: dict[str, object] = {
    "persons_per_household": 2.7,
    "homes_per_tap": {"metro": 8, "coastal": 6, "mountain": 4, "remote_island": 4},
    "homes_per_odp": {"metro": 32, "coastal": 16, "mountain": 8, "remote_island": 8},
    "homes_per_hfc_node": 450,
    "homes_per_pon_port": 32,
    "pon_share_by_archetype": {"metro": 0.45, "coastal": 0.35,
                               "mountain": 0.20, "remote_island": 0.25},
    "basis": "conventional HFC and PON design practice, not LPR plant records",
    "household_basis": "approximated from published municipal populations at "
                       "2.7 persons per household",
}

# Approximate populations, used only to scale household counts. Rounded.
POPULATION: dict[str, int] = {
    "PR-SJU": 342_000, "PR-BAY": 185_000, "PR-CAR": 154_000, "PR-GUY": 89_000,
    "PR-CAG": 127_000, "PR-PON": 137_000, "PR-MAY": 73_000, "PR-ARE": 87_000,
    "PR-AGU": 55_000, "PR-HUM": 50_000, "PR-FAJ": 32_000, "PR-GUA": 36_000,
    "PR-MAN": 39_000, "PR-CAB": 47_000, "PR-UTU": 28_000, "PR-ADJ": 17_000,
    "PR-JAY": 14_000, "PR-CIA": 16_000, "PR-MAR": 5_000, "PR-LMA": 8_000,
    "PR-YAU": 34_000, "PR-VQS": 8_000, "PR-CUL": 1_800,
}


def households(site: Site) -> int:
    pop = POPULATION.get(site.site_id)
    if pop is None:
        return 0
    return int(round(pop / float(PLANT_ASSUMPTIONS["persons_per_household"])))


def _seq(site_id: str, kind: str, index: int) -> str:
    """Deterministic 4-digit sequence, stable across processes and machines."""
    material = f"{site_id}|{kind}|{index}".encode()
    return f"{int(hashlib.sha256(material).hexdigest()[:6], 16) % 10000:04d}"


@dataclass(frozen=True, slots=True)
class PlantElement:
    element_id: str
    kind: Literal["household", "drop", "tap", "odp", "hfc_node", "pon_port"]
    technology: Technology
    site_id: str
    serves_households: int
    parent_id: str | None = None
    assumed: bool = True

    @property
    def is_delimiter(self) -> bool:
        """Taps and ODPs are the responsibility boundary an MR is raised against."""
        return self.kind in {"tap", "odp"}

    @property
    def crew_type(self) -> str:
        return "clean" if self.kind in {"household", "drop"} else "dirty"


def _ratio(table_key: str, archetype: str) -> int:
    return int(PLANT_ASSUMPTIONS[table_key][archetype])  # type: ignore[index]


def site_plant(site: Site) -> dict[str, int]:
    """Assumed element counts for one site."""
    homes = households(site)
    pon_share = float(PLANT_ASSUMPTIONS["pon_share_by_archetype"][site.archetype])  # type: ignore[index]
    pon_homes = int(round(homes * pon_share))
    hfc_homes = homes - pon_homes
    return {
        "households": homes,
        "hfc_households": hfc_homes,
        "pon_households": pon_homes,
        "taps": max(1, -(-hfc_homes // _ratio("homes_per_tap", site.archetype))),
        "odps": max(1, -(-pon_homes // _ratio("homes_per_odp", site.archetype))),
        "hfc_nodes": max(1, -(-hfc_homes // int(PLANT_ASSUMPTIONS["homes_per_hfc_node"]))),
        "pon_ports": max(1, -(-pon_homes // int(PLANT_ASSUMPTIONS["homes_per_pon_port"]))),
    }


def footprint_totals() -> dict[str, int]:
    totals: dict[str, int] = {}
    for site in sites_in_cpe_footprint():
        for key, value in site_plant(site).items():
            totals[key] = totals.get(key, 0) + value
    return totals


def delimiter_for(site_id: str, technology: Technology, index: int = 0) -> PlantElement:
    """The tap or ODP an MR would be raised against at this site."""
    site = SITE_BY_ID[site_id]
    short = site_id.split("-", 1)[1]
    if technology == "HFC":
        return PlantElement(
            element_id=f"TAP-{short}-{_seq(site_id, 'tap', index)}",
            kind="tap", technology="HFC", site_id=site_id,
            serves_households=_ratio("homes_per_tap", site.archetype),
            parent_id=f"NODE-{short}-{_seq(site_id, 'node', index // 60)}")
    return PlantElement(
        element_id=f"ODP-{short}-{_seq(site_id, 'odp', index)}",
        kind="odp", technology="PON", site_id=site_id,
        serves_households=_ratio("homes_per_odp", site.archetype),
        parent_id=f"OLTPORT-{short}-{_seq(site_id, 'pon_port', index // 4)}")


def chain_for(site_id: str, technology: Technology, index: int = 0) -> list[PlantElement]:
    """Household up to the delimiter, which is what an RCA has to choose between."""
    site = SITE_BY_ID[site_id]
    short = site_id.split("-", 1)[1]
    delimiter = delimiter_for(site_id, technology, index)
    household = PlantElement(
        element_id=f"HH-{short}-{_seq(site_id, 'hh', index)}",
        kind="household", technology=technology, site_id=site_id,
        serves_households=1, parent_id=f"DROP-{short}-{_seq(site_id, 'drop', index)}")
    drop = PlantElement(
        element_id=household.parent_id or "",
        kind="drop", technology=technology, site_id=site_id,
        serves_households=1, parent_id=delimiter.element_id)
    upstream = PlantElement(
        element_id=delimiter.parent_id or "",
        kind="hfc_node" if technology == "HFC" else "pon_port",
        technology=technology, site_id=site_id,
        serves_households=(int(PLANT_ASSUMPTIONS["homes_per_hfc_node"])
                           if technology == "HFC"
                           else int(PLANT_ASSUMPTIONS["homes_per_pon_port"])))
    return [household, drop, delimiter, upstream]


# Which plant element each responsibility domain implicates.
DOMAIN_TO_KIND: dict[str, str] = {
    "cpe": "household", "wifi_or_home": "household", "premise_wiring": "household",
    "drop": "drop", "hfc_tap": "tap", "pon_odp": "odp",
    "plant": "hfc_node", "shared_network": "hfc_node", "provisioning": "household",
    "unknown": "household",
}


def blast_radius(domain: str, site_id: str, technology: Technology) -> int:
    """Households affected if this domain is the true cause.

    This is the number that makes a tap fault operationally different from a drop
    fault: one household versus the whole tap.
    """
    kind = DOMAIN_TO_KIND.get(domain, "household")
    for element in chain_for(site_id, technology):
        if element.kind == kind:
            return element.serves_households
    if kind in {"hfc_node", "pon_port"}:
        return int(PLANT_ASSUMPTIONS["homes_per_hfc_node"] if technology == "HFC"
                   else PLANT_ASSUMPTIONS["homes_per_pon_port"])
    return 1
