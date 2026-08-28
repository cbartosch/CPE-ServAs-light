"""Footprint and dispatch inputs linked to the active Digital Twin run.

The default view selects a generated demo case and uses its service, technology,
delimiter, RCA, action, work-order skill/parts and generated timestamps as the
inputs to dispatch staging. The legacy manual footprint check remains available
as an explicit assumptions-only mode.
"""

from __future__ import annotations

import pathlib
from typing import Any

import streamlit as st

from lpr_cpe_demo.geo_layers import (
    INITIAL_VIEW,
    OSM_ATTRIBUTION,
    OSM_POLICY_URL,
    ROUTE_CAVEAT,
    SITE_TOOLTIP,
    TILE_URL,
    dispatch_route,
    ferry_arcs,
    hub_records,
    marker_records,
    site_records,
)
from lpr_cpe_demo.geography import (
    DISPATCH_BASES,
    assumed_bases,
    core_sites,
    ferry_terminals,
    sites_in_cpe_footprint,
)
from lpr_cpe_demo.ui.client import APIError
from lpr_cpe_demo.ui.common import digital_twin_api

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


def _selected_marker(case: dict[str, Any] | None) -> dict[str, Any] | None:
    if case is None:
        return None
    return {
        "position": [case["intervention_lon"], case["intervention_lat"]],
        "colour": [251, 191, 36, 245],
        "radius": 5_600,
        "name": case["case_id"],
        "region": (
            f"{case['scenario']} · {case['executed_or_forecast_action']} · "
            f"{case['action_status']}"
        ),
        "archetype": (
            f"{case['municipio']} · {case['recommended_domain']} · "
            f"{case['intervention_id']}"
        ),
        "technologies": f"{case['technology']} · {case['crew_type']} crew",
    }


def _render_pydeck(
    route_path: dict[str, Any] | None,
    selected_case: dict[str, Any] | None,
) -> None:
    import pydeck as pdk

    from lpr_cpe_demo.ui import deck as deckbuild

    layers = deckbuild.footprint_layers(
        pdk,
        route_path=route_path,
        selected_case=_selected_marker(selected_case),
    )
    st.pydeck_chart(
        deckbuild.deck(pdk, layers, tooltip=SITE_TOOLTIP),
        use_container_width=True,
    )


def _render_folium(
    route_path: dict[str, Any] | None,
    selected_case: dict[str, Any] | None,
) -> None:
    import folium
    from streamlit_folium import st_folium

    fmap = folium.Map(
        location=[INITIAL_VIEW["latitude"], INITIAL_VIEW["longitude"]],
        zoom_start=9,
        tiles=TILE_URL,
        attr=OSM_ATTRIBUTION,
    )
    for record in site_records():
        red, green, blue = record["colour"][:3]
        folium.CircleMarker(
            [record["lat"], record["lon"]],
            radius=5,
            color="#FCFBFA",
            weight=1,
            fill=True,
            fill_opacity=0.9,
            fill_color=f"#{red:02x}{green:02x}{blue:02x}",
            tooltip=(
                f"{record['name']} — {record['archetype']} — "
                f"{record['technologies']}"
            ),
        ).add_to(fmap)
    for record in marker_records():
        folium.CircleMarker(
            [record["lat"], record["lon"]],
            radius=9,
            color="#5A5A5A",
            weight=2,
            fill=False,
            dash_array="4",
            tooltip=f"{record['name']} — {record['role']}. {record['detail']}",
        ).add_to(fmap)
    for record in hub_records():
        folium.Marker(
            [record["lat"], record["lon"]],
            icon=folium.Icon(
                color="darkgreen",
                icon=(
                    "wrench"
                    if record["likelihood"] == "very_high"
                    else "info-sign"
                ),
            ),
            tooltip=f"{record['name']} — likelihood {record['likelihood']}",
            popup=folium.Popup(
                f"<b>{record['name']}</b><br/>{record['rationale']}"
                f"<br/><i>{record['basis']}</i>",
                max_width=280,
            ),
        ).add_to(fmap)
    for arc in ferry_arcs():
        folium.PolyLine(
            [
                [arc["from_lat"], arc["from_lon"]],
                [arc["to_lat"], arc["to_lon"]],
            ],
            color="#8F7D62",
            weight=2.5,
            dash_array="6",
            tooltip=arc["label"],
        ).add_to(fmap)
    if route_path:
        folium.PolyLine(
            [[lat, lon] for lon, lat in route_path["path"]],
            color="#0C5457",
            weight=4,
            opacity=0.85,
            tooltip=route_path["label"],
        ).add_to(fmap)
    if selected_case:
        folium.CircleMarker(
            [selected_case["intervention_lat"], selected_case["intervention_lon"]],
            radius=9,
            color="#FCFBFA",
            weight=2,
            fill=True,
            fill_color="#FBBF24",
            fill_opacity=0.95,
            tooltip=(
                f"{selected_case['case_id']} — {selected_case['scenario']} — "
                f"{selected_case['intervention_id']}"
            ),
        ).add_to(fmap)
    st_folium(fmap, height=520, use_container_width=True, returned_objects=[])


