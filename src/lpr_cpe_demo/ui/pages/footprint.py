"""Footprint and dispatch page.

Renders an OpenStreetMap basemap with sites, assumed dispatch hubs, the core
site, the ferry terminal and the selected dispatch route.

Three rendering tiers, so the page degrades rather than breaking:
  1. pydeck with an OSM TileLayer. pydeck ships with Streamlit, no extra install.
  2. folium via streamlit-folium, if the optional [map] extra is present.
  3. the generated SVG schematic, which needs no network at all.

Tiles are fetched by the browser, not the container, so a restricted container
network does not stop this working. A browser that cannot reach
tile.openstreetmap.org will show markers over an empty basemap, which is what the
SVG fallback is for.
"""

from __future__ import annotations

import pathlib

import streamlit as st

from lpr_cpe_demo.geo_layers import (OSM_ATTRIBUTION, OSM_POLICY_URL,
                                     ROUTE_CAVEAT, TILE_URL,
                                     dispatch_route, ferry_arcs,
                                     hub_records, marker_records,
                                     site_records)
from lpr_cpe_demo.geography import (DISPATCH_BASES, SITE_BY_ID, assumed_bases,
                                    core_sites, ferry_terminals,
                                    sites_in_cpe_footprint)

ASSETS = pathlib.Path(__file__).resolve().parents[1] / "assets"
SVG = ASSETS / "footprint_map.svg"


def _renderers() -> list[str]:
    available = []
    try:
        import pydeck  # noqa: F401
        available.append("OpenStreetMap (pydeck)")
    except Exception:
        pass
    try:
        import folium  # noqa: F401
        from streamlit_folium import st_folium  # noqa: F401
        available.append("OpenStreetMap (folium)")
    except Exception:
        pass
    if SVG.exists():
        available.append("Schematic SVG (offline)")
    return available


def _render_pydeck(route_path) -> None:
    import pydeck as pdk

    from lpr_cpe_demo.geo_layers import SITE_TOOLTIP
    from lpr_cpe_demo.ui import deck as deckbuild

    layers = deckbuild.footprint_layers(pdk, route_path=route_path)
    st.pydeck_chart(deckbuild.deck(pdk, layers, tooltip=SITE_TOOLTIP),
                    use_container_width=True)


def _render_folium(route_path) -> None:
    import folium
    from streamlit_folium import st_folium

    fmap = folium.Map(location=[INITIAL_VIEW["latitude"], INITIAL_VIEW["longitude"]],
                      zoom_start=9, tiles=TILE_URL, attr=OSM_ATTRIBUTION)
    for rec in site_records():
        folium.CircleMarker(
            [rec["lat"], rec["lon"]], radius=5,
            color="#FCFBFA", weight=1, fill=True, fill_opacity=0.9,
            fill_color="#%02x%02x%02x" % tuple(rec["colour"][:3]),
            tooltip=f"{rec['name']} — {rec['archetype']} — {rec['technologies']}",
        ).add_to(fmap)
    for rec in marker_records():
        folium.CircleMarker([rec["lat"], rec["lon"]], radius=9, color="#5A5A5A",
                            weight=2, fill=False, dash_array="4",
                            tooltip=f"{rec['name']} — {rec['role']}. {rec['detail']}"
                            ).add_to(fmap)
    for rec in hub_records():
        folium.Marker(
            [rec["lat"], rec["lon"]],
            icon=folium.Icon(color="darkgreen",
                             icon="wrench" if rec["likelihood"] == "very_high" else "info-sign"),
            tooltip=f"{rec['name']} — likelihood {rec['likelihood']}",
            popup=folium.Popup(f"<b>{rec['name']}</b><br/>{rec['rationale']}"
                               f"<br/><i>{rec['basis']}</i>", max_width=280),
        ).add_to(fmap)
    for arc in ferry_arcs():
        folium.PolyLine([[arc["from_lat"], arc["from_lon"]], [arc["to_lat"], arc["to_lon"]]],
                        color="#8F7D62", weight=2.5, dash_array="6",
                        tooltip=arc["label"]).add_to(fmap)
    if route_path:
        folium.PolyLine([[lat, lon] for lon, lat in route_path["path"]],
                        color="#0C5457", weight=4, opacity=0.85,
                        tooltip=route_path["label"]).add_to(fmap)
    st_folium(fmap, height=520, use_container_width=True, returned_objects=[])


