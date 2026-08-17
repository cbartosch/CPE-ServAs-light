"""Fault simulator: cost and location of intervention.

Generates synthetic faults across the footprint, plots each at the place the work
actually happens, and shows what it costs. The intervention point is not the
customer address: a tap or ODP fault is worked at the tap or ODP, by a different
crew, serving several households.

Every rate, duration and plant ratio is assumed. See effort.assumptions() and
plant.PLANT_ASSUMPTIONS.
"""

from __future__ import annotations

import pathlib

import streamlit as st

from lpr_cpe_demo.benchmarks import BANDS, citation
from lpr_cpe_demo.effort import assumptions, false_positive_cost
from lpr_cpe_demo.fault_generator import generate_faults, summarise
from lpr_cpe_demo.geo_layers import (COST_BANDS, FAULT_TOOLTIP, INITIAL_VIEW,
                                     OSM_ATTRIBUTION, fault_layer_specs,
                                     fault_records)

ASSETS = pathlib.Path(__file__).resolve().parents[1] / "assets"


def _render_map(faults, show_routes: bool) -> bool:
    try:
        import json

        import pydeck as pdk
    except Exception:
        return False
    spec = {
        "initialViewState": INITIAL_VIEW,
        "layers": fault_layer_specs(faults, show_routes=show_routes),
        "mapProvider": None,
        "mapStyle": None,
        "views": [{"@@type": "MapView", "controller": True}],
    }
    try:
        st.pydeck_chart(pdk.Deck.from_json(json.dumps(spec)),
                        use_container_width=True)
        return True
    except Exception as exc:
        st.warning(f"pydeck could not render ({exc}).")
        return False


