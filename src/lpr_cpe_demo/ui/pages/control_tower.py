"""E2E Fixed Access Assurance Orchestration — control tower.

Single-page dark dashboard in the supplied format: hero with badges, control
strip, KPI row, charts, hotspot table, closed-loop confidence, playbook backlog.

Every panel shows its provenance as a coloured chip: green for computed from the
model, amber for a stated assumption, red for shape-only with no data source. The
supplied template mixed all three silently, which is how a synthetic figure ends
up quoted in a steering committee.
"""

from __future__ import annotations

import pathlib

import streamlit as st

from lpr_cpe_demo.benchmarks import citation
from lpr_cpe_demo.dashboard import build
from lpr_cpe_demo.ui import theme_dark as td
from lpr_cpe_demo.ui.client import APIError
from lpr_cpe_demo.ui.common import digital_twin_api
from lpr_cpe_demo.ui.measurement import (
    render_common_kpis,
    render_measurement_context,
    render_status_partition,
)


def _chart(block, plot) -> None:
    st.markdown(td.card_open(block.title, block.provenance, block.note),
                unsafe_allow_html=True)
    plot()


def _render_planning_model() -> None:
    with st.sidebar:
        st.caption("Control tower")
        count = st.slider("Incidents", 20, 300, 60, step=10)
        seed = st.number_input("Seed", min_value=0, max_value=2_147_483_647,
                              value=20_260_817, step=1)
        show_synthetic = st.checkbox("Show shape-only panels", value=False,
                                     help="Panels with no data source behind them.")

    dash = build(count=int(count), seed=int(seed))
    st.markdown(td.hero(dash.title, dash.subtitle, dash.badges),
                unsafe_allow_html=True)
    render_measurement_context(
        {
            "measurement_context": {
                "mode": "planning_model",
                "source": "seeded_fault_generator",
                "run_id": f"seed-{int(seed)}",
                "linked_to_active_run": False,
                "as_of": "Reproducible planning sample",
                "window": f"{int(count)} generated fault records",
                "primary_grain": "synthetic fault record",
                "completeness": "Complete generated sample; independent of active run",
                "planning_model": True,
                "scan_coverage_pct": None,
            },
            "data_completeness": {"truncated": False},
        },
        title="Planning-model measurement context",
    )
    st.warning(
        "Planning-model values are independent what-if outputs. They are not the "
        "active Digital Twin run and are never blended into active-run KPI totals."
    )
    st.markdown(td.executive_crosslink(), unsafe_allow_html=True)

    # State the agent layer's status before any number, because an inactive layer
    # changes what every number below means.
    status = dash.block("agent_status")
    banner = st.error if status.provenance != "computed" else st.success
    banner(f"**Agent status.** {status.note}", icon="🤖")

    counts = dash.provenance_counts()
    strip = st.columns([2, 1, 1, 1])
    strip[0].markdown(
        f'<div class="ct-card"><div class="ct-kpi-label">Assurance mode</div>'
        f'<div class="ct-kpi-desc" style="font-size:0.9rem;color:{td.INK}">'
        f'{dash.control_panel["assurance_mode"]}</div></div>',
        unsafe_allow_html=True)
    for col, (key, colour) in zip(strip[1:], (("computed", td.ACCENTS["green"]),
                                             ("assumed", td.ACCENTS["amber"]),
                                             ("synthetic", td.ACCENTS["red"])),
                                           strict=True):
        col.markdown(
            f'<div class="ct-card"><div class="ct-kpi-label">{key} panels</div>'
            f'<div class="ct-kpi-value" style="color:{colour}">'
            f'{counts.get(key, 0)}</div></div>', unsafe_allow_html=True)

    # ------------------------------------------------------------------ KPIs
    kpis = dash.block("kpis")
    st.markdown(td.card_open(kpis.title, kpis.provenance, kpis.note),
                unsafe_allow_html=True)
    cols = st.columns(len(kpis.data))
    for col, item in zip(cols, kpis.data, strict=True):
        col.markdown(td.kpi(item["label"], item["value"], item["description"]),
                     unsafe_allow_html=True)

    try:
        import plotly.graph_objects as go
    except Exception as exc:
        st.warning(f"plotly unavailable ({exc}); showing tables instead.")
        go = None

    left, right = st.columns(2)

    # -------------------------------------------------------- root cause mix
    mix = dash.block("incident_root_cause_mix")
    with left:
        if go:
            def plot_mix() -> None:
                fig = go.Figure(go.Pie(
                    labels=[d["name"] for d in mix.data],
                    values=[d["value"] for d in mix.data], hole=0.58,
                    marker={"colors": [d["color"] for d in mix.data],
                            "line": {"color": td.SLATE_900, "width": 2}},
                    textinfo="percent", insidetextfont={"color": td.SLATE_950}))
                fig.update_layout(**td.plotly_layout(280), showlegend=True)
                st.plotly_chart(fig, use_container_width=True)
            _chart(mix, plot_mix)
        else:
            _chart(mix, lambda: st.dataframe(mix.data, hide_index=True,
                                             use_container_width=True))

    # ---------------------------------------------------------- autonomy funnel
    funnel = dash.block("automation_funnel")
    with right:
        if go:
            def plot_funnel() -> None:
                stages = [d["stage"] for d in funnel.data]
                fig = go.Figure()
                fig.add_bar(y=stages, x=[d["autonomous_pct"] for d in funnel.data],
                            name="autonomous", orientation="h",
                            marker_color=td.ACCENTS["cyan"])
                fig.add_bar(y=stages, x=[d["human_pct"] for d in funnel.data],
                            name="human in the loop", orientation="h",
                            marker_color=td.ACCENTS["amber"])
                layout = td.plotly_layout(280)
                layout["barmode"] = "stack"
                layout["yaxis"]["autorange"] = "reversed"
                fig.update_layout(**layout)
                st.plotly_chart(fig, use_container_width=True)
            _chart(funnel, plot_funnel)
        else:
            _chart(funnel, lambda: st.dataframe(funnel.data, hide_index=True,
                                                use_container_width=True))

    # -------------------------------------------------------- cost by archetype
    cost = dash.block("cost_by_archetype")
    if go:
        def plot_cost() -> None:
            arche = [d["archetype"] for d in cost.data]
            fig = go.Figure()
            fig.add_bar(x=arche, y=[d["mean_cost"] for d in cost.data],
                        name="mean cost to resolve",
                        marker_color=td.ACCENTS["blue"])
            fig.add_bar(x=arche, y=[d["mean_wasted_visit"] for d in cost.data],
                        name="benchmark cost of a wasted visit",
                        marker_color=td.ACCENTS["red"])
            layout = td.plotly_layout(300)
            layout["barmode"] = "group"
            layout["yaxis"]["title"] = "USD"
            fig.update_layout(**layout)
            st.plotly_chart(fig, use_container_width=True)
        _chart(cost, plot_cost)
        st.caption(citation())
    else:
        _chart(cost, lambda: st.dataframe(cost.data, hide_index=True,
                                          use_container_width=True))

    # ---------------------------------------------------------------- hotspots
    hot = dash.block("hotspots")
    _chart(hot, lambda: st.dataframe(hot.data, hide_index=True,
                                     use_container_width=True))

    # ------------------------------------------------- closed-loop confidence
    loop = dash.block("closed_loop_confidence")
    lcol, rcol = st.columns([1, 1])
    with lcol:
        st.markdown(td.card_open(loop.title, loop.provenance, loop.note),
                    unsafe_allow_html=True)
        overall = loop.data["overall_confidence_pct"]
        st.markdown(td.kpi("Overall", f"{overall}%",
                           "Mean of the guardrail scores below"),
                    unsafe_allow_html=True)
        for guard in loop.data["guardrails"]:
            score = guard["score_pct"]
            tone = (td.ACCENTS["green"] if score >= 85
                    else td.ACCENTS["amber"] if score >= 60
                    else td.ACCENTS["red"])
            st.markdown(
                f'<div class="ct-card" style="padding:0.55rem 0.85rem">'
                f'<span style="color:{tone};font-weight:600">{score}%</span> '
                f'<span>{guard["name"]}</span>'
                f'<div class="ct-note">{guard["basis"]}</div></div>',
                unsafe_allow_html=True)

    with rcol:
        play = dash.block("playbook_backlog")
        _chart(play, lambda: st.dataframe(play.data, hide_index=True,
                                         use_container_width=True))

    # -------------------------------------------------------- synthetic panels
    if show_synthetic:
        health = dash.block("service_health_by_layer")
        if go:
            def plot_health() -> None:
                fig = go.Figure()
                for name, colour in (("HFC", "cyan"), ("PON", "blue"),
                                     ("Core", "green"), ("WiFi", "amber")):
                    fig.add_scatter(x=[d["time"] for d in health.data],
                                    y=[d[name] for d in health.data],
                                    name=name, mode="lines",
                                    line={"color": td.ACCENTS[colour], "width": 2})
                layout = td.plotly_layout(280)
                layout["yaxis"]["range"] = [85, 100]
                layout["yaxis"]["title"] = "% healthy"
                fig.update_layout(**layout)
                st.plotly_chart(fig, use_container_width=True)
            _chart(health, plot_health)
        else:
            _chart(health, lambda: st.dataframe(health.data, hide_index=True,
                                                use_container_width=True))

    caddi = dash.block("cadi_call_center_layer")
    st.markdown(td.card_open(caddi.title, caddi.provenance, caddi.note),
                unsafe_allow_html=True)
    caddi_summary = caddi.data["summary"]
    caddi_cols = st.columns(4)
    caddi_cols[0].metric("Mapped domains", caddi_summary["capability_domains"])
    caddi_cols[1].metric("Declared in DvSum CADDI", caddi_summary["declared_existing"])
    caddi_cols[2].metric("Known gaps", caddi_summary["known_gaps"])
    caddi_cols[3].metric("Live adapter", "No — contract only")
    st.info(
        caddi.data["source_of_truth_policy"] + " " + caddi.data["operations_boundary"]
    )
    st.dataframe(caddi.data["capabilities"], hide_index=True,
                 use_container_width=True)
    st.caption(
        "DvSum CADDI capability mapping is based on LPR stakeholder input. APIs, field "
        "definitions, latency, source precedence and contractor roadmap require "
        "joint discovery before a live integration is claimed."
    )

    contract = dash.block("data_contract")
    st.markdown(td.card_open(contract.title, contract.provenance, contract.note),
                unsafe_allow_html=True)
    st.dataframe(contract.data, hide_index=True, use_container_width=True)
    st.caption("A panel marked blocked is not a caveat: the named source system "
               "is the work item that closes it.")

    html_path = pathlib.Path(__file__).resolve().parents[3].parent / "docs" / "control_tower.html"
    if html_path.exists():
        st.download_button(
            "Download the standalone drill-down HTML",
            data=html_path.read_bytes(), file_name="control_tower.html",
            mime="text/html",
            help="One file, no server, no network. Opens from a USB stick and "
                 "drills from a panel to an incident to its effort ledger.")

    with st.expander("Provenance, and what would make each panel real"):
        for block in dash.blocks:
            st.markdown(f"**{block.title}** — `{block.provenance}`  \n{block.note}")