def _render_map(
    renderer: str,
    route_path: dict[str, Any] | None,
    selected_case: dict[str, Any] | None,
) -> None:
    if renderer.endswith("(pydeck)"):
        try:
            _render_pydeck(route_path, selected_case)
            return
        except Exception as exc:
            st.warning(
                f"pydeck could not render ({type(exc).__name__}: {exc}). "
                "Showing the offline schematic."
            )
    elif renderer.endswith("(folium)"):
        _render_folium(route_path, selected_case)
        return
    st.image(str(SVG), use_container_width=True)
    if selected_case:
        st.caption(
            "The offline SVG is static; generated case and route markers are shown "
            "only in the pydeck or folium renderers."
        )


def _map_caption() -> None:
    st.caption(ROUTE_CAVEAT)
    st.caption(
        f"Basemap {OSM_ATTRIBUTION}. Tiles are fetched by the browser. The public "
        f"OSM tile service is governed by {OSM_POLICY_URL}; use an internal or "
        "commercial tile service beyond a demo. Generated subscriber records do not "
        "contain surveyed coordinates, so the active-run location is a deterministic "
        "mapping from generated region and delimiter into approximate municipio "
        "geometry."
    )


def _active_case_label(case: dict[str, Any]) -> str:
    return (
        f"{case['case_id']} — {case['scenario']} — {case['technology']} — "
        f"{case['recommended_domain']} — {case['municipio']}"
    )