def render() -> None:
    st.title("Fault simulator: cost and location of intervention")

    st.warning(
        "**Every figure here is assumed.** Rates, durations, plant ratios and "
        "hub locations are placeholders of plausible magnitude, not LPR data. "
        "Faults are synthetic, generated from a seed. Replace `RATES`, "
        "`DURATIONS` and `PLANT_ASSUMPTIONS` before any number leaves a "
        "demonstration.",
        icon="⚠️",
    )

    controls = st.columns([1, 1, 1, 1])
    count = controls[0].slider("Faults", 5, 200, 40, step=5)
    seed = controls[1].number_input("Seed", min_value=0, max_value=10_000_000,
                                    value=20260817, step=1,
                                    help="Same seed gives the same faults, "
                                         "coordinates and costs on any machine.")
    show_routes = controls[2].checkbox("Show dispatch routes", value=True)
    plant_only = controls[3].checkbox("Plant interventions only",
                                      help="Faults worked away from the customer "
                                           "address: taps, ODPs, nodes, PON ports.")

    faults = generate_faults(count, seed=int(seed))
    shown = [f for f in faults if not f.intervention_is_at_premise] if plant_only \
        else faults
    if not shown:
        st.info("No plant interventions in this sample. Increase the count or "
                "change the seed.")
        return

    stats = summarise(shown)

    a, b, c, d, e = st.columns(5)
    a.metric("Faults", stats["faults"])
    b.metric("Total cost", f"${stats['total_cost_usd']:,.0f}")
    c.metric("Mean per fault", f"${stats['mean_cost_usd']:,.0f}")
    d.metric("Truck rolls", stats["truck_rolls"])
    e.metric("Households affected", f"{stats['households_affected']:,}")

    f, g, h, i = st.columns(4)
    f.metric("Worked away from premise", stats["off_premise_interventions"],
             help="Tap, ODP, node or PON port faults. The reporting address is "
                  "not where the crew goes.")
    g.metric("Dirty boots share", f"{stats['dirty_boots_share']:.0%}")
    h.metric("Ferry jobs", stats["ferry_jobs"])
    i.metric("Overnight jobs", stats["overnight_jobs"],
             help="Round trip plus on-site work exceeds one shift.")

    st.info(
        f"**Benchmark cross-check.** Summing the third-party per-dispatch cost over "
        f"the {stats['truck_rolls']} truck rolls above gives "
        f"${stats['benchmark_wasted_exposure_usd']:,.0f} if every one were wasted. "
        f"{stats['outside_benchmark_scope']} fault(s) fall outside the published "
        f"range because island work involves a ferry crossing and an overnight, "
        f"which the source does not contemplate.\n\n{citation()}",
        icon="📊",
    )

    st.error(
        f"**Misdispatch exposure: ${stats['misdispatch_exposure_usd']:,.0f}.** "
        f"That is the additional cost if every one of these faults were sent to "
        f"the wrong crew first: a wasted visit plus a handover, before the correct "
        f"visit still has to happen. A false alarm on the RCA gate costs "
        f"${false_positive_cost().cost_usd:,.2f} by comparison.",
        icon="💸",
    )

    if not _render_map(shown, show_routes):
        svg = ASSETS / "footprint_map.svg"
        if svg.exists():
            st.image(str(svg), use_container_width=True)
            st.caption("pydeck unavailable; showing the offline schematic without "
                       "fault pins.")

    legend = " · ".join(f"{label}" for _, _, label in COST_BANDS)
    st.caption(
        f"Pin position is the **intervention point**, not the reporting address. "
        f"Grey lines join a household to its tap or ODP when the work happens "
        f"away from the premise. Pin size and colour carry cost: {legend} USD. "
        f"Teal squares are assumed dispatch hubs. Basemap {OSM_ATTRIBUTION}."
    )

    st.subheader("Cost by fault")
    rows = sorted(fault_records(shown), key=lambda r: -float(r["cost"]))
    st.dataframe(
        [{"fault": r["fault_id"], "priority": r["priority"],
          "municipio": r["municipio"], "tech": r["technology"],
          "domain": r["domain"], "intervention": r["intervention_id"],
          "at": r["at"], "hh": r["households"], "crew": r["crew"],
          "base": r["base"], "minutes": r["minutes"],
          "cost USD": r["cost"], "if misdispatched USD": r["if_missed"]}
         for r in rows],
        hide_index=True, use_container_width=True)

    st.subheader("Effort ledger")
    chosen = st.selectbox("Fault", [f.fault_id for f in shown],
                          format_func=lambda fid: next(
                              f"{f.fault_id} — {f.municipio} — {f.true_domain} "
                              f"— ${f.total_cost_usd:,.0f}"
                              for f in shown if f.fault_id == fid))
    fault = next(f for f in shown if f.fault_id == chosen)

    left, right = st.columns([2, 1])
    with left:
        st.dataframe(list(fault.ledger_rows), hide_index=True,
                     use_container_width=True)
    with right:
        st.write(f"**Reported by** {fault.household_id}")
        st.write(f"**Worked at** {fault.intervention_id} "
                 f"({fault.intervention_kind})")
        st.write(f"**Serving** {fault.households_affected} household(s)")
        st.write(f"**Crew** {fault.crew_type} boots from {fault.base_name}")
        st.write(f"**Travel** {fault.travel_minutes} min each way")
        if fault.requires_ferry:
            st.info("Ferry leg required.", icon="⛴")
        if not fault.same_day_feasible:
            st.error("Exceeds one shift.", icon="⏱")
        st.metric("Cost", f"${fault.total_cost_usd:,.2f}")
        st.metric("If misdispatched", f"${fault.misdispatch_cost_usd:,.2f}",
                  delta=f"+${fault.misdispatch_premium_usd:,.2f}",
                  delta_color="inverse")

    with st.expander("Assumptions and benchmark source"):
        st.write("**Bottom-up model** — assumed labour rates and durations:")
        st.json(assumptions())
        st.write("**Third-party benchmark** — published bands per dispatched visit:")
        st.json({band: BANDS[band] for band in BANDS})
        st.caption(citation())
        st.caption(
            "Reconciliation: the bottom-up model runs 1.3 to 1.7 times the "
            "benchmark on coastal, mountain and island work, and about 0.6 times "
            "it in metro where a hub is co-located and travel is near zero. The "
            "household-weighted blend lands at roughly $219 per wasted dispatch, "
            "inside the published $150 to $300 range.")
