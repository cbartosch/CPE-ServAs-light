"""Footprint and dispatch page.

Shows the schematic map, the assumed dispatch bases, and what a location costs
in travel time for a dirty-boots visit.
"""

from __future__ import annotations

import pathlib

import streamlit as st

from lpr_cpe_demo.geography import (DISPATCH_BASES, SITE_BY_ID, assumed_bases,
                                    select_base, sites_in_cpe_footprint)

ASSETS = pathlib.Path(__file__).resolve().parents[1] / "assets"


def render() -> None:
    st.title("Footprint and dispatch")

    st.warning(
        "**Dispatch bases are assumed.** Liberty does not publish operations-centre "
        "locations. Every base below is placed at a plausible regional municipio and "
        "must be replaced with actual facility locations, crew rosters and van stock "
        "before this model is used operationally. The only externally supported "
        "anchor is a core platform site in San Juan.",
        icon="⚠️",
    )

    svg = ASSETS / "footprint_map.svg"
    if svg.exists():
        st.image(str(svg), use_container_width=True)
    else:
        st.error("Map not generated. Run scripts/generate_footprint_map.py.")

    st.caption(
        "Fixed HFC and PON footprint is Puerto Rico, 78 municipios including the "
        "island municipios of Vieques and Culebra. U.S. Virgin Islands sites are "
        "modelled but excluded: LPR serves USVI for mobile, while USVI fixed sits "
        "with a separate entity."
    )

    left, right = st.columns([1, 1])

    with left:
        st.subheader("Assumed dispatch bases")
        st.dataframe(
            [{"base": b.base_id.replace("BASE-", ""), "name": b.name,
              "crews": ", ".join(b.crew_types),
              "splice kit": "yes" if "splice_kit" in b.van_stock else "no"}
             for b in DISPATCH_BASES],
            hide_index=True, use_container_width=True)
        st.caption(f"{len(assumed_bases())} of {len(DISPATCH_BASES)} bases are assumptions.")

    with right:
        st.subheader("What does this location cost?")
        sites = sorted(sites_in_cpe_footprint(), key=lambda s: s.municipio)
        choice = st.selectbox("Site", sites,
                              format_func=lambda s: f"{s.municipio} — {s.archetype}")
        needs_splice = st.checkbox("Fault needs a fibre splice (requires a splice kit)")

        try:
            sel = select_base(
                choice, crew_type="dirty",
                required_skills=["fibre_splice"] if needs_splice else [],
                required_parts=["splice_kit"] if needs_splice else [])
        except LookupError as exc:
            st.error(str(exc))
        else:
            a, b, c = st.columns(3)
            a.metric("Staged from", sel.base.base_id.replace("BASE-", ""))
            b.metric("One-way travel", f"{sel.plan.total_minutes} min")
            c.metric("Same day", "yes" if sel.plan.same_day_feasible else "no")

            for leg in sel.plan.legs:
                st.write(f"- **{leg.kind}** {leg.minutes} min — {leg.description}")

            if sel.plan.requires_ferry:
                st.info("Island work is staged from Fajardo. The ferry leg includes a mean "
                        "wait for the next sailing, and cargo slots are limited, so parts "
                        "must travel with the crew.", icon="⛴")
            if not sel.plan.same_day_feasible:
                st.error("A round trip plus on-site work exceeds one shift. This dispatch "
                         "needs an overnight plan or a pre-positioned crew.", icon="⏱")
            if sel.rejected_for_parts:
                st.caption(f"{len(sel.rejected_for_parts)} nearer base(s) rejected for missing "
                           f"parts: {', '.join(sel.rejected_for_parts)}")