def _render_active_dispatch(available: list[str]) -> None:
    try:
        projection = digital_twin_api().dispatch_cost_projection()
    except APIError as exc:
        st.error(
            "The active Digital Twin run could not be loaded. Create or activate a "
            f"demo run first, or select Manual planning inputs. Details: {exc}"
        )
        return

    run_id = str(projection.get("run_id", "active"))
    cases = list(projection.get("cases", []))
    if not cases:
        st.info("The active run contains no generated dispatch/cost cases.")
        return

    st.success(
        f"Dispatch inputs are linked to active demo run **{projection.get('run_id')}**. "
        "Selecting a case below uses its generated service, technology, delimiter, "
        "RCA, action, work-order readiness and MR records."
    )
    st.info(
        "**Location boundary.** The run provides region and network identities but "
        "not surveyed coordinates. The selected municipio and intervention point are "
        "therefore deterministic planning mappings. Hub locations and travel remain "
        "assumptions; generated work-order travel is shown beside the route model. "
        "The planning route contributes to forecast cost only, never to executed cost."
    )
    integrity = projection.get("data_integrity", {})
    if integrity.get("passed"):
        st.caption(
            f"Integrity gate passed: {integrity.get('datasets_verified', 0)} datasets, "
            f"{integrity.get('manifest_cases_verified', 0)} case graphs."
        )

    filters = st.columns([1, 1, 2])
    technologies = ["All", *sorted({str(case["technology"]) for case in cases})]
    technology = filters[0].selectbox(
        "Technology", technologies, key=f"dispatch_technology_{run_id}"
    )
    dispatch_only = filters[1].checkbox(
        "Field-dispatch cases only",
        value=True,
        key=f"dispatch_field_{run_id}",
    )
    scenarios = sorted({str(case["scenario"]) for case in cases})
    selected_scenarios = filters[2].multiselect(
        "Generated scenarios",
        scenarios,
        default=scenarios,
        key=f"dispatch_scenarios_{run_id}",
    )
    filtered = [
        case
        for case in cases
        if (technology == "All" or case["technology"] == technology)
        and (not dispatch_only or int(case["truck_rolls"]) > 0)
        and case["scenario"] in selected_scenarios
    ]
    if not filtered:
        st.info("No generated cases match the current dispatch filters.")
        return

    selection, renderer_column = st.columns([3, 1])
    with selection:
        selected_id = st.selectbox(
            "Generated case",
            [case["case_id"] for case in filtered],
            format_func=lambda case_id: _active_case_label(
                next(case for case in filtered if case["case_id"] == case_id)
            ),
            key=f"dispatch_case_{run_id}",
        )
    with renderer_column:
        renderer = st.selectbox(
            "Basemap", available, key=f"dispatch_basemap_{run_id}"
        )
    case = next(item for item in filtered if item["case_id"] == selected_id)
    route = dict(case.get("route") or {})

    metrics = st.columns(5)
    metrics[0].metric("Mapped municipio", case["municipio"])
    metrics[1].metric(
        "Staged from",
        case["base_id"].replace("BASE-", "") or "No field dispatch",
    )
    metrics[2].metric(
        "Route model",
        f"{case['modelled_route_minutes']} min one way",
    )
    generated_minutes = case.get("generated_route_minutes")
    metrics[3].metric(
        "Generated travel",
        f"{generated_minutes} min" if generated_minutes is not None else "Not executed",
    )
    metrics[4].metric(
        "Fits one shift",
        "Yes" if case["same_day_feasible"] else "No",
    )

    map_column, detail = st.columns([2, 1])
    with map_column:
        _render_map(renderer, route.get("path_record"), case)
        _map_caption()
    with detail:
        st.subheader("Generated dispatch inputs")
        st.write(f"**Run** {case['run_id']}")
        st.write(f"**Incident** {case['incident_id']} ({case['incident_status']})")
        st.write(f"**Case** {case['case_id']} ({case['lifecycle_mode']})")
        st.write(f"**Service / device** {case['service_id']} / {case['device_id']}")
        st.write(f"**Technology** {case['technology']}")
        st.write(f"**Delimiter** {case['delimiter_id']} ({case['delimiter_kind']})")
        st.write(f"**Actual domain** {case['actual_domain']}")
        st.write(f"**Recommended domain** {case['recommended_domain']}")
        st.write(
            f"**Action** {case['executed_or_forecast_action']} "
            f"({case['action_status']})"
        )
        st.write(f"**Intervention** {case['intervention_id']}")
        st.write(f"**Crew** {case['crew_type']}")
        st.write(
            "**Generated skill** "
            + (", ".join(case["generated_required_skills"]) or "Not materialized")
        )
        st.write(
            "**Generated parts** "
            + (", ".join(case["generated_parts_required"]) or "Not materialized")
        )
        st.write(
            "**Staging skill/parts** "
            + ", ".join(
                [
                    *case["dispatch_required_skills"],
                    *case["dispatch_required_parts"],
                ]
            )
        )
        st.caption(
            "Dispatch readiness source: "
            + case["dispatch_readiness_source"].replace("_", " ")
        )
        st.write(
            "**Work order(s)** "
            + (", ".join(case["work_order_ids"]) or "Forecast only")
        )
        st.write("**MR(s)** " + (", ".join(case["mr_ids"]) or "None"))
        st.write(f"**Cost basis** {case['cost_basis'].replace('_', ' ')}")
        if not case.get("execution_economics_complete", True):
            st.warning(
                "Executed cost is incomplete because source work-order economics are "
                "missing: "
                + ", ".join(case.get("execution_economics_missing", []))
            )
        for leg in route.get("legs", []):
            st.caption(
                f"**{leg['kind']}** {leg['minutes']} modelled min — "
                f"{leg['description']}"
            )
        if route.get("rejected_for_skills"):
            st.caption(
                "Nearer hubs rejected for skills: "
                + ", ".join(route["rejected_for_skills"])
            )
        if route.get("rejected_for_parts"):
            st.caption(
                "Nearer hubs rejected for parts: "
                + ", ".join(route["rejected_for_parts"])
            )
        if route.get("warning"):
            st.warning(route["warning"])
        if not case["same_day_feasible"]:
            st.error(
                "A round trip plus the generated/modelled on-site duration exceeds "
                "one shift. Plan an overnight or pre-positioned crew.",
                icon="⏱",
            )
        st.caption(case["location_provenance"])

    st.subheader("All generated dispatch inputs")
    st.dataframe(
        [
            {
                "case": row["case_id"],
                "incident": row["incident_id"],
                "service": row["service_id"],
                "scenario": row["scenario"],
                "technology": row["technology"],
                "municipio": row["municipio"],
                "actual domain": row["actual_domain"],
                "recommended domain": row["recommended_domain"],
                "action": row["executed_or_forecast_action"],
                "status": row["action_status"],
                "crew": row["crew_type"],
                "base": row["base_id"].replace("BASE-", ""),
                "model route min": row["modelled_route_minutes"],
                "generated travel min": row["generated_route_minutes"],
                "cost basis": row["cost_basis"],
                "work order": row["work_order_id"],
                "MR": row["mr_id"],
            }
            for row in filtered
        ],
        hide_index=True,
        use_container_width=True,
    )


