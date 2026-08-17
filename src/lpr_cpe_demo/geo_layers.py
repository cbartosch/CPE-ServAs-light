"""Interactive map layers over an OpenStreetMap basemap.

Why this module exists separately from the UI
---------------------------------------------
Everything here returns plain dictionaries. That keeps the layer construction
testable with the standard library alone, in the same container as the rest of
the core, rather than only being exercisable by clicking around a running
Streamlit app.

Rendering strategy, in preference order
---------------------------------------
1. ``pydeck`` with an OSM raster ``TileLayer``. pydeck is already a Streamlit
   dependency, so this adds nothing to install.
2. ``folium`` via ``streamlit-folium``, if the optional ``[map]`` extra is
   installed. Better popups, but two extra packages.
3. The generated SVG schematic in ``ui/assets/footprint_map.svg``, which needs no
   network at all.

Tiles are fetched by the **browser**, not by the container, so a locked-down
container network does not prevent this from working. A browser that cannot reach
``tile.openstreetmap.org`` will show an empty basemap with the markers still
drawn, which is why the SVG fallback is kept.

Attribution
-----------
OSM requires visible attribution and its tile usage policy discourages heavy or
commercial use of the public tile servers. ``OSM_ATTRIBUTION`` is rendered by the
UI, and ``TILE_URL`` is configurable so an internal or commercial tile service can
be substituted for anything beyond a demo.
"""

from __future__ import annotations

from typing import Any

from .geography import (DISPATCH_BASES, SITE_BY_ID, Site, core_sites,
                        ferry_terminals, select_base, sites_in_cpe_footprint)

TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
OSM_ATTRIBUTION = "© OpenStreetMap contributors"
OSM_POLICY_URL = "https://operations.osmfoundation.org/policies/tiles/"

# Puerto Rico, framed to include Vieques and Culebra.
INITIAL_VIEW: dict[str, float] = {
    "latitude": 18.22, "longitude": -66.35, "zoom": 8.1, "pitch": 0, "bearing": 0,
}

# RGBA. Same semantics as the SVG schematic so the two views agree.
ARCHETYPE_RGBA: dict[str, list[int]] = {
    "metro":         [12, 84, 87, 220],
    "coastal":       [24, 168, 175, 220],
    "mountain":      [143, 125, 98, 220],
    "remote_island": [138, 124, 106, 230],
}
HUB_RGBA = [12, 84, 87, 245]
CORE_RGBA = [90, 90, 90, 200]
TERMINAL_RGBA = [143, 125, 98, 245]
FERRY_LINE_RGBA = [143, 125, 98, 200]
ROUTE_RGBA = [12, 84, 87, 210]


def tile_layer(url: str = TILE_URL) -> dict[str, Any]:
    """OSM raster basemap. `map_provider` must be None so deck.gl adds no other."""
    return {
        "@@type": "TileLayer",
        "data": url,
        "minZoom": 0,
        "maxZoom": 19,
        "tileSize": 256,
        "pickable": False,
    }


def site_records() -> list[dict[str, Any]]:
    out = []
    for s in sites_in_cpe_footprint():
        out.append({
            "site_id": s.site_id,
            "name": s.municipio,
            "region": s.region,
            "archetype": s.archetype,
            "technologies": ", ".join(s.technologies),
            "island": s.island,
            "lat": s.lat,
            "lon": s.lon,
            "position": [s.lon, s.lat],
            "colour": ARCHETYPE_RGBA[s.archetype],
            "radius": 2600 if s.island else 2000,
        })
    return out


def hub_records() -> list[dict[str, Any]]:
    return [{
        "base_id": b.base_id,
        "short": b.base_id.replace("BASE-", ""),
        "name": b.name,
        "likelihood": b.likelihood,
        "rationale": b.rationale,
        "basis": b.basis,
        "crews": ", ".join(b.crew_types),
        "splice_kit": "yes" if "splice_kit" in b.van_stock else "no",
        "lat": b.lat,
        "lon": b.lon,
        "position": [b.lon, b.lat],
        "colour": HUB_RGBA,
        # A very-high-likelihood hub reads larger, matching the filled marker in
        # the SVG schematic.
        "radius": 5200 if b.likelihood == "very_high" else 3800,
    } for b in DISPATCH_BASES]


