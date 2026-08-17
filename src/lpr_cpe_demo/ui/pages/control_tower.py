"""E2E Fixed Access Assurance Orchestration — control tower.

Single-page dark dashboard in the supplied format: hero with badges, control
strip, KPI row, charts, hotspot table, closed-loop confidence, playbook backlog.

Every panel shows its provenance as a coloured chip: green for computed from the
model, amber for a stated assumption, red for shape-only with no data source. The
supplied template mixed all three silently, which is how a synthetic figure ends
up quoted in a steering committee.
"""

from __future__ import annotations

import streamlit as st

from lpr_cpe_demo.benchmarks import citation
from lpr_cpe_demo.dashboard import build
from lpr_cpe_demo.ui import theme_dark as td


def _chart(block, plot) -> None:
    st.markdown(td.card_open(block.title, block.provenance, block.note),
                unsafe_allow_html=True)
    plot()


def render() -> None:
    st.markdown(td.css(), unsafe_allow_html=True)

    with st.sidebar:
        st.caption("Control tower")
        count = st.slider("Incidents", 20, 300, 60, step=10)
        seed = st.number_input("Seed", min_value=0, max_value=2_147_483_647,
                              value=20_260_817, step=1)
        show_synthetic = st.checkbox("Show shape-only panels", value=True,
                                     help="Panels with no data source behind them.")

    dash = build(count=int(count), seed=int(seed))
    st.markdown(td.hero(dash.title, dash.subtitle, dash.badges),
                unsafe_allow_html=True)

    counts = dash.provenance_counts()
    strip = st.columns([2, 1, 1, 1])
    strip[0].markdown(
        f'<div class="ct-card"><div class="ct-kpi-label">Assurance mode</div>'
        f'<div class="ct-kpi-desc" style="font-size:0.9rem;color:{td.INK}">'
        f'{dash.control_panel["assurance_mode"]}</div></div>',
        unsafe_allow_html=True)
    for col, (key, colour) in zip(strip[1:], (("computed", td.ACCENTS["green"]),
                                             ("assumed", td.ACCENTS["amber"]),
                                             ("synthetic", td.ACCENTS["red"]))):
        col.markdown(
            f'<div class="ct-card"><div class="ct-kpi-label">{key} panels</div>'
            f'<div class="ct-kpi-value" style="color:{colour}">'
            f'{counts.get(key, 0)}</div></div>', unsafe_allow_html=True)

    # ------------------------------------------------------------------ KPIs
    kpis = dash.block("kpis")
    st.markdown(td.card_open(kpis.title, kpis.provenance, kpis.note),
                unsafe_allow_html=True)
    cols = st.columns(len(kpis.data))
    for col, item in zip(cols, kpis.data):
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

    contract = dash.block("data_contract")
    st.markdown(td.card_open(contract.title, contract.provenance, contract.note),
                unsafe_allow_html=True)
    st.dataframe(contract.data, hide_index=True, use_container_width=True)
    st.caption("A panel marked blocked is not a caveat: the named source system "
               "is the work item that closes it.")

    with st.expander("Provenance, and what would make each panel real"):
        for block in dash.blocks:
            st.markdown(f"**{block.title}** — `{block.provenance}`  \n{block.note}")