def _render_manual_dispatch(available: list[str]) -> None:
    st.warning(
        "**Manual planning inputs.** Hub locations, site coordinates, crew skills and "
        "van stock are assumptions. This mode is independent of the active demo run.",
        icon="⚠️",
    )
    controls, detail = st.columns([2, 1])
    with detail:
        st.subheader("Dispatch check")
        sites = sorted(sites_in_cpe_footprint(), key=lambda site: site.municipio)
        site = st.selectbox(
            "Site",
            sites,
            format_func=lambda item: f"{item.municipio} — {item.archetype}",
        )
        needs_splice = st.checkbox("Fault needs a fibre splice")
        renderer = st.selectbox("Basemap", available, key="manual_basemap")
        try:
            route = dispatch_route(
                site,
                crew_type="dirty",
                required_skills=("fibre_splice",) if needs_splice else (),
                required_parts=("splice_kit",) if needs_splice else (),
            )
        except LookupError as exc:
            st.error(str(exc))
            route = None
        else:
            selected = route["selection"]
            st.metric("Staged from", selected.base.base_id.replace("BASE-", ""))
            st.metric("One-way travel", f"{selected.plan.total_minutes} min")
            st.metric(
                "Fits one shift",
                "Yes" if selected.plan.same_day_feasible else "No",
            )
            for leg in selected.plan.legs:
                st.caption(f"**{leg.kind}** {leg.minutes} min — {leg.description}")
            if selected.rejected_for_parts:
                st.caption(
                    "Nearer hubs rejected for missing parts: "
                    + ", ".join(selected.rejected_for_parts)
                )

    with controls:
        path = route["path_record"] if route else None
        _render_map(renderer, path, None)
        _map_caption()


def _hub_table() -> None:
    st.subheader("Assumed dispatch hubs")
    st.dataframe(
        [
            {
                "hub": hub["short"],
                "name": hub["name"],
                "likelihood": hub["likelihood"].replace("_", " "),
                "crews": hub["crews"],
                "splice kit": hub["splice_kit"],
                "rationale": hub["rationale"],
            }
            for hub in hub_records()
        ],
        hide_index=True,
        use_container_width=True,
    )
    st.caption(
        f"{len(assumed_bases())} of {len(DISPATCH_BASES)} hub locations are "
        f"assumptions. Core sites: {', '.join(site.municipio for site in core_sites())}. "
        f"Ferry terminals: {', '.join(site.municipio for site in ferry_terminals())}. "
        "Puerto Rico HFC/PON is in scope; USVI fixed service is excluded."
    )


def render() -> None:
    from lpr_cpe_demo.ui import theme

    st.markdown(
        theme.header(
            "Footprint and dispatch",
            "Stage dispatch from the exact cases generated by the active demo run, "
            "or switch to manual planning inputs.",
        ),
        unsafe_allow_html=True,
    )
    available = _renderers()
    if not available:
        st.error(
            "No map renderer is available. Run scripts/generate_footprint_map.py "
            "for the offline schematic."
        )
        return

    source = st.radio(
        "Input source",
        ("Active demo run", "Manual planning inputs"),
        horizontal=True,
    )
    if source == "Active demo run":
        _render_active_dispatch(available)
    else:
        _render_manual_dispatch(available)
    _hub_table()