def render() -> None:
    from lpr_cpe_demo.ui import theme

    st.markdown(
        theme.header("Footprint and dispatch",
                     "Puerto Rico fixed CPE footprint, assumed dispatch "
                     "hubs, and what a location costs to reach."),
        unsafe_allow_html=True)

    st.warning(
        "**Hub locations are assumed.** Liberty does not publish operations-centre "
        "locations, so nothing here is a confirmed facility address. The hub set and "
        "the likelihood ratings come from a practitioner assessment, which is expert "
        "judgement rather than published fact. Replace these with actual facility "
        "locations, crew rosters and van stock before operational use.\n\n"
        "San Juan is modelled as a **core site** (headend and NOC), not a dispatch "
        "hub. Fajardo is modelled as a **ferry terminal** that island work is driven "
        "to, not a hub.",
        icon="⚠️",
    )

    available = _renderers()
    if not available:
        st.error("No map renderer available. Run scripts/generate_footprint_map.py "
                 "for the offline schematic.")
        return

    controls, detail = st.columns([2, 1])

    with detail:
        st.subheader("Dispatch check")
        sites = sorted(sites_in_cpe_footprint(), key=lambda s: s.municipio)
        site = st.selectbox("Site", sites,
                            format_func=lambda s: f"{s.municipio} — {s.archetype}")
        needs_splice = st.checkbox("Fault needs a fibre splice")
        renderer = st.selectbox("Basemap", available)

        try:
            route = dispatch_route(
                site, crew_type="dirty",
                required_skills=("fibre_splice",) if needs_splice else (),
                required_parts=("splice_kit",) if needs_splice else ())
        except LookupError as exc:
            st.error(str(exc))
            route = None
        else:
            sel = route["selection"]
            st.metric("Staged from", sel.base.base_id.replace("BASE-", ""))
            st.metric("One-way travel", f"{sel.plan.total_minutes} min")
            st.metric("Fits one shift", "yes" if sel.plan.same_day_feasible else "no")
            for leg in sel.plan.legs:
                st.caption(f"**{leg.kind}** {leg.minutes} min — {leg.description}")
            if not sel.plan.same_day_feasible:
                st.error("A round trip plus on-site work exceeds one shift. Needs an "
                         "overnight plan or a pre-positioned crew.", icon="⏱")
            if sel.rejected_for_parts:
                st.caption(f"Nearer hub(s) rejected for missing parts: "
                           f"{', '.join(sel.rejected_for_parts)}")

    with controls:
        path = route["path_record"] if route else None
        if renderer.endswith("(pydeck)"):
            try:
                _render_pydeck(path)
            except Exception as exc:
                st.warning(f"pydeck could not render ({type(exc).__name__}: {exc}). "
                           f"Showing the offline schematic.")
                st.image(str(SVG), use_container_width=True)
        elif renderer.endswith("(folium)"):
            _render_folium(path)
        else:
            st.image(str(SVG), use_container_width=True)

        st.caption(ROUTE_CAVEAT)
        st.caption(
            f"Basemap {OSM_ATTRIBUTION}. Tiles are fetched by your browser, not by the "
            f"container. The public OSM tile service has a usage policy "
            f"({OSM_POLICY_URL}); substitute an internal or commercial tile service for "
            f"anything beyond a demo. Marker coordinates are approximate municipio "
            f"centroids."
        )

    st.subheader("Assumed dispatch hubs")
    st.dataframe(
        [{"hub": h["short"], "name": h["name"], "likelihood": h["likelihood"].replace("_", " "),
          "crews": h["crews"], "splice kit": h["splice_kit"], "rationale": h["rationale"]}
         for h in hub_records()],
        hide_index=True, use_container_width=True)
    st.caption(
        f"{len(assumed_bases())} of {len(DISPATCH_BASES)} hub locations are assumptions. "
        f"Core sites: {', '.join(s.municipio for s in core_sites())}. "
        f"Ferry terminals: {', '.join(s.municipio for s in ferry_terminals())}. "
        f"Fixed HFC and PON footprint is Puerto Rico; USVI is mobile under LPR and "
        f"excluded here.")