def marker_records() -> list[dict[str, Any]]:
    """Core sites and ferry terminals, which are deliberately not hubs."""
    out = []
    for s in core_sites():
        out.append({"name": s.municipio, "role": "Core site: headend and NOC",
                    "detail": "Not a dispatch hub", "lat": s.lat, "lon": s.lon,
                    "colour": CORE_RGBA, "radius": 4200})
    for s in ferry_terminals():
        out.append({"name": s.municipio, "role": "Ferry terminal",
                    "detail": "Island work is driven here from a mainland hub",
                    "lat": s.lat, "lon": s.lon,
                    "position": [s.lon, s.lat],
                    "colour": TERMINAL_RGBA, "radius": 4200})
    return out


def ferry_arcs() -> list[dict[str, Any]]:
    out = []
    for terminal in ferry_terminals():
        for site in sites_in_cpe_footprint():
            if site.island and site.ferry_from == terminal.site_id:
                out.append({
                    "from_lon": terminal.lon, "from_lat": terminal.lat,
                    "to_lon": site.lon, "to_lat": site.lat,
                    "label": f"Ferry {terminal.municipio} to {site.municipio}",
                    "colour": FERRY_LINE_RGBA,
                })
    return out


def dispatch_route(site: Site, *, crew_type: str = "dirty",
                   required_skills: tuple[str, ...] = (),
                   required_parts: tuple[str, ...] = ()) -> dict[str, Any]:
    """Path from the selected hub to the site, via the terminal when islanded."""
    sel = select_base(site, crew_type=crew_type, required_skills=required_skills,
                      required_parts=required_parts)
    path = [[sel.base.lon, sel.base.lat]]
    if sel.plan.requires_ferry and site.ferry_from:
        terminal = SITE_BY_ID[site.ferry_from]
        path.append([terminal.lon, terminal.lat])
    path.append([site.lon, site.lat])
    return {
        "selection": sel,
        "path_record": {
            "path": path,
            "colour": ROUTE_RGBA,
            "label": (f"{sel.base.name} to {site.municipio}, "
                      f"{sel.plan.total_minutes} min one way"),
        },
    }



# Cost bands for fault pins, USD. Colour carries cost so an expensive job is
# visible without reading the table.
COST_BANDS: tuple[tuple[float, list[int], str], ...] = (
    (100.0, [24, 168, 175, 220], "under 100"),
    (400.0, [143, 125, 98, 230], "100 to 400"),
    (900.0, [180, 110, 60, 235], "400 to 900"),
    (float("inf"), [168, 60, 50, 245], "over 900"),
)


def cost_colour(cost_usd: float) -> list[int]:
    for ceiling, rgba, _ in COST_BANDS:
        if cost_usd < ceiling:
            return rgba
    return list(COST_BANDS[-1][1])


def cost_radius(cost_usd: float) -> int:
    """Area roughly proportional to cost, floored so cheap jobs stay visible."""
    return int(900 + 90 * (max(cost_usd, 40.0) ** 0.5))


def fault_records(faults) -> list[dict[str, object]]:
    """Pins at the INTERVENTION point, not the customer address."""
    out = []
    for f in faults:
        out.append({
            "fault_id": f.fault_id,
            "municipio": f.municipio,
            "technology": f.technology,
            "domain": f.true_domain,
            "priority": f.priority,
            "intervention_kind": f.intervention_kind,
            "intervention_id": f.intervention_id,
            "at": "premise" if f.intervention_is_at_premise else "plant",
            "households": f.households_affected,
            "crew": f.crew_type,
            "base": f.base_id.replace("BASE-", ""),
            "minutes": f.total_minutes,
            "cost": f.total_cost_usd,
            "cost_label": f"${f.total_cost_usd:,.0f}",
            "if_missed": f.misdispatch_cost_usd,
            "lat": f.intervention_lat,
            "lon": f.intervention_lon,
            "position": [f.intervention_lon, f.intervention_lat],
            "colour": cost_colour(f.total_cost_usd),
            "radius": cost_radius(f.total_cost_usd),
        })
    return out


