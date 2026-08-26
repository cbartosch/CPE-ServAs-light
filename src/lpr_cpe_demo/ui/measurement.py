"""Streamlit helpers for the shared dashboard measurement contract."""

from __future__ import annotations

from typing import Any

import streamlit as st


def metric_record(projection: dict[str, Any], key: str) -> dict[str, Any]:
    return dict(projection.get("metrics", {}).get(key, {}))


def metric_value(
    projection: dict[str, Any],
    key: str,
    default: int | float | None = None,
) -> int | float | None:
    record = metric_record(projection, key)
    return record.get("value", default) if record.get("available", True) else default


def format_metric(value: int | float | None, *, percent: bool = False) -> str:
    if value is None:
        return "—"
    if percent:
        return f"{float(value):.1f}%"
    if isinstance(value, float) and not value.is_integer():
        return f"{value:,.1f}"
    return f"{int(value):,}"


def render_measurement_context(
    projection: dict[str, Any],
    *,
    title: str = "Measurement context",
) -> None:
    context = projection.get("measurement_context", {})
    coverage = context.get("scan_coverage_pct")
    run_id = context.get("run_id") or "Not linked"
    with st.container(border=True):
        st.markdown(f"**{title}**")
        cols = st.columns(6)
        cols[0].metric("Mode", str(context.get("mode", "unknown")).replace("_", " ").title())
        cols[1].metric("Run", str(run_id))
        cols[2].metric("As of", str(context.get("as_of") or "—"))
        cols[3].metric("Primary grain", str(context.get("primary_grain") or "—"))
        cols[4].metric("Scan coverage", format_metric(coverage, percent=True))
        cols[5].metric(
            "Complete",
            "Yes" if not projection.get("data_completeness", {}).get("truncated") else "No",
        )
        st.caption(
            f"Window: {context.get('window', '—')} · Source: "
            f"{context.get('source', '—')} · {context.get('completeness', '—')}"
        )


def render_status_partition(projection: dict[str, Any]) -> None:
    partition = projection.get("status_partition", {})
    cols = st.columns(5)
    for col, key in zip(
        cols,
        ("open", "waiting", "closed", "escalated", "quarantined"),
        strict=True,
    ):
        col.metric(key.title(), int(partition.get(key, 0) or 0))
    st.caption(
        "These five states are mutually exclusive and sum to root incidents. "
        "Pending approvals and other workload counters are shown separately."
    )


def render_common_kpis(projection: dict[str, Any]) -> None:
    cols = st.columns(6)
    cols[0].metric(
        "Root incidents",
        format_metric(metric_value(projection, "root_incidents")),
    )
    cols[1].metric(
        "At-risk services",
        format_metric(metric_value(projection, "at_risk_services")),
    )
    cols[2].metric(
        "Predictive match",
        format_metric(metric_value(projection, "predictive_match_rate_pct"), percent=True),
    )
    cols[3].metric(
        "Closed root incidents",
        format_metric(metric_value(projection, "closed_root_incidents")),
    )
    cols[4].metric(
        "Pending approvals",
        format_metric(metric_value(projection, "pending_approvals")),
    )
    cols[5].metric(
        "Scan coverage",
        format_metric(metric_value(projection, "scan_coverage_pct"), percent=True),
    )
