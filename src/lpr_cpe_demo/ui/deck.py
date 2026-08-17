"""pydeck layer construction against the real Python API.

Why this exists
---------------
An earlier version handed deck.gl a JSON specification via `pdk.Deck.from_json`.
That method does not exist in the installed pydeck, so the map failed with
`type object 'Deck' has no attribute 'from_json'` and the page fell back to the
offline schematic. Layers are now built with `pdk.Layer(...)`, which is the
supported API.

Each layer is constructed defensively: if one raises, it is skipped and the rest
still render. A missing label layer is better than a missing map.
"""

from __future__ import annotations

from typing import Any

from ..geo_layers import (FAULT_TOOLTIP, INITIAL_VIEW, TILE_URL,
                          ferry_leg_records, hub_core_records,
                          hub_label_records, hub_ring_records,
                          premise_link_records, road_leg_records, fault_records,
                          marker_records, site_records)


def _try(build) -> Any | None:
    try:
        return build()
    except Exception:
        return None


def tile(pdk, tile_url: str = TILE_URL):
    return pdk.Layer("TileLayer", data=tile_url, min_zoom=0, max_zoom=19,
                     tile_size=256, pickable=False)


def hub_layers(pdk) -> list[Any]:
    """A depot symbol: white ring with a dark edge, dark core, code above."""
    out = []
    ring = _try(lambda: pdk.Layer(
        "ScatterplotLayer", data=hub_ring_records(), get_position="position",
        get_fill_color="fill", get_line_color="edge", get_radius="radius",
        radius_min_pixels=9, radius_max_pixels=20, stroked=True, filled=True,
        line_width_min_pixels=2, pickable=True))
    core = _try(lambda: pdk.Layer(
        "ScatterplotLayer", data=hub_core_records(), get_position="position",
        get_fill_color="colour", get_radius="radius", radius_min_pixels=3,
        radius_max_pixels=7, pickable=False))
    label = _try(lambda: pdk.Layer(
        "TextLayer", data=hub_label_records(), get_position="position",
        get_text="label", get_color="colour", get_size=13,
        get_pixel_offset=[0, -20], get_text_anchor="'middle'",
        get_alignment_baseline="'bottom'", font_weight="bold", pickable=False))
    return [layer for layer in (ring, core, label) if layer is not None]


def fault_layers(pdk, faults, *, show_routes: bool = True,
                 router: Any | None = None) -> list[Any]:
    out: list[Any] = []

    links = _try(lambda: pdk.Layer(
        "PathLayer", data=premise_link_records(faults), get_path="path",
        get_color="colour", get_width=180, width_min_pixels=1, pickable=True))
    if links:
        out.append(links)

    if show_routes:
        road = _try(lambda: pdk.Layer(
            "PathLayer", data=road_leg_records(faults, router), get_path="path",
            get_color="colour", get_width=420, width_min_pixels=2, pickable=True))
        if road:
            out.append(road)
        ferry = _try(lambda: pdk.Layer(
            "ArcLayer", data=ferry_leg_records(faults),
            get_source_position="source", get_target_position="target",
            get_source_color="colour", get_target_color="colour",
            get_width=3, get_height=0.35, pickable=True))
        if ferry:
            out.append(ferry)

    out.extend(hub_layers(pdk))

    pins = _try(lambda: pdk.Layer(
        "ScatterplotLayer", data=fault_records(faults), get_position="position",
        get_fill_color="colour", get_radius="radius", radius_min_pixels=5,
        radius_max_pixels=24, stroked=True, line_width_min_pixels=1,
        get_line_color=[252, 251, 250, 230], pickable=True))
    if pins:
        out.append(pins)
    return out


def footprint_layers(pdk, *, route_path: dict[str, Any] | None = None) -> list[Any]:
    out: list[Any] = []
    if route_path is not None:
        route = _try(lambda: pdk.Layer(
            "PathLayer", data=[route_path], get_path="path", get_color="colour",
            get_width=600, width_min_pixels=3, pickable=True))
        if route:
            out.append(route)

    sites = _try(lambda: pdk.Layer(
        "ScatterplotLayer", data=site_records(), get_position="position",
        get_fill_color="colour", get_radius="radius", radius_min_pixels=4,
        radius_max_pixels=13, stroked=True, line_width_min_pixels=1,
        get_line_color=[252, 251, 250, 255], pickable=True))
    if sites:
        out.append(sites)

    markers = _try(lambda: pdk.Layer(
        "ScatterplotLayer", data=marker_records(), get_position="position",
        get_fill_color="colour", get_radius="radius", radius_min_pixels=7,
        radius_max_pixels=16, stroked=True, line_width_min_pixels=2,
        get_line_color=[252, 251, 250, 255], pickable=True))
    if markers:
        out.append(markers)

    out.extend(hub_layers(pdk))
    return out


def deck(pdk, layers: list[Any], *, tooltip: dict[str, Any] | None = None,
         tile_url: str = TILE_URL):
    """Basemap first, then the supplied layers. No Mapbox or Carto basemap."""
    return pdk.Deck(
        layers=[tile(pdk, tile_url), *layers],
        initial_view_state=pdk.ViewState(**INITIAL_VIEW),
        map_provider=None,
        map_style=None,
        tooltip=tooltip or FAULT_TOOLTIP,
    )
