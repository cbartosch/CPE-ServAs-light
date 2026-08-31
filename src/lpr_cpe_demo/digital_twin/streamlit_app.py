# ruff: noqa: E501
from __future__ import annotations

import base64
import html
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

import streamlit as st

from ..caddi import caddi_contract, caddi_contract_rows
from ..ui.measurement import (
    format_metric,
    metric_value,
    render_measurement_context,
    render_status_partition,
)
from . import executive_style

API = os.getenv("DT_API_URL", "http://api:8001")
USER = os.getenv("DT_USER", "demo")
PASSWORD = os.getenv("DT_PASSWORD", "CHANGE_ME")
DATASETS = [
    "subscriber_master",
    "scenario_manifests",
    "telemetry_tr181",
    "nxt_alarms",
    "contacts",
    "incidents",
    "work_orders",
    "field_evidence",
    "mrs",
    "validation_events",
    "resolution_events",
    "deterministic_decisions",
    "agent_decisions",
    "reconciliation_records",
    "human_decisions",
    "action_events",
    "predictive_modem_pulls",
    "predictive_tickets",
    "care_tickets",
    "care_ticket_reviews",
]

DATASET_LABELS = {
    "subscriber_master": "Subscribers",
    "scenario_manifests": "Scenario timeline",
    "telemetry_tr181": "Modem telemetry (TR-181)",
    "nxt_alarms": "Network alarms",
    "contacts": "Customer contacts",
    "incidents": "Incidents",
    "work_orders": "Field work orders",
    "field_evidence": "Field evidence",
    "mrs": "Maintenance requests",
    "validation_events": "Service validation",
    "resolution_events": "Resolution evidence",
    "deterministic_decisions": "Deterministic decisions",
    "agent_decisions": "AI decisions",
    "reconciliation_records": "Decision reconciliation",
    "human_decisions": "Human approvals",
    "action_events": "Actions",
    "predictive_modem_pulls": "Predictive modem evidence",
    "predictive_tickets": "Predicted service risks",
    "care_tickets": "Customer Care tickets",
    "care_ticket_reviews": "Customer Care reviews",
}

SCENARIO_LABELS = {
    "slow_wifi": "Slow in-home Wi-Fi",
    "no_service": "No broadband service",
    "intermittent_service": "Intermittent service",
    "iptv_degradation": "TV quality degradation",
    "fiber_cut": "Fiber access cut",
    "hfc_ingress": "HFC ingress / RF impairment",
    "congestion": "Peak-time congestion",
    "power_outage": "Power outage",
    "storm": "Storm impact",
    "flooding": "Flooding",
    "hurricane": "Hurricane",
    "provisioning_error": "Provisioning error",
    "cpe_failure": "Gateway / modem failure",
}

RUN_STATE_KEYS = (
    "install_run",
    "predictive_run",
    "care_run",
    "data_run",
    "sub_run",
    "decision_run",
)

VIEW_ALIASES = {
    "external": "external",
    "external-evidence": "external",
    "csv-evidence": "external",
    "install": "install",
    "install-assurance": "install",
    "24-hour-install-watch": "install",
    "caddi": "caddi",
    "dvsum-caddi": "caddi",
    "genesys": "caddi",
    "caddi-genesys": "caddi",
    "cadi": "caddi",
    "cadi-genesys": "caddi",
    "executive": "executive",
    "executive-view": "executive",
    "create": "create",
    "create-demo": "create",
    "predictive": "predictive",
    "predictive-health": "predictive",
    "care": "care",
    "customer-care": "care",
    "customer-experience": "care",
    "subscriber": "subscriber",
    "subscriber-story": "subscriber",
    "decisions": "decisions",
    "controls": "decisions",
    "evidence": "evidence",
    "audit": "evidence",
}


