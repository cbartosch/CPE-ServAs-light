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


def layer_specs(*, route_path: dict[str, Any] | None = None,
                tile_url: str = TILE_URL) -> list[dict[str, Any]]:
    """Full layer stack, basemap first so markers draw above it."""
    layers: list[dict[str, Any]] = [tile_layer(tile_url)]

    layers.append({
        "@@type": "ArcLayer", "id": "ferry", "data": ferry_arcs(),
        "getSourcePosition": "@@=[from_lon, from_lat]",
        "getTargetPosition": "@@=[to_lon, to_lat]",
        "getSourceColor": "@@=colour", "getTargetColor": "@@=colour",
        "getWidth": 2.5, "pickable": True,
    })

    if route_path is not None:
        layers.append({
            "@@type": "PathLayer", "id": "route", "data": [route_path],
            "getPath": "@@=path", "getColor": "@@=colour",
            "getWidth": 900, "widthMinPixels": 3, "pickable": True,
        })

    layers.append({
        "@@type": "ScatterplotLayer", "id": "sites", "data": site_records(),
        "getPosition": "@@=[lon, lat]", "getFillColor": "@@=colour",
        "getRadius": "@@=radius", "radiusMinPixels": 4, "radiusMaxPixels": 14,
        "stroked": True, "lineWidthMinPixels": 1,
        "getLineColor": [252, 251, 250, 255], "pickable": True,
    })

    layers.append({
        "@@type": "ScatterplotLayer", "id": "markers", "data": marker_records(),
        "getPosition": "@@=[lon, lat]", "getFillColor": "@@=colour",
        "getRadius": "@@=radius", "radiusMinPixels": 7, "radiusMaxPixels": 18,
        "stroked": True, "lineWidthMinPixels": 2,
        "getLineColor": [252, 251, 250, 255], "pickable": True,
    })

    layers.append({
        "@@type": "ScatterplotLayer", "id": "hubs", "data": hub_records(),
        "getPosition": "@@=[lon, lat]", "getFillColor": "@@=colour",
        "getRadius": "@@=radius", "radiusMinPixels": 8, "radiusMaxPixels": 22,
        "stroked": True, "lineWidthMinPixels": 2,
        "getLineColor": [252, 251, 250, 255], "pickable": True,
    })
    return layers


SITE_TOOLTIP = {
    "html": "<b>{name}</b><br/>{region}<br/>{archetype}<br/>{technologies}",
    "style": {"backgroundColor": "#0C5457", "color": "white", "fontSize": "12px"},
}
HUB_TOOLTIP = {
    "html": ("<b>{name}</b><br/>likelihood: {likelihood}<br/>{rationale}"
             "<br/><i>{basis}</i>"),
    "style": {"backgroundColor": "#0C5457", "color": "white", "fontSize": "12px"},
}