def _render_active_run() -> None:
    try:
        projection = digital_twin_api().active_projection()
    except APIError as exc:
        st.error(f"Active Digital Twin run unavailable: {exc}")
        st.info("Create a Digital Twin run or choose Planning model in the sidebar.")
        return

    context = projection.get("measurement_context", {})
    run_id = str(projection.get("run_id") or context.get("run_id") or "unknown")
    badges = [
        {"label": "active-run evidence", "type": "observability"},
        {"label": f"run {run_id}", "type": "scope"},
        {"label": "root-incident grain", "type": "scope"},
        {"label": "complete canonical datasets", "type": "observability"},
    ]
    st.markdown(
        td.hero(
            "Executive Control Tower — active-run evidence",
            (
                "The same canonical measurement projection used by Predictive Health "
                "and Customer Experience. Planning assumptions are kept in a separate mode."
            ),
            badges,
        ),
        unsafe_allow_html=True,
    )
    st.markdown(td.executive_crosslink(), unsafe_allow_html=True)
    render_measurement_context(projection, title="Active-run measurement context")
    render_common_kpis(projection)

    st.subheader("Root-incident status")
    render_status_partition(projection)

    predictive = projection.get("predictive_funnel", {})
    care = projection.get("care_funnel", {})
    operational = projection.get("operational_funnel", {})
    left, middle, right = st.columns(3)
    with left:
        st.markdown(td.card_open(
            "Predictive funnel",
            "computed",
            "Unique service/device grain from the complete canonical run.",
        ), unsafe_allow_html=True)
        st.dataframe(
            [
                {"Stage": "Services in footprint", "Count": predictive.get("eligible_services", 0)},
                {"Stage": "Devices scanned", "Count": predictive.get("scanned_devices", 0)},
                {
                    "Stage": "Healthy scanned services",
                    "Count": predictive.get("healthy_scanned_services", 0),
                },
                {
                    "Stage": "Forecast-risk services",
                    "Count": predictive.get("forecast_risk_services", 0),
                },
                {
                    "Stage": "Currently degraded services",
                    "Count": predictive.get("degraded_services", 0),
                },
            ],
            hide_index=True,
            use_container_width=True,
        )
    with middle:
        st.markdown(td.card_open(
            "Care correlation",
            "computed",
            "Contact grain. It is intentionally separate from root incidents.",
        ), unsafe_allow_html=True)
        st.dataframe(
            [
                {"Stage": "Care contacts", "Count": care.get("contacts", 0)},
                {"Stage": "Predictively matched", "Count": care.get("predictively_matched", 0)},
                {"Stage": "Reactive only", "Count": care.get("reactive_only", 0)},
                {
                    "Stage": "Attached to canonical root",
                    "Count": care.get("canonical_root_attachments", 0),
                },
            ],
            hide_index=True,
            use_container_width=True,
        )
    with right:
        st.markdown(td.card_open(
            "Operational funnel",
            "computed",
            "Case attempts are distinguished from durable root incidents.",
        ), unsafe_allow_html=True)
        st.dataframe(
            [
                {"Stage": "Case attempts", "Count": operational.get("case_attempts", 0)},
                {"Stage": "Root incidents", "Count": operational.get("root_incidents", 0)},
                {
                    "Stage": "Field-dispatched roots",
                    "Count": operational.get("field_dispatched_root_incidents", 0),
                },
                {"Stage": "Validated events", "Count": operational.get("validated_events", 0)},
                {
                    "Stage": "Closed root incidents",
                    "Count": operational.get("closed_root_incidents", 0),
                },
            ],
            hide_index=True,
            use_container_width=True,
        )

    reconciliation = projection.get("reconciliation", {})
    if reconciliation.get("passed"):
        st.success("Shared measurement invariants reconcile for the active run.")
    else:
        st.error("One or more shared measurement invariants failed for the active run.")
    with st.expander("Reconciliation checks", expanded=False):
        st.json(reconciliation)

    stories = projection.get("stories", [])
    if stories:
        st.subheader("Canonical customer-to-incident links")
        rows = [
            {
                "Care contact": item.get("contact_id"),
                "Service": item.get("service_id"),
                "Predictive match": bool(item.get("predictive_match")),
                "Root incident": item.get("incident_id"),
                "Case attempt": item.get("case_id"),
                "Incident status": (item.get("root_incident") or {}).get("status"),
            }
            for item in stories[:20]
        ]
        st.dataframe(rows, hide_index=True, use_container_width=True)

    st.caption(
        "This mode contains no seeded planning-model KPIs. Choose Planning model in "
        "the sidebar for cost, benchmark and what-if panels."
    )


def render() -> None:
    st.markdown(td.css(), unsafe_allow_html=True)
    with st.sidebar:
        st.caption("Control Tower evidence mode")
        mode = st.radio(
            "Measurement source",
            ("Active run evidence", "Planning model"),
            index=0,
            help=(
                "Active run uses the shared Digital Twin projection. Planning model "
                "uses an independent seeded fault sample and is never blended into run KPIs."
            ),
        )
    if mode == "Active run evidence":
        _render_active_run()
    else:
        _render_planning_model()