def _request(path: str, method: str = "GET", body: dict | None = None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    token = base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
    req.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API {exc.code}: {detail}") from exc


def _remember_run(run_id: str) -> None:
    st.session_state["run_id"] = run_id
    for key in RUN_STATE_KEYS:
        st.session_state[key] = run_id


def _runs() -> list[dict]:
    try:
        result = _request("/api/runs")
    except Exception:
        return []
    return result if isinstance(result, list) else []


def _latest_run_id() -> str:
    for run in _runs():
        run_id = str(run.get("run_id", "")).strip()
        if run_id:
            return run_id
    return ""


def _active_run_id() -> str:
    try:
        active = _request("/api/active-run")
    except Exception:
        active = {}
    run_id = str(active.get("run_id", "")).strip() if isinstance(active, dict) else ""
    if not run_id:
        run_id = _latest_run_id()
        if run_id:
            try:
                _request("/api/active-run", "PUT", {"run_id": run_id})
            except Exception:
                pass
    if run_id:
        _remember_run(run_id)
    return run_id


def _activate_run(run_id: str) -> None:
    _request("/api/active-run", "PUT", {"run_id": run_id})
    _remember_run(run_id)


def _run_id(key: str) -> str:
    active = _active_run_id()
    runs = [str(item.get("run_id", "")) for item in _runs() if item.get("run_id")]
    if active and active not in runs:
        runs.insert(0, active)
    if not runs:
        return ""
    with st.expander("Canonical run selection", expanded=False):
        st.caption(
            "One persisted active run is shared across Executive, Predictive, Care and "
            "the active-run Control Tower. Selecting another run updates the API pointer."
        )
        selected = st.selectbox(
            "Active run",
            runs,
            index=runs.index(active) if active in runs else 0,
            key=f"{key}_selector",
        )
        if selected != active:
            try:
                _activate_run(selected)
                st.success(f"Active run changed to {_short_run(selected)}")
            except Exception as exc:
                st.error(f"Could not activate run: {exc}")
                return active
        st.session_state[key] = selected
        return selected


def _load_dataset_page(run_id: str, dataset: str, *, limit: int = 5000) -> dict:
    result = _request(
        f"/api/runs/{urllib.parse.quote(run_id)}/datasets/{dataset}?limit={limit}"
    )
    return dict(result)


def _load_dataset(run_id: str, dataset: str, *, limit: int = 5000) -> list[dict]:
    return list(_load_dataset_page(run_id, dataset, limit=limit).get("rows", []))


def _catalog(run_id: str) -> dict:
    return _request(f"/api/runs/{urllib.parse.quote(run_id)}")


def _projection(run_id: str) -> dict:
    return _request(f"/api/runs/{urllib.parse.quote(run_id)}/executive-projection")


def _friendly(value: object) -> str:
    return str(value or "").replace("_", " ").strip().title()


def _short_run(run_id: str) -> str:
    return run_id if len(run_id) <= 28 else f"{run_id[:18]}…{run_id[-7:]}"


def _timestamp(value: object) -> str:
    text = str(value or "")
    if not text:
        return "—"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    return parsed.strftime("%d %b · %H:%M")


def _run_chip(run_id: str) -> None:
    if not run_id:
        return
    st.markdown(
        f'<div class="lpr-run-chip">● Active demo run&nbsp; <strong>{html.escape(_short_run(run_id))}</strong></div>',
        unsafe_allow_html=True,
    )


def _hero() -> None:
    st.markdown(
        """
        <div class="lpr-exec-hero">
          <div class="lpr-exec-kicker">Predictive Service Assurance</div>
          <h1>Predict before the call. Resolve once.</h1>
          <p>One executive view connects modem health, Customer Care, root-cause decisions and governed resolution — so the demo tells a business story instead of exposing a data pipeline.</p>
          <div class="lpr-pill-row">
            <span class="lpr-pill"><span class="lpr-dot"></span> Predictive HFC + PON</span>
            <span class="lpr-pill"><span class="lpr-dot"></span> Care correlation</span>
            <span class="lpr-pill"><span class="lpr-dot"></span> DvSum CADDI / Genesys contract mapped</span>
            <span class="lpr-pill"><span class="lpr-dot"></span> AI reconciled to controls</span>
            <span class="lpr-pill"><span class="lpr-dot"></span> Production writes off</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _query_value(name: str) -> str:
    """Read one query parameter without depending on browser URL construction."""
    try:
        value = st.query_params.get(name, "")
    except Exception:
        return ""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    return str(value).strip().lower()


def _requested_view() -> str:
    return VIEW_ALIASES.get(_query_value("view"), "")


def _executive_crosslink(requested_view: str) -> None:
    linked = {
        "predictive": "Predictive Health",
        "care": "Customer Experience",
    }.get(requested_view)
    context = (
        f"Linked from the legacy Control Tower into {linked}."
        if linked
        else "Move between the legacy modeled scorecard and active-run operational evidence."
    )
    st.markdown(
        f'''<div class="lpr-crosslink">
          <div class="lpr-crosslink-summary">
            <div class="lpr-crosslink-title">One executive story, connected operational views</div>
            <div class="lpr-crosslink-copy">{html.escape(context)} The active run remains unchanged while you move between views.</div>
          </div>
          <div class="lpr-crosslink-actions">
            <a class="lpr-crosslink-link legacy" target="_self" href="control-tower">← Legacy Control Tower</a>
            <a class="lpr-crosslink-link" target="_self" href="digital-twin?view=predictive">Predictive Health</a>
            <a class="lpr-crosslink-link" target="_self" href="digital-twin?view=install-assurance">Install Assurance</a>
            <a class="lpr-crosslink-link" target="_self" href="digital-twin?view=customer-care">Customer Care</a>
            <a class="lpr-crosslink-link" target="_self" href="digital-twin?view=external-evidence">External Evidence</a>
            <a class="lpr-crosslink-link" target="_self" href="footprint">Footprint & Dispatch</a>
            <a class="lpr-crosslink-link" target="_self" href="simulator">Cost Simulator</a>
          </div>
        </div>''',
        unsafe_allow_html=True,
    )


def _section(kicker: str, title: str, copy: str = "") -> None:
    copy_html = f'<p class="lpr-section-copy">{html.escape(copy)}</p>' if copy else ""
    st.markdown(
        f'<div class="lpr-section-label">{html.escape(kicker)}</div>'
        f'<div class="lpr-section-title">{html.escape(title)}</div>{copy_html}',
        unsafe_allow_html=True,
    )


def _empty(title: str, copy: str) -> None:
    st.markdown(
        f'<div class="lpr-empty"><strong>{html.escape(title)}</strong>{html.escape(copy)}</div>',
        unsafe_allow_html=True,
    )


def _predictive_headline(ticket: dict) -> tuple[str, str]:
    findings = ticket.get("findings") or []
    if not findings:
        return "—", "—"
    breached = [finding for finding in findings if finding.get("breached_now")]
    if breached:
        finding = breached[0]
    else:
        candidates = [finding for finding in findings if finding.get("days_to_breach") is not None]
        finding = min(candidates, key=lambda item: float(item["days_to_breach"])) if candidates else findings[0]
    eta = finding.get("days_to_breach")
    return _friendly(finding.get("kpi")), "Now" if finding.get("breached_now") else (f"{float(eta):.1f} days" if eta is not None else "—")


def _predictive_table(rows: list[dict]) -> list[dict]:
    table = []
    for row in rows:
        signal, eta = _predictive_headline(row)
        table.append(
            {
                "Service": row.get("service_id"),
                "Access": row.get("technology"),
                "Risk": _friendly(row.get("ticket_class")),
                "Severity": _friendly(row.get("severity")),
                "Leading signal": signal,
                "Time to threshold": eta,
                "Likely cause": _friendly(row.get("suspected_cause")),
            }
        )
    return table


def _care_table(rows: list[dict]) -> list[dict]:
    return [
        {
            "Priority": row.get("priority"),
            "Customer issue": _friendly(row.get("category")),
            "Status": _friendly(row.get("status")),
            "Predictive match": "Yes — seen before call" if row.get("predictive_match") else "No",
            "Repeat": "Yes" if row.get("repeat_contact") else "No",
            "Opened": _timestamp(row.get("opened_at")),
            "Service": row.get("service_id"),
        }
        for row in rows
    ]


def _show_predictive_summary(summary: dict) -> None:
    cols = st.columns(5)
    cols[0].metric("Modems scanned", f"{summary.get('scanned', 0):,}")
    cols[1].metric("Healthy", f"{summary.get('healthy', 0):,}")
    cols[2].metric("Risk ticket rows", f"{summary.get('tickets', 0):,}")
    cols[3].metric("Risk rate", f"{100 * float(summary.get('flag_rate', 0)):.2f}%")
    cols[4].metric("Canonical Care links", f"{summary.get('care_tickets_correlated', 0):,}")


def _executive_view(run_id: str) -> None:
    if not run_id:
        _empty(
            "Your executive story starts with one demo run",
            "Open Create Demo, choose the scale and scenarios, and generate. The "
            "persisted active run will then follow you across every active-run view.",
        )
        return

    try:
        projection = _projection(run_id)
        predictive_page = _load_dataset_page(run_id, "predictive_tickets", limit=100)
    except Exception as exc:
        st.error(f"Could not load executive view: {exc}")
        return

    render_measurement_context(projection, title="Canonical active-run context")
    _section("Executive scorecard", "One metric contract across every active-run view")
    metrics = st.columns(6)
    metrics[0].metric(
        "Services in footprint",
        format_metric(metric_value(projection, "footprint_services")),
    )
    metrics[1].metric(
        "Devices scanned",
        format_metric(metric_value(projection, "scanned_devices")),
    )
    metrics[2].metric(
        "At-risk services",
        format_metric(metric_value(projection, "at_risk_services")),
    )
    metrics[3].metric(
        "Predictive match rate",
        format_metric(
            metric_value(projection, "predictive_match_rate_pct"),
            percent=True,
        ),
    )
    metrics[4].metric(
        "Canonical root attachments",
        format_metric(metric_value(projection, "canonical_root_attachments")),
    )
    closed = metric_value(projection, "closed_root_incidents", 0) or 0
    roots = metric_value(projection, "root_incidents", 0) or 0
    metrics[5].metric("Closed root incidents", f"{int(closed):,} / {int(roots):,}")

    st.subheader("Root-incident status")
    render_status_partition(projection)

    care = projection.get("care_funnel", {})
    predictive = projection.get("predictive_funnel", {})
    workload = projection.get("workload", {})
    contacts = int(care.get("contacts", 0) or 0)
    matched = int(care.get("predictively_matched", 0) or 0)
    share = 100 * matched / contacts if contacts else 0.0
    st.markdown(
        f'<div class="lpr-insight"><strong>Executive takeaway.</strong> '
        f'<strong>{matched:,} of {contacts:,} Care contacts ({share:.1f}%)</strong> '
        f'arrived with canonical predictive evidence. All {care.get("canonical_root_attachments", 0):,} '
        f'contacts are linked to a durable root incident. This is a measured attachment '
        f'count, not an unsupported claim that the same number of duplicate incidents '
        f'was attempted or avoided.</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <div class="lpr-story-grid">
          <div class="lpr-story-card"><div class="lpr-story-no">01</div><strong>Prevent</strong><span>{predictive.get('forecast_risk_services', 0):,} services are forecast-risk and {predictive.get('degraded_services', 0):,} are currently degraded. Together they reconcile to {predictive.get('at_risk_services', 0):,} unique at-risk services.</span></div>
          <div class="lpr-story-card"><div class="lpr-story-no">02</div><strong>Connect</strong><span>{matched:,} contacts have predictive context; {care.get('reactive_only', 0):,} are reactive only. Contact grain remains separate from root-incident grain.</span></div>
          <div class="lpr-story-card"><div class="lpr-story-no">03</div><strong>Control</strong><span>{workload.get('pending_approvals', 0):,} approval object(s) remain pending. Approvals are workload, not an additive incident status.</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    left, right = st.columns([1.35, 1])
    with left:
        _section("Leading indicators", "Highest-priority risk-ticket records")
        risk_rows = list(predictive_page.get("rows", []))
        ranked = sorted(
            risk_rows,
            key=lambda row: (
                {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(
                    str(row.get("severity")),
                    9,
                ),
                0 if row.get("ticket_class") == "proactive" else 1,
            ),
        )[:8]
        if ranked:
            st.dataframe(
                _predictive_table(ranked),
                hide_index=True,
                use_container_width=True,
            )
            total = predictive_page.get("total")
            st.caption(
                f"Showing {len(ranked):,} prioritized ticket rows from {total:,} total "
                "ticket records. Executive totals above use unique services from the "
                "complete projection, not this display page."
                if total is not None
                else "Displayed rows do not drive executive totals."
            )
        else:
            st.info("No predictive service risks in this run.")
    with right:
        _section("Customer impact", "Care priority is not network-risk severity")
        stories = projection.get("stories", [])
        p1 = sum((row.get("care_ticket") or {}).get("priority") == "P1" for row in stories)
        p2 = sum((row.get("care_ticket") or {}).get("priority") == "P2" for row in stories)
        p3 = sum((row.get("care_ticket") or {}).get("priority") == "P3" for row in stories)
        cols = st.columns(3)
        cols[0].metric("P1 Care contacts", p1)
        cols[1].metric("P2 Care contacts", p2)
        cols[2].metric("P3 Care contacts", p3)
        st.caption(
            "Care priority is scenario-driven customer impact. Predictive severity is "
            "threshold and time-to-breach risk; the two are intentionally not forced to match."
        )
        governance = projection.get("governance", {})
        if governance.get("data_integrity_gate_passed"):
            st.success(
                f"Data-integrity gate passed · "
                f"{governance.get('data_integrity_controls', 0)} controls"
            )
        else:
            st.error("Data-integrity gate did not pass for this run.")

    reconciliation = projection.get("reconciliation", {})
    if reconciliation.get("passed"):
        st.success("All shared measurement invariants reconcile for this active run.")
    else:
        st.error("One or more shared measurement invariants failed.")
    with st.expander("Metric definitions and reconciliation checks", expanded=False):
        st.json(
            {
                "measurement_context": projection.get("measurement_context"),
                "reconciliation": reconciliation,
                "data_completeness": projection.get("data_completeness"),
            }
        )

    try:
        install_projection = _request(
            f"/api/runs/{urllib.parse.quote(run_id)}/install-assurance/projection"
        )
    except Exception:
        install_projection = None
    if install_projection:
        install_metrics = install_projection["summary"]["metrics"]
        install_pass = install_metrics["pass_rate_24h"]
        _section(
            "Installation assurance",
            "24-hour new-install supervision",
            "Assurance-episode metrics are separate from break/fix incidents.",
        )
        install_cols = st.columns(5)
        install_cols[0].metric(
            "Install assurance cohort",
            f"{install_metrics['episodes_entering_watch']:,}",
        )
        install_cols[1].metric(
            "Matured",
            f"{install_metrics['matured_episodes']:,}",
        )
        install_cols[2].metric(
            "Passed 24h",
            "—"
            if install_pass["value"] is None
            else f"{100 * install_pass['value']:.1f}%",
        )
        install_cols[3].metric(
            "Promoted to incident",
            f"{install_metrics['episodes_promoted_to_incident']:,}",
        )
        install_cols[4].metric(
            "Network before call",
            f"{install_metrics['network_before_call_contacts']:,}",
        )
        st.caption(
            "Healthy installations remain assurance episodes. Only persistent or "
            "severe defects are promoted to a root incident."
        )

    with st.expander("Executive demo talk track", expanded=False):
        st.markdown(
            """
            **1. Establish context.** Name the active run, as-of time, population, scan coverage and root-incident grain before quoting a number.
            **2. Reconcile the waterfall.** Forecast risk plus current degradation equals unique at-risk services; matched plus reactive contacts equals all Care contacts; the five incident states equal root incidents.
            **3. Separate workload from status.** Case attempts, contacts and approvals are related objects, not additional incident totals.
            **4. End with governance.** Deterministic controls remain authoritative, actions are gated, and closure requires objective restoration evidence.
            """
        )


def _create_demo() -> None:
    _section(
        "Create a boardroom scenario",
        "Choose the population and evidence density, then generate one governed run",
        (
            "Footprint size, predictive coverage, case attempts and root incidents are "
            "different populations. The selected profile makes that relationship explicit."
        ),
    )

    preset_cols = st.columns(3)
    if preset_cols[0].button("Boardroom · 500 services", use_container_width=True):
        st.session_state["demo_homes"] = 500
        st.session_state["demo_profile"] = "smoke"
    if preset_cols[1].button("Operations · 5,000 services", use_container_width=True):
        st.session_state["demo_homes"] = 5000
        st.session_state["demo_profile"] = "board"
    if preset_cols[2].button("Footprint · 500,000 services", use_container_width=True):
        st.session_state["demo_homes"] = 500000
        st.session_state["demo_profile"] = "full"
    st.session_state.setdefault("demo_homes", 500)
    st.session_state.setdefault("demo_profile", "smoke")

    controls = st.columns([1, 1, 2])
    homes = controls[0].number_input(
        "Services in the digital footprint",
        min_value=1,
        max_value=500000,
        key="demo_homes",
    )
    profile = controls[1].selectbox(
        "Evidence-density profile",
        ["smoke", "preview", "board", "full"],
        key="demo_profile",
        help=(
            "Smoke keeps the minimum scenario cases. Preview/board/full scale case "
            "attempts with the footprint. Predictive coverage remains separately configurable."
        ),
    )
    scenarios = controls[2].multiselect(
        "Customer and network stories",
        list(SCENARIO_LABELS),
        default=["slow_wifi", "fiber_cut", "power_outage"],
        format_func=lambda value: SCENARIO_LABELS[value],
    )

    minimum_cases = len(scenarios) * 2
    expected_cases = (
        minimum_cases
        if profile == "smoke"
        else max(minimum_cases, round(int(homes) * 0.005))
    )
    st.info(
        f"Selected context: {int(homes):,} eligible services · approximately "
        f"{expected_cases:,} case attempts before repeat consolidation · predictive "
        "population configured independently below."
    )

    st.markdown(
        """
        <div class="lpr-story-grid">
          <div class="lpr-story-card"><div class="lpr-story-no">A</div><strong>Predictive assurance</strong><span>Separate eligible footprint, scanned devices, unique at-risk services and risk-ticket rows.</span></div>
          <div class="lpr-story-card"><div class="lpr-story-no">B</div><strong>Customer correlation</strong><span>Count contacts at contact grain and link each to one durable root incident.</span></div>
          <div class="lpr-story-card"><div class="lpr-story-no">C</div><strong>Governed resolution</strong><span>Keep case attempts and approvals outside the mutually exclusive incident-status partition.</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    enable_predictive = st.checkbox("Include predictive modem intelligence", value=True)
    predictive_days = 14
    predictive_population = 0
    provider = "fake"
    model = ""
    with st.expander("Advanced model & simulation settings", expanded=False):
        predictive_population = st.number_input(
            "Predictive modem population (0 = profile default)",
            min_value=0,
            max_value=500000,
            value=0,
            disabled=not enable_predictive,
        )
        predictive_days = st.slider(
            "Trend window (days)", 7, 60, 14, disabled=not enable_predictive
        )
        provider = st.selectbox("AI provider", ["fake", "disabled", "openai", "anthropic"])
        enable_llm = provider in {"openai", "anthropic"}
        model = st.text_input("Model name", disabled=not enable_llm)
        st.caption("Fake is deterministic and recommended for an offline executive demo.")

    enable_llm = provider in {"openai", "anthropic"}
    if st.button("Generate executive demo", type="primary", use_container_width=True):
        payload = {
            "config": {
                "profile": profile,
                "homes": int(homes),
                "scenarios": scenarios,
                "enable_llm": enable_llm,
                "llm_provider": provider,
                "llm_model": model,
                "enable_predictive": enable_predictive,
                "predictive_population": int(predictive_population),
                "predictive_days": int(predictive_days),
            }
        }
        try:
            with st.spinner(
                "Building the canonical run, predictive risks and Care correlation…"
            ):
                result = _request("/api/runs", "POST", payload)
            _remember_run(result["run_id"])
            st.success(
                "Executive demo ready — all data-integrity controls passed."
                if result["quality"]["passed"]
                else "Demo generated, but the data-integrity gate needs attention."
            )
            scale = result.get("operational_scale", {})
            metrics = st.columns(5)
            metrics[0].metric("Services", f"{scale.get('homes', 0):,}")
            metrics[1].metric(
                "Devices scanned",
                f"{scale.get('predictive_modems_scanned', 0):,}",
            )
            metrics[2].metric("Case attempts", f"{scale.get('case_attempts', 0):,}")
            metrics[3].metric("Root incidents", f"{scale.get('root_incidents', 0):,}")
            metrics[4].metric(
                "Data-integrity controls",
                f"{result['quality'].get('checks', 0)} passed",
            )
            _run_chip(result["run_id"])
            with st.expander("Technical generation record", expanded=False):
                st.json(result)
        except Exception as exc:
            st.error(str(exc))


def _predictive_health() -> None:
    _section(
        "Prevent",
        "Predictive network health",
        (
            "Canonical headline values use unique services and complete run aggregates. "
            "Risk-ticket tables are display pages and never drive the KPI totals."
        ),
    )
    run_id = _run_id("predictive_run")
    if not run_id:
        _empty(
            "No demo run selected",
            "Create a demo first. Predictive health will use the persisted active run.",
        )
        return

    try:
        projection = _projection(run_id)
        ticket_page = _load_dataset_page(run_id, "predictive_tickets", limit=500)
    except Exception as exc:
        st.error(str(exc))
        return

    render_measurement_context(projection, title="Canonical predictive context")
    funnel = projection.get("predictive_funnel", {})
    cols = st.columns(6)
    cols[0].metric("Services in footprint", f"{funnel.get('eligible_services', 0):,}")
    cols[1].metric("Devices scanned", f"{funnel.get('scanned_devices', 0):,}")
    cols[2].metric(
        "Scan coverage",
        format_metric(metric_value(projection, "scan_coverage_pct"), percent=True),
    )
    cols[3].metric(
        "Forecast-risk services",
        f"{funnel.get('forecast_risk_services', 0):,}",
    )
    cols[4].metric(
        "Currently degraded",
        f"{funnel.get('degraded_services', 0):,}",
    )
    cols[5].metric("Unique at-risk services", f"{funnel.get('at_risk_services', 0):,}")

    matched = int(projection.get("care_funnel", {}).get("predictively_matched", 0) or 0)
    if matched:
        st.markdown(
            f'<div class="lpr-insight"><strong>Customer impact connection.</strong> '
            f'{matched:,} Care contact(s) in the canonical run are already linked to '
            f'predictive modem evidence. Open Customer Experience to follow the same '
            f'contact and root-incident identifiers.</div>',
            unsafe_allow_html=True,
        )

    _section("Prioritized view", "Risk-ticket records worth discussing")
    tickets = list(ticket_page.get("rows", []))
    if tickets:
        ranked = sorted(
            tickets,
            key=lambda row: (
                {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(
                    str(row.get("severity")),
                    9,
                ),
                0 if row.get("ticket_class") == "proactive" else 1,
            ),
        )
        st.dataframe(
            _predictive_table(ranked[:100]),
            hide_index=True,
            use_container_width=True,
        )
        st.caption(
            f"Showing {min(100, len(ranked)):,} of {ticket_page.get('total', len(ranked)):,} "
            "risk-ticket rows. The KPI above counts unique services, so ticket and "
            "service counts are not silently treated as the same grain."
        )
    else:
        st.success("No predictive service risks in the current run.")

    with st.expander("Run an exploratory child scan", expanded=False):
        st.warning(
            "A child scan has its own population, trend window and simulation day. "
            "It does not change the canonical parent run, executive KPIs or Care queue."
        )
        pcols = st.columns(3)
        population = pcols[0].number_input(
            "Devices to scan", min_value=1, max_value=500000, value=500, step=100
        )
        days = pcols[1].slider("Trend days", 7, 60, 14)
        day_index = pcols[2].number_input(
            "Simulation day", min_value=0, max_value=365, value=0
        )
        if st.button("Create exploratory scan", type="primary"):
            try:
                summary = _request(
                    f"/api/runs/{urllib.parse.quote(run_id)}/predictive/scans",
                    "POST",
                    {
                        "population": int(population),
                        "days": int(days),
                        "day_index": int(day_index),
                    },
                )
                st.session_state["predictive_scan_id"] = summary["scan_id"]
                st.session_state["predictive_summary"] = summary
            except Exception as exc:
                st.error(str(exc))

        summary = st.session_state.get("predictive_summary")
        if summary and summary.get("canonical_run_id") == run_id:
            st.markdown(
                f"**Exploratory scan:** `{summary.get('scan_id')}` · "
                f"parent `{run_id}` · {summary.get('effective_population', 0):,} devices · "
                f"day {summary.get('day_index', 0)} · not promoted to canonical run"
            )
            _show_predictive_summary(summary)
            scan_id = summary["scan_id"]
            try:
                detail = _request(
                    f"/api/runs/{urllib.parse.quote(run_id)}/predictive/scans/"
                    f"{urllib.parse.quote(scan_id)}?limit=500"
                )
                st.dataframe(
                    _predictive_table(detail["tickets"]),
                    hide_index=True,
                    use_container_width=True,
                )
                with st.expander("Raw child-scan modem evidence"):
                    st.dataframe(detail["pulls"], use_container_width=True)
            except Exception as exc:
                st.error(str(exc))


def _customer_experience() -> None:
    _section(
        "Connect",
        "Customer experience & Care correlation",
        (
            "Care is measured at contact grain. Each contact is linked to one canonical "
            "root incident without implying that every attachment represents an audited "
            "duplicate-creation attempt."
        ),
    )
    st.caption(
        "Target presentation layer: DvSum CADDI inside Genesys. The demo uses canonical run "
        "evidence and does not claim a live DvSum CADDI connection."
    )
    run_id = _run_id("care_run")
    if not run_id:
        _empty(
            "No Care story yet",
            "Create a demo first. The Care queue will use the persisted active run.",
        )
        return

    try:
        projection = _projection(run_id)
    except Exception as exc:
        st.error(str(exc))
        return
    render_measurement_context(projection, title="Canonical Care context")

    filters = st.columns(3)
    status = filters[0].selectbox(
        "Ticket status",
        ["ALL", "OPEN", "CLOSED"],
        format_func=lambda value: "All statuses" if value == "ALL" else _friendly(value),
    )
    priority = filters[1].selectbox(
        "Customer priority",
        ["ALL", "P1", "P2", "P3"],
        format_func=lambda value: "All priorities" if value == "ALL" else value,
    )
    pred_filter = filters[2].selectbox(
        "Network saw it first",
        ["ALL", "MATCHED", "UNMATCHED"],
        format_func=lambda value: {
            "ALL": "All contacts",
            "MATCHED": "Yes — predictive evidence",
            "UNMATCHED": "No — reactive only",
        }[value],
    )

    params = {"limit": 200}
    if status != "ALL":
        params["status"] = status
    if priority != "ALL":
        params["priority"] = priority
    if pred_filter != "ALL":
        params["predictive_match"] = "true" if pred_filter == "MATCHED" else "false"
    suffix = f"?{urllib.parse.urlencode(params)}"
    try:
        response = _request(
            f"/api/runs/{urllib.parse.quote(run_id)}/care/tickets{suffix}"
        )
    except Exception as exc:
        st.error(str(exc))
        return

    queue = list(response.get("rows", []))
    summary = response.get("summary", {})
    filtered_total = int(response.get("filtered_total", len(queue)) or 0)
    cols = st.columns(5)
    cols[0].metric("Filtered Care contacts", f"{filtered_total:,}")
    cols[1].metric(
        "Predictively matched",
        f"{int(summary.get('predictively_matched', 0)):,}",
    )
    cols[2].metric("Reactive only", f"{int(summary.get('reactive_only', 0)):,}")
    cols[3].metric("P1 contacts", f"{int(summary.get('p1', 0)):,}")
    cols[4].metric("Repeat contacts", f"{int(summary.get('repeat_contacts', 0)):,}")
    st.caption(
        f"Showing {response.get('returned', len(queue)):,} of {filtered_total:,} filtered "
        f"contacts; canonical run total is {response.get('total', filtered_total):,}. "
        "The summary is calculated across the full filtered population, not the page rows."
    )

    care_funnel = projection.get("care_funnel", {})
    st.info(
        f"Canonical run reconciliation: {care_funnel.get('predictively_matched', 0):,} "
        f"matched + {care_funnel.get('reactive_only', 0):,} reactive-only = "
        f"{care_funnel.get('contacts', 0):,} Care contacts; "
        f"{care_funnel.get('canonical_root_attachments', 0):,} carry a root incident ID."
    )

    if not queue:
        st.info("No Care contacts match the current filters.")
        return

    st.dataframe(_care_table(queue), hide_index=True, use_container_width=True)
    care_id = st.selectbox(
        "Choose a customer story",
        [row["care_ticket_id"] for row in queue],
        format_func=lambda value: next(
            f"{row['priority']} · {_friendly(row['category'])} · "
            f"{'predictive match' if row['predictive_match'] else 'reactive only'}"
            for row in queue
            if row["care_ticket_id"] == value
        ),
    )
    try:
        detail = _request(
            f"/api/runs/{urllib.parse.quote(run_id)}/care/tickets/"
            f"{urllib.parse.quote(care_id)}"
        )
    except Exception as exc:
        st.error(str(exc))
        return

    ticket = detail["ticket"]
    predictive = detail.get("predictive")
    review = detail.get("review") or {}
    case = detail.get("case") or {}

    st.markdown(
        f'<div class="lpr-insight"><strong>{html.escape(str(ticket.get("priority")))}</strong> · '
        f'{html.escape(_friendly(ticket.get("category")))} — '
        f'{html.escape(str(ticket.get("issue_summary", "Customer reported a service issue.")))}</div>',
        unsafe_allow_html=True,
    )
    left, middle, right = st.columns(3)
    with left:
        st.markdown("### Customer contact")
        st.metric("Status", _friendly(ticket.get("status")))
        st.write(f"**Contact ID:** {ticket.get('contact_id')}")
        st.write(f"**Channel:** {_friendly(ticket.get('channel'))}")
        st.write(f"**Opened:** {_timestamp(ticket.get('opened_at'))}")
        st.write(f"**Repeat contact:** {'Yes' if ticket.get('repeat_contact') else 'No'}")
    with middle:
        st.markdown("### Network-risk evidence")
        if predictive:
            signal, eta = _predictive_headline(predictive)
            st.metric("Seen before contact", "Yes")
            st.write(
                f"**Risk:** {_friendly(predictive.get('ticket_class'))} · "
                f"{_friendly(predictive.get('severity'))}"
            )
            st.write(f"**Leading signal:** {signal}")
            st.write(f"**Threshold timing:** {eta}")
        else:
            st.metric("Seen before contact", "No")
            st.caption("This is a reactive-only Care contact in the synthetic run.")
    with right:
        st.markdown("### Root incident & governed decision")
        st.metric("Root incident", ticket.get("incident_id") or "—")
        st.write(
            f"**Human review:** "
            f"{'Required' if review.get('reconciled_human_review_required') else 'Not required'}"
        )
        st.write(f"**Domain:** {_friendly(review.get('deterministic_domain'))}")
        st.write(f"**Recommended action:** {_friendly(review.get('deterministic_action'))}")
        st.write(f"**Case state:** {_friendly(case.get('state'))}")

    if ticket.get("incident_id"):
        st.success(
            "Canonical attachment confirmed: the Care contact references the durable "
            "root incident and inherits its context. The demo does not emit a separate "
            "audited duplicate-attempt event, so this is not labelled as duplicates avoided."
        )

    with st.expander("Technical evidence & reconciliation", expanded=False):
        detail_tabs = st.tabs(
            ["Care contact", "Predictive evidence", "Decision review", "Control-plane case"]
        )
        with detail_tabs[0]:
            st.json(ticket)
        with detail_tabs[1]:
            if predictive:
                st.json(predictive)
            else:
                st.info("No predictive modem ticket preceded this contact.")
        with detail_tabs[2]:
            st.json(review)
        with detail_tabs[3]:
            st.json(case)


def _caddi_layer() -> None:
    contract = caddi_contract()
    summary = contract["summary"]
    _section(
        "Existing call-center layer",
        "DvSum CADDI & Genesys integration boundary",
        (
            "Make the existing LPR call-center correlation investment explicit, "
            "preserve source authority, and identify where the assurance layer should "
            "augment rather than create a second source of truth."
        ),
    )

    cols = st.columns(4)
    cols[0].metric("Mapped capability domains", summary["capability_domains"])
    cols[1].metric("Declared existing in DvSum CADDI", summary["declared_existing"])
    cols[2].metric("Known data gaps", summary["known_gaps"])
    cols[3].metric("Live DvSum CADDI adapter", "Not connected")

    st.warning(
        "Contract-only status. The mapping below is based on LPR stakeholder input; "
        "DvSum CADDI APIs, field definitions, source precedence, latency, retention, ownership "
        "and contractor roadmap still require joint discovery."
    )
    st.info(contract["source_of_truth_policy"] + " " + contract["operations_boundary"])

    left, right = st.columns(2)
    with left:
        st.markdown("### DvSum CADDI remains")
        st.markdown(
            """
            - The Genesys-facing call-center context and correlation experience.
            - A presentation of billing, outage, provisioning and service evidence.
            - The place where an agent sees an existing issue and the best current route.
            """
        )
    with right:
        st.markdown("### Assurance layer adds")
        st.markdown(
            """
            - Predictive detection, evidence lineage and fault-side localization.
            - Governed next-best action and correlation to one root incident.
            - Maintenance/repair handoff, validation and customer-safe status back to DvSum CADDI.
            """
        )

    st.dataframe(caddi_contract_rows(), hide_index=True, use_container_width=True)
    with st.expander("DvSum CADDI architecture decision gate", expanded=False):
        st.markdown(
            f"""
            **Preferred pattern:** `{contract['preferred_pattern']}`

            **Replacement policy:** `{contract['replacement_policy']}`


            Stage 2 keeps the Stage 1 DvSum CADDI contract intact while applying the shared
            measurement model to active-run and Operations evidence. A live DvSum CADDI adapter or
            replacement decision remains out of scope until the DvSum CADDI owner, Genesys owner,
            source-system teams and contractor confirm the architecture and responsibilities.
            """
        )


def _subscriber_story() -> None:
    _section(
        "Drill down",
        "Subscriber story",
        "Bring the modem, alarms, customer contacts, incident and resolution evidence together around one service.",
    )
    run_id = _run_id("sub_run")
    if not run_id:
        _empty("No subscriber context yet", "Create a demo first, then use a service ID to tell the end-to-end customer story.")
        return
    _run_chip(run_id)
    service_id = st.text_input("Service ID", value="SVC-0000001")
    if st.button("Open subscriber story", type="primary"):
        try:
            st.session_state["subscriber_detail"] = _request(
                f"/api/runs/{urllib.parse.quote(run_id)}/subscriber/{urllib.parse.quote(service_id)}"
            )
        except Exception as exc:
            st.error(str(exc))
    result = st.session_state.get("subscriber_detail")
    if not result:
        return
    subscriber = result["subscriber"]
    related = result["related"]
    cols = st.columns(4)
    cols[0].metric("Access", subscriber.get("technology", "—"))
    cols[1].metric("Region", _friendly(subscriber.get("region")))
    cols[2].metric("Device", subscriber.get("device_id", "—"))
    cols[3].metric("Serving point", subscriber.get("delimiter_id", "—"))
    st.caption(f"Customer {subscriber.get('customer_id')} · Account {subscriber.get('service_account_id')} · Premise {subscriber.get('premise_id')}")

    story_order = [
        "predictive_tickets",
        "telemetry_tr181",
        "nxt_alarms",
        "care_tickets",
        "incidents",
        "work_orders",
        "field_evidence",
        "validation_events",
        "resolution_events",
    ]
    for name in story_order:
        rows = related.get(name, [])
        if not rows:
            continue
        with st.expander(f"{DATASET_LABELS.get(name, _friendly(name))} · {len(rows)} record(s)", expanded=name in {"predictive_tickets", "care_tickets", "incidents"}):
            if name == "predictive_tickets":
                st.dataframe(_predictive_table(rows), hide_index=True, use_container_width=True)
            elif name == "care_tickets":
                st.dataframe(_care_table(rows), hide_index=True, use_container_width=True)
            else:
                st.dataframe(rows, hide_index=True, use_container_width=True)


def _decision_control() -> None:
    _section(
        "Govern",
        "Decision & operating controls",
        "AI can recommend; deterministic controls define what is allowed. Human approval remains explicit where the workflow requires it.",
    )
    run_id = _run_id("decision_run")
    if not run_id:
        _empty("No decision case selected", "Create a demo first, then load a case to show the control plane.")
        return
    _run_chip(run_id)
    case_id = st.text_input("Case ID", value="CASE-0000001-SLOW_WIFI")
    if st.button("Open governed case"):
        try:
            st.session_state["case"] = _request(
                f"/api/runs/{urllib.parse.quote(run_id)}/cases/{urllib.parse.quote(case_id)}"
            )
        except Exception as exc:
            st.error(str(exc))
    case = st.session_state.get("case")
    if not case:
        return
    state_cols = st.columns(3)
    state_cols[0].metric("Case state", _friendly(case.get("state")))
    state_cols[1].metric("Revision", case.get("revision", "—"))
    state_cols[2].metric("Human gate", "Waiting" if case.get("state") == "WAITING_HUMAN" else "Resolved / not required")

    if case.get("state") == "WAITING_HUMAN":
        st.warning("A side effect is waiting for an authorized human decision.")
        response = st.selectbox(
            "Decision",
            ["approve", "reject", "request_evidence", "escalate"],
            format_func=lambda value: {
                "approve": "Approve governed action",
                "reject": "Reject action",
                "request_evidence": "Request more evidence",
                "escalate": "Escalate to supervisor",
            }[value],
        )
        rationale = st.text_area("Decision rationale", placeholder="Explain the business / operational reason for the decision")
        if st.button("Submit governed decision", type="primary"):
            payload = {
                "case_id": case["case_id"],
                "revision": case["revision"],
                "response": response,
                "actor": USER,
                "rationale": rationale or "Operator decision",
            }
            try:
                updated = _request(
                    f"/api/runs/{urllib.parse.quote(run_id)}/decisions", "POST", payload
                )
                st.session_state["case"] = updated
                st.success(f"Case state: {_friendly(updated['state'])}")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    with st.expander("Technical case record", expanded=False):
        st.json(case)


def _evidence() -> None:
    _section(
        "Trust",
        "Evidence, audit & release controls",
        "Keep raw data available for technical validation without making it the center of the executive demo.",
    )
    run_id = _run_id("data_run")
    data_tab, release_tab = st.tabs(["Evidence explorer", "Release assurance"])
    with data_tab:
        if not run_id:
            _empty("No run selected", "Create a demo first; technical evidence is stored against the canonical run.")
        else:
            _run_chip(run_id)
            dataset = st.selectbox(
                "Evidence set",
                DATASETS,
                format_func=lambda value: DATASET_LABELS[value],
            )
            limit = st.slider("Rows to display", 10, 1000, 100, 10)
            if st.button("Load evidence"):
                try:
                    result = _request(
                        f"/api/runs/{urllib.parse.quote(run_id)}/datasets/{dataset}?limit={limit}"
                    )
                    st.caption(f"Showing {result['returned']} of {result['total']} records")
                    st.dataframe(result["rows"], use_container_width=True)
                    st.download_button(
                        "Download displayed evidence (JSON)",
                        json.dumps(result["rows"], indent=2),
                        file_name=f"{dataset}.json",
                        mime="application/json",
                    )
                except Exception as exc:
                    st.error(str(exc))
    with release_tab:
        cols = st.columns(4)
        cols[0].metric("Runtime", "Python 3.14.7")
        cols[1].metric("Canonical datasets", "20")
        cols[2].metric("Production writes", "Disabled")
        cols[3].metric("Operating model", "Fail closed")
        st.success("Unified Docker stack · one Streamlit experience · predictive + Customer Care + governed action flow")
        st.markdown(
            """
            **What the demo proves**
            - Predictive modem evidence and Customer Care are correlated through the same service and root incident.
            - DvSum CADDI is explicitly positioned as the Genesys call-center context layer; no live DvSum CADDI adapter is claimed.
            - Deterministic operating controls remain authoritative when an AI recommendation differs.
            - Dispatch requires diagnosis plus skills, parts and access readiness.
            - CPE replacement requires failed diagnostics or a documented reason.
            - Closure requires objective restoration evidence and the repair checklist.
            - Repeat cases remain linked and escalate rather than resetting the operating clock.
            """
        )



def _install_episode_table(rows: list[dict]) -> list[dict]:
    return [
        {
            "Episode": row.get("episode_id"),
            "Service": row.get("service_id"),
            "Access": row.get("technology"),
            "Age": f"{float(row.get('age_hours', 0)):.1f}h",
            "Lifecycle": _friendly(row.get("lifecycle_state")),
            "Health": row.get("health_state"),
            "Leading finding": row.get("leading_finding"),
            "Current owner": _friendly(row.get("current_owner")),
            "Root incident": row.get("incident_id") or "None — assurance only",
        }
        for row in rows
    ]


def _install_assurance() -> None:
    _section(
        "Assure",
        "24-Hour Install Assurance Watch",
        "Supervise new HFC and PON installations as assurance episodes. Healthy "
        "installs pass without becoming incidents; persistent faults are promoted "
        "once to a governed root incident.",
    )
    run_id = _run_id("install_run")
    if not run_id:
        _empty(
            "No active run",
            "Create a Digital Twin run first, then start an install assurance cohort.",
        )
        return
    _run_chip(run_id)
    st.caption(
        "Install-watch metrics use assurance-episode grain and remain separate from "
        "break/fix incident KPIs. The parent run remains immutable."
    )

    with st.expander("Create or replay an install watch", expanded=False):
        controls = st.columns(4)
        population = controls[0].number_input(
            "New installs",
            min_value=2,
            max_value=5_000,
            value=12,
            step=1,
        )
        as_of_hours = controls[1].slider("Snapshot age", 0.0, 48.0, 24.0, 1.0)
        stability_tail = controls[2].slider("Post-action stability tail", 1.0, 12.0, 4.0, 1.0)
        seed = controls[3].number_input("Cohort seed", min_value=0, value=0, step=1)
        if st.button("Start 24-hour assurance watch", type="primary"):
            try:
                with st.spinner("Building the supervised install cohort…"):
                    summary = _request(
                        f"/api/runs/{urllib.parse.quote(run_id)}/install-assurance/watches",
                        "POST",
                        {
                            "population": int(population),
                            "as_of_hours": float(as_of_hours),
                            "stability_tail_hours": float(stability_tail),
                            "seed": int(seed),
                        },
                    )
                st.session_state["install_watch_id"] = summary["watch_id"]
                st.success("Install assurance watch created without changing the parent run.")
            except Exception as exc:
                st.error(str(exc))

    try:
        projection = _request(
            f"/api/runs/{urllib.parse.quote(run_id)}/install-assurance/projection"
        )
    except Exception:
        st.info("No install assurance cohort exists for this run yet.")
        return

    summary = projection["summary"]
    metrics = summary["metrics"]
    pass_rate = metrics["pass_rate_24h"]
    conversion = metrics["incident_conversion_rate"]
    before_call = metrics["network_before_call_rate"]
    top = st.columns(6)
    top[0].metric("Installs under watch", f"{metrics['episodes_entering_watch']:,}")
    top[1].metric("Matured episodes", f"{metrics['matured_episodes']:,}")
    top[2].metric(
        "24-hour pass rate",
        "—" if pass_rate["value"] is None else f"{100 * pass_rate['value']:.1f}%",
        help="Passed episodes divided by episodes whose effective watch window matured.",
    )
    top[3].metric("Promoted installs", f"{metrics['episodes_promoted_to_incident']:,}")
    top[4].metric(
        "Incident conversion",
        "—" if conversion["value"] is None else f"{100 * conversion['value']:.1f}%",
    )
    top[5].metric(
        "Network before call",
        "—" if before_call["value"] is None else f"{100 * before_call['value']:.1f}%",
    )

    lifecycle = summary["lifecycle_partition"]
    health = summary["health_partition"]
    left, right = st.columns(2)
    with left:
        _section("Episode state", "Lifecycle partition")
        st.dataframe(
            [{"Lifecycle": _friendly(key), "Episodes": value} for key, value in lifecycle.items()],
            hide_index=True,
            use_container_width=True,
        )
    with right:
        _section("Service health", "Current watch health")
        st.dataframe(
            [{"Health": key, "Episodes": value} for key, value in health.items()],
            hide_index=True,
            use_container_width=True,
        )

    episodes = list(projection.get("episodes", []))
    _section("Supervision queue", "Installation episodes")
    st.dataframe(_install_episode_table(episodes), hide_index=True, use_container_width=True)
    if not episodes:
        return
    episode_id = st.selectbox(
        "Choose an installation story",
        [row["episode_id"] for row in episodes],
        format_func=lambda value: next(
            f"{row['technology']} · {_friendly(row['lifecycle_state'])} · "
            f"{row['service_id']}"
            for row in episodes
            if row["episode_id"] == value
        ),
    )
    selected = next(row for row in episodes if row["episode_id"] == episode_id)
    caddi = next(
        (
            row
            for row in projection.get("caddi_contexts") or projection.get("caddi_contexts", [])
            if row.get("episode_id") == episode_id
        ),
        None,
    )
    cols = st.columns(3)
    cols[0].metric("Watch state", _friendly(selected.get("lifecycle_state")))
    cols[1].metric("Health", selected.get("health_state", "—"))
    cols[2].metric("Incident", selected.get("incident_id") or "Not created")
    st.write(f"**Leading finding:** {selected.get('leading_finding')}")
    st.write(f"**Next action:** {_friendly(selected.get('next_action'))}")
    st.write(f"**Effective maturity:** {_timestamp(selected.get('effective_maturity_at'))}")
    if selected.get("network_before_call"):
        st.success("Network evidence preceded the Genesys contact; diagnostics are not restarted.")
    if selected.get("incident_id") is None:
        st.info("This remains an assurance episode and is not counted as a break/fix incident.")
    else:
        st.warning("Persistent evidence promoted this episode to one governed root incident.")

    with st.expander("DvSum CADDI & Genesys context", expanded=False):
        if caddi:
            st.json(caddi)
        else:
            st.info("No DvSum CADDI projection is available for this episode.")
    with st.expander("Technical assurance episode", expanded=False):
        st.json(selected)



def _external_evidence() -> None:
    _section(
        "Import & triangulate",
        "External CSV evidence",
        "Load NXT, DvSum CADDI, Genesys and JTrack exports into an immutable, "
        "read-only scenario. Deterministic controls validate every row; an optional "
        "LLM agent triangulates the accepted evidence and flags inconsistencies.",
    )
    st.warning(
        "Simulation and analysis only. Imported files never write back to NXT, "
        "DvSum CADDI, Genesys, JTrack or production incident systems."
    )
    try:
        contract = _request("/api/external-evidence/contract")
        batches = _request("/api/import-batches")
    except Exception as exc:
        st.error(f"External evidence service unavailable: {exc}")
        return

    source_order = [
        "identity_map",
        "nxt_telemetry",
        "nxt_alarms",
        "dvsum_caddi_insights",
        "genesys_interactions",
        "jtrack_events",
        "install_cohort",
    ]
    source_labels = {
        source: contract["sources"][source]["label"] for source in source_order
    }

    create_tab, upload_tab, review_tab = st.tabs(
        ["1 · Create / select", "2 · Upload & validate", "3 · Analyze & recommend"]
    )
    with create_tab:
        cols = st.columns([1, 1, 1])
        mode = cols[0].selectbox(
            "Replay mode",
            ["historical_replay", "point_in_time", "install_watch", "shadow"],
            format_func=lambda value: _friendly(value),
            key="external_mode",
        )
        name = cols[1].text_input(
            "Batch name",
            value="External evidence replay",
            key="external_batch_name",
        )
        as_of = cols[2].text_input(
            "As-of time (ISO-8601, optional)",
            placeholder="2026-08-27T09:12:00Z",
            key="external_as_of",
        )
        if st.button("Create immutable import batch", type="primary", use_container_width=True):
            try:
                result = _request(
                    "/api/import-batches",
                    "POST",
                    {"mode": mode, "name": name, "as_of": as_of or None},
                )
                st.session_state["external_batch_id"] = result["batch_id"]
                st.session_state.pop("external_quality", None)
                st.session_state.pop("external_analysis", None)
                st.success(f"Created {result['batch_id']}")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
        choices = [str(item.get("batch_id", "")) for item in batches if item.get("batch_id")]
        current = str(st.session_state.get("external_batch_id", ""))
        if choices:
            selected = st.selectbox(
                "Existing import batch",
                choices,
                index=choices.index(current) if current in choices else 0,
                format_func=lambda value: next(
                    (
                        f"{value} · {_friendly(item.get('mode'))} · "
                        f"{_friendly(item.get('status'))}"
                        for item in batches
                        if item.get("batch_id") == value
                    ),
                    value,
                ),
            )
            if selected != current:
                st.session_state["external_batch_id"] = selected
                st.session_state.pop("external_quality", None)
                st.session_state.pop("external_analysis", None)
        st.caption(
            "Identity resolution is deterministic: exact service, device, MAC, serial, "
            "tap/ODP and timestamp relationships take precedence over analytical text."
        )

    batch_id = str(st.session_state.get("external_batch_id", "")).strip()
    with upload_tab:
        if not batch_id:
            st.info("Create or select an import batch first.")
        else:
            st.markdown(f"**Active import batch:** `{batch_id}`")
            st.caption(
                "Use UTF-8 CSV with ISO-8601 timestamps including a timezone. Raw files "
                "are retained unchanged with SHA-256 lineage."
            )
            for source in source_order:
                left, middle, right = st.columns([1.2, 2.2, 1])
                with left:
                    st.markdown(f"**{source_labels[source]}**")
                    st.caption(contract["sources"][source]["grain"])
                with middle:
                    uploaded = st.file_uploader(
                        f"Upload {source_labels[source]}",
                        type=["csv"],
                        key=f"external_upload_{source}",
                        label_visibility="collapsed",
                    )
                with right:
                    try:
                        template = _request(f"/api/external-evidence/templates/{source}")
                        st.download_button(
                            "CSV template",
                            template["content"],
                            file_name=template["filename"],
                            mime="text/csv",
                            key=f"external_template_{source}",
                            use_container_width=True,
                        )
                    except Exception:
                        pass
                if uploaded is not None and st.button(
                    f"Store {source_labels[source]}",
                    key=f"external_store_{source}",
                    use_container_width=True,
                ):
                    try:
                        content = uploaded.getvalue().decode("utf-8-sig")
                        result = _request(
                            f"/api/import-batches/{urllib.parse.quote(batch_id)}/files/{source}",
                            "POST",
                            {
                                "filename": uploaded.name,
                                "content": content,
                                "replace": True,
                            },
                        )
                        st.session_state.pop("external_quality", None)
                        st.session_state.pop("external_analysis", None)
                        st.success(
                            f"Stored {result['original_filename']} · "
                            f"SHA-256 {result['sha256'][:12]}…"
                        )
                    except UnicodeDecodeError:
                        st.error("The file is not UTF-8 encoded.")
                    except Exception as exc:
                        st.error(str(exc))
            if st.button("Validate, normalize and correlate", type="primary", use_container_width=True):
                try:
                    with st.spinner("Validating schemas, identity, chronology and lineage…"):
                        quality = _request(
                            f"/api/import-batches/{urllib.parse.quote(batch_id)}/validate",
                            "POST",
                            {},
                        )
                    st.session_state["external_quality"] = quality
                    st.session_state.pop("external_analysis", None)
                    st.success(f"Validation status: {_friendly(quality['status'])}")
                except Exception as exc:
                    st.error(str(exc))
            quality = st.session_state.get("external_quality")
            if quality:
                counts = quality.get("issue_counts", {})
                metrics = st.columns(5)
                metrics[0].metric("Rows read", quality.get("total_rows", 0))
                metrics[1].metric("Accepted", quality.get("accepted_rows", 0))
                metrics[2].metric("Quarantined", quality.get("quarantined_rows", 0))
                metrics[3].metric("Warnings", counts.get("WARNING", 0))
                metrics[4].metric("Errors", counts.get("ERROR", 0))
                if quality.get("issues"):
                    st.dataframe(
                        quality["issues"],
                        hide_index=True,
                        use_container_width=True,
                    )

    with review_tab:
        if not batch_id:
            st.info("Create or select an import batch first.")
            return
        provider_cols = st.columns([1, 1, 1, 1])
        enable_llm = provider_cols[0].checkbox(
            "Run triangulation agent",
            value=True,
            help="Deterministic validation always runs first and remains authoritative.",
        )
        provider = provider_cols[1].selectbox(
            "Agent provider",
            ["fake", "disabled", "openai", "anthropic"],
            help="Fake is the deterministic offline agent used for a no-network demo.",
        )
        model = provider_cols[2].text_input(
            "Model",
            disabled=provider not in {"openai", "anthropic"},
            placeholder="Provider model name",
        )
        max_services = provider_cols[3].number_input(
            "Services sent to agent",
            min_value=1,
            max_value=50,
            value=25,
        )
        if st.button("Analyze and triangulate evidence", type="primary", use_container_width=True):
            try:
                with st.spinner(
                    "Running deterministic RCA, DvSum comparison and LLM triangulation…"
                ):
                    analysis = _request(
                        f"/api/import-batches/{urllib.parse.quote(batch_id)}/analyze",
                        "POST",
                        {
                            "enable_llm": enable_llm,
                            "llm_provider": provider,
                            "llm_model": model,
                            "max_services": int(max_services),
                        },
                    )
                st.session_state["external_analysis"] = analysis
            except Exception as exc:
                st.error(str(exc))
        analysis = st.session_state.get("external_analysis")
        if not analysis:
            st.info("Validate the batch, then run the analysis.")
            return
        invocation = analysis.get("agent_invocation", {})
        status_cols = st.columns(4)
        status_cols[0].metric("Provider", _friendly(invocation.get("provider")))
        status_cols[1].metric("Provider status", _friendly(invocation.get("provider_status")))
        status_cols[2].metric(
            "External call attempted",
            "Yes" if invocation.get("attempted_external_call") else "No",
        )
        status_cols[3].metric(
            "Human review",
            "Required" if analysis.get("human_review_required") else "Not required",
        )
        if invocation.get("error"):
            st.warning(f"Provider fallback: {invocation['error']}")
        st.info(
            "The deterministic quality and policy branch remains authoritative. "
            "The agent can add inconsistencies or explanations but cannot approve or execute an action."
        )
        recommendations = analysis.get("reconciled_recommendations", [])
        if recommendations:
            st.subheader("Reconciled action recommendations")
            st.dataframe(
                [
                    {
                        "Service": item.get("service_id"),
                        "Agent agreement": _friendly(item.get("agreement")),
                        "DvSum CADDI": _friendly(
                            (item.get("deterministic") or {}).get(
                                "dvsum_caddi_domain_agreement"
                            )
                        ),
                        "DvSum domain": _friendly(
                            (item.get("deterministic") or {}).get("dvsum_caddi_domain")
                        ),
                        "Domain": _friendly(
                            (item.get("authoritative_recommendation") or {}).get("domain")
                        ),
                        "Recommended action": _friendly(
                            (item.get("authoritative_recommendation") or {}).get("action")
                        ),
                        "Human review": "Required" if item.get("human_review_required") else "No",
                        "Execution": "Blocked — advisory only",
                    }
                    for item in recommendations
                ],
                hide_index=True,
                use_container_width=True,
            )
        llm = analysis.get("llm_triangulation", {})
        detail_tabs = st.tabs(
            [
                "Agent summary",
                "Inconsistencies",
                "Scenario projection",
                "Evidence timeline",
                "Raw report",
            ]
        )
        with detail_tabs[0]:
            st.write(llm.get("summary", "No agent summary."))
            st.metric("Agent confidence", f"{100 * float(llm.get('overall_confidence', 0)):.0f}%")
            for fact in llm.get("validated_facts", []):
                st.write(f"✓ {fact}")
            for missing in llm.get("missing_evidence", []):
                st.write(f"△ {missing}")
        with detail_tabs[1]:
            inconsistencies = llm.get("inconsistencies", [])
            if inconsistencies:
                st.dataframe(inconsistencies, hide_index=True, use_container_width=True)
            else:
                st.success("The agent did not add an inconsistency beyond deterministic validation.")
        with detail_tabs[2]:
            try:
                projection = _request(
                    f"/api/import-batches/{urllib.parse.quote(batch_id)}/projection"
                )
                metrics = projection.get("metrics", {})
                projection_cols = st.columns(5)
                projection_cols[0].metric("Services", metrics.get("services", 0))
                projection_cols[1].metric(
                    "Evidence records", metrics.get("evidence_records", 0)
                )
                projection_cols[2].metric(
                    "Care contacts", metrics.get("genesys_contacts", 0)
                )
                projection_cols[3].metric(
                    "Human review", metrics.get("human_review_required", 0)
                )
                projection_cols[4].metric(
                    "Promoted installs", metrics.get("install_watch_promoted", 0)
                )
                st.dataframe(
                    projection.get("services", []),
                    hide_index=True,
                    use_container_width=True,
                )
            except Exception as exc:
                st.error(str(exc))
        with detail_tabs[3]:
            try:
                batch = _request(f"/api/import-batches/{urllib.parse.quote(batch_id)}")
                timeline = (batch.get("timeline") or {}).get("events", [])
                st.dataframe(timeline, hide_index=True, use_container_width=True)
            except Exception as exc:
                st.error(str(exc))
        with detail_tabs[4]:
            st.json(analysis)
        run_id = _active_run_id()
        if st.button(
            "Materialize read-only scenario overlay",
            use_container_width=True,
            help="Creates a child scenario reference; canonical run datasets remain unchanged.",
        ):
            try:
                scenario = _request(
                    f"/api/import-batches/{urllib.parse.quote(batch_id)}/materialize",
                    "POST",
                    {"run_id": run_id or None},
                )
                st.success(
                    f"Materialized {scenario['scenario_id']} · canonical run unchanged"
                )
            except Exception as exc:
                st.error(str(exc))

def render() -> None:
    st.markdown(executive_style.css(), unsafe_allow_html=True)
    _hero()
    requested_view = _requested_view()
    _executive_crosslink(requested_view)
    run_id = _active_run_id()
    if run_id:
        _run_chip(run_id)

    sections = [
        ("executive", "Executive View", lambda: _executive_view(run_id)),
        ("create", "Create Demo", _create_demo),
        ("predictive", "Predictive Health", _predictive_health),
        ("install", "Install Assurance", _install_assurance),
        ("external", "External Evidence", _external_evidence),
        ("care", "Customer Experience", _customer_experience),
        ("caddi", "DvSum CADDI & Genesys", _caddi_layer),
        ("subscriber", "Subscriber Story", _subscriber_story),
        ("decisions", "Decisions & Controls", _decision_control),
        ("evidence", "Evidence & Audit", _evidence),
    ]
    if requested_view:
        sections.sort(key=lambda section: section[0] != requested_view)

    tabs = st.tabs([label for _, label, _ in sections])
    for tab, (_, _, render_section) in zip(tabs, sections, strict=True):
        with tab:
            render_section()


if __name__ == "__main__":
    render()