def premise_link_records(faults) -> list[dict[str, object]]:
    """Household to intervention point, drawn only when they differ.

    This is the line that shows a tap fault is not worked at the address that
    reported it.
    """
    out = []
    for f in faults:
        if f.intervention_is_at_premise:
            continue
        out.append({
            "path": [[f.household_lon, f.household_lat],
                     [f.intervention_lon, f.intervention_lat]],
            "label": (f"{f.household_id} reported it; work happens at "
                      f"{f.intervention_id} serving {f.households_affected} households"),
            "colour": [120, 120, 120, 180],
        })
    return out


def fault_route_records(faults) -> list[dict[str, object]]:
    """Dispatch base to the intervention point, via the ferry terminal if islanded."""
    out = []
    for f in faults:
        if f.truck_rolls == 0:
            continue
        base = next((b for b in DISPATCH_BASES if b.base_id == f.base_id), None)
        if base is None:
            continue
        path = [[base.lon, base.lat]]
        site = SITE_BY_ID[f.site_id]
        if f.requires_ferry and site.ferry_from:
            terminal = SITE_BY_ID[site.ferry_from]
            path.append([terminal.lon, terminal.lat])
        path.append([f.intervention_lon, f.intervention_lat])
        out.append({
            "path": path,
            "label": (f"{f.fault_id}: {base.name} to {f.intervention_id}, "
                      f"{f.travel_minutes} min each way"),
            "colour": [12, 84, 87, 170],
        })
    return out



# ------------------------------------------------------------- hub rendering
# A single filled circle reads as a blotch at this zoom. A depot reads as a
# white-filled ring with a dark core and its code above it, which is legible
# against both land and water and stays distinguishable from a fault pin.
HUB_RING_RGBA = [252, 251, 250, 255]
HUB_EDGE_RGBA = [12, 84, 87, 255]
HUB_CORE_RGBA = [12, 84, 87, 255]
HUB_LABEL_RGBA = [12, 84, 87, 255]


def hub_ring_records() -> list[dict[str, Any]]:
    out = []
    for b in DISPATCH_BASES:
        very_high = b.likelihood == "very_high"
        out.append({
            "position": [b.lon, b.lat],
            "short": b.base_id.replace("BASE-", ""),
            "name": b.name,
            "likelihood": b.likelihood.replace("_", " "),
            "rationale": b.rationale,
            "basis": b.basis,
            "fill": HUB_RING_RGBA,
            "edge": HUB_EDGE_RGBA,
            # very-high hubs read larger, matching the SVG schematic
            "radius": 4200 if very_high else 3200,
            "edge_width": 3 if very_high else 2,
        })
    return out


def hub_core_records() -> list[dict[str, Any]]:
    """Filled centre only on very-high-likelihood hubs."""
    return [{"position": [b.lon, b.lat], "colour": HUB_CORE_RGBA, "radius": 1500}
            for b in DISPATCH_BASES if b.likelihood == "very_high"]


def hub_label_records() -> list[dict[str, Any]]:
    return [{"position": [b.lon, b.lat], "label": b.base_id.replace("BASE-", ""),
             "colour": HUB_LABEL_RGBA} for b in DISPATCH_BASES]


# ------------------------------------------------------------- route legs
# Road and ferry legs are separated so the ferry hop is visually distinct: a road
# leg is a line on the ground, a ferry leg is an arc over water.
#
# HONEST LIMIT: road legs are straight lines between hub, terminal and
# intervention point. They are not road geometry. Road-accurate routing needs a
# routing service (OSRM, Valhalla or a commercial API), which this container
# cannot reach. The travel MINUTES are not straight-line, though: they come from
# the archetype road-speed model with a detour factor, so the number is a better
# estimate than the drawn line suggests.
ROAD_LEG_RGBA = [12, 84, 87, 200]
FERRY_LEG_RGBA = [143, 125, 98, 230]


def road_leg_records(faults, router=None) -> list[dict[str, Any]]:
    """Land legs only. Pass a `routing.Router` to snap them to real roads.

    With no router, geometry is the two endpoints and `on_roads` is False, which
    the caption reports honestly. With an OSRM router, geometry is the road path
    and the label carries the routed distance and duration.
    """
    out = []
    for f in faults:
        if not f.truck_rolls:
            continue
        base = next((b for b in DISPATCH_BASES if b.base_id == f.base_id), None)
        if base is None:
            continue
        site = SITE_BY_ID[f.site_id]
        if f.requires_ferry and site.ferry_from:
            terminal = SITE_BY_ID[site.ferry_from]
            start, end = (base.lon, base.lat), (terminal.lon, terminal.lat)
            where = f"the {terminal.municipio} ferry terminal"
        else:
            start, end = (base.lon, base.lat), (f.intervention_lon, f.intervention_lat)
            where = f.intervention_id

        path = [[start[0], start[1]], [end[0], end[1]]]
        on_roads = False
        detail = f"{f.travel_minutes} min each way, modelled"
        if router is not None:
            try:
                route = router.route([start, end])
                path = route.path
                on_roads = route.on_roads
                if on_roads:
                    detail = (f"{route.distance_km} km on roads, "
                              f"{route.duration_min} min routed")
            except Exception:
                pass                  # keep the straight line for this leg only

        out.append({"path": path, "colour": ROAD_LEG_RGBA,
                    "label": f"{f.fault_id} road leg: {base.name} to {where}, {detail}",
                    "on_roads": on_roads})
    return out


def routing_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """How many legs are genuine road geometry, for the caption to state."""
    total = len(records)
    routed = sum(1 for r in records if r.get("on_roads"))
    return {"legs": total, "on_roads": routed,
            "straight_line": total - routed,
            "all_routed": total > 0 and routed == total}


def ferry_leg_records(faults) -> list[dict[str, Any]]:
    out = []
    for f in faults:
        site = SITE_BY_ID[f.site_id]
        if not (f.truck_rolls and f.requires_ferry and site.ferry_from):
            continue
        terminal = SITE_BY_ID[site.ferry_from]
        out.append({
            "source": [terminal.lon, terminal.lat],
            "target": [f.intervention_lon, f.intervention_lat],
            "colour": FERRY_LEG_RGBA,
            "label": (f"{f.fault_id} ferry leg: {terminal.municipio} to "
                      f"{f.municipio}, {f.travel_minutes} min total each way "
                      f"including the mean wait for a sailing"),
        })
    return out


ROUTE_CAVEAT = (
    "Route legs are drawn as straight lines between hub, ferry terminal and "
    "intervention point. They are not road geometry: road-accurate routing needs a "
    "routing service this deployment does not call. Travel minutes are not "
    "straight-line, though, and come from the archetype road-speed model with a "
    "detour factor applied."
)

FAULT_TOOLTIP = {
    "html": ("<b>{fault_id}</b> {priority}<br/>{municipio} — {technology}<br/>"
             "domain: {domain}<br/>intervention: {intervention_id} ({at})<br/>"
             "{households} household(s) affected<br/>{crew} boots from {base}<br/>"
             "<b>{cost_label}</b> · {minutes} min"),
    "style": {"backgroundColor": "#0C5457", "color": "white", "fontSize": "12px"},
}

SITE_TOOLTIP = {
    "html": "<b>{name}</b><br/>{region}<br/>{archetype}<br/>{technologies}",
    "style": {"backgroundColor": "#0C5457", "color": "white", "fontSize": "12px"},
}
