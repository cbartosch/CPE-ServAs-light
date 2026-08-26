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
    "predictive_run",
    "care_run",
    "data_run",
    "sub_run",
    "decision_run",
)

VIEW_ALIASES = {
    "executive": "executive",
    "executive-view": "executive",
    "create": "create",
    "create-demo": "create",
    "predictive": "predictive",
    "predictive-health": "predictive",
    "care": "care",
    "customer-care": "care",
    "customer-experience": "care",
    "caddi": "caddi",
    "dvsum-caddi": "caddi",
    "cadi": "caddi",
    "genesys": "caddi",
    "cadi-genesys": "caddi",
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
    remembered = str(st.session_state.get("run_id", "")).strip()
    if not remembered:
        remembered = _latest_run_id()
        if remembered:
            _remember_run(remembered)
    return remembered


def _run_id(key: str) -> str:
    remembered = _active_run_id()
    if remembered and not str(st.session_state.get(key, "")).strip():
        st.session_state[key] = remembered
    with st.expander("Demo run selection", expanded=False):
        st.caption("The latest saved demo run is selected automatically. Change this only for technical replay.")
        return st.text_input("Run ID", key=key)


def _load_dataset(run_id: str, dataset: str, *, limit: int = 5000) -> list[dict]:
    result = _request(
        f"/api/runs/{urllib.parse.quote(run_id)}/datasets/{dataset}?limit={limit}"
    )
    return list(result.get("rows", []))


def _catalog(run_id: str) -> dict:
    return _request(f"/api/runs/{urllib.parse.quote(run_id)}")


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
          <div>
            <div class="lpr-crosslink-title">One executive story, two evidence lenses</div>
            <div class="lpr-crosslink-copy">{html.escape(context)} The active run remains unchanged while you move between views.</div>
          </div>
          <div class="lpr-crosslink-actions">
            <a class="lpr-crosslink-link legacy" target="_self" href="control-tower">← Legacy Control Tower</a>
            <a class="lpr-crosslink-link" target="_self" href="digital-twin?view=predictive">Predictive Health</a>
            <a class="lpr-crosslink-link" target="_self" href="digital-twin?view=customer-care">Customer Care</a>
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
    cols[2].metric("At risk", f"{summary.get('tickets', 0):,}")
    cols[3].metric("Risk rate", f"{100 * float(summary.get('flag_rate', 0)):.2f}%")
    cols[4].metric("Care linked", f"{summary.get('care_tickets_correlated', 0):,}")


def _executive_view(run_id: str) -> None:
    if not run_id:
        _empty(
            "Your executive story starts with one demo run",
            "Open Create Demo, choose the scale and scenarios, and generate. The latest run will then follow you automatically across every view.",
        )
        return

    _run_chip(run_id)
    try:
        catalog = _catalog(run_id)
        predictive = _load_dataset(run_id, "predictive_tickets")
        care = _load_dataset(run_id, "care_tickets")
        reviews = _load_dataset(run_id, "care_ticket_reviews")
        incidents = _load_dataset(run_id, "incidents")
    except Exception as exc:
        st.error(f"Could not load executive view: {exc}")
        return

    homes = int(catalog.get("config", {}).get("homes", 0))
    matched = sum(bool(row.get("predictive_match")) for row in care)
    avoided = sum(bool(row.get("duplicate_incident_suppressed")) for row in care)
    human = sum(bool(row.get("reconciled_human_review_required")) for row in reviews)
    closed = sum(str(row.get("status")) == "CLOSED" for row in incidents)
    forecast = sum(str(row.get("ticket_class")) == "forecast" for row in predictive)
    proactive = sum(str(row.get("ticket_class")) == "proactive" for row in predictive)

    _section("Executive scorecard", "What the closed-loop model demonstrates")
    top = st.columns(5)
    top[0].metric("Homes modeled", f"{homes:,}")
    top[1].metric("Service risks found", f"{len(predictive):,}")
    top[2].metric("Care contacts pre-correlated", f"{matched:,} / {len(care):,}")
    top[3].metric("Duplicate incidents avoided", f"{avoided:,}")
    top[4].metric("Cases closed", f"{closed:,} / {len(incidents):,}")

    if care:
        share = 100 * matched / len(care)
        st.markdown(
            f'<div class="lpr-insight"><strong>Executive takeaway.</strong> In this synthetic run, <strong>{matched:,} of {len(care):,} Customer Care contacts ({share:.0f}%)</strong> arrived with predictive modem evidence already available. The workflow attaches the call to the governed root incident rather than creating duplicate work.</div>',
            unsafe_allow_html=True,
        )

    st.markdown(
        f"""
        <div class="lpr-story-grid">
          <div class="lpr-story-card"><div class="lpr-story-no">01</div><strong>Prevent</strong><span>{forecast:,} forecast risks surface before a hard threshold breach; {proactive:,} are already degraded and prioritized for action.</span></div>
          <div class="lpr-story-card"><div class="lpr-story-no">02</div><strong>Connect</strong><span>{matched:,} customer contacts are correlated to predictive evidence and the same root incident, preserving SLA clock and context.</span></div>
          <div class="lpr-story-card"><div class="lpr-story-no">03</div><strong>Control</strong><span>{human:,} care reviews require human oversight after deterministic and agent recommendations are reconciled to operating controls.</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    left, right = st.columns([1.35, 1])
    with left:
        _section("Leading indicators", "Highest-priority predicted service risks")
        ranked = sorted(
            predictive,
            key=lambda row: (
                {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(str(row.get("severity")), 9),
                0 if row.get("ticket_class") == "proactive" else 1,
            ),
        )[:8]
        if ranked:
            st.dataframe(_predictive_table(ranked), hide_index=True, use_container_width=True)
        else:
            st.info("No predictive service risks in this run.")
    with right:
        _section("Customer impact", "Care priority and predictive context")
        p1 = sum(row.get("priority") == "P1" for row in care)
        p2 = sum(row.get("priority") == "P2" for row in care)
        p3 = sum(row.get("priority") == "P3" for row in care)
        cols = st.columns(3)
        cols[0].metric("P1", p1)
        cols[1].metric("P2", p2)
        cols[2].metric("P3", p3)
        st.caption("Priority is synthetic and scenario-driven. It is shown as a workload lens, not a production KPI.")
        if catalog.get("quality", {}).get("passed"):
            st.success(f"Governance gate passed · {catalog['quality'].get('checks', 0)} quality checks")
        else:
            st.error("Governance gate did not pass for this run.")

    with st.expander("Executive demo talk track", expanded=False):
        st.markdown(
            """
            **1. Start with prediction.** The platform scans HFC and PON modem trajectories and distinguishes *forecast risk* from *already degraded* service.  
            **2. Show the customer call.** When Care contacts arrive, the system correlates them to predictive evidence and the durable root incident instead of restarting diagnosis.  
            **3. End with governance.** Deterministic controls remain authoritative; the AI recommendation is reconciled, side effects are gated, and closure requires objective restoration evidence.
            """
        )


def _create_demo() -> None:
    _section(
        "Create a boardroom scenario",
        "Choose the scale, choose the story, then generate one governed run",
        "The controls below are intentionally business-facing. Technical AI settings are optional and collapsed.",
    )

    preset_cols = st.columns(3)
    if preset_cols[0].button("Boardroom · 500 homes", use_container_width=True):
        st.session_state["demo_homes"] = 500
    if preset_cols[1].button("Operations · 5,000 homes", use_container_width=True):
        st.session_state["demo_homes"] = 5000
    if preset_cols[2].button("Footprint · 500,000 homes", use_container_width=True):
        st.session_state["demo_homes"] = 500000
    if "demo_homes" not in st.session_state:
        st.session_state["demo_homes"] = 500

    controls = st.columns([1, 2])
    homes = controls[0].number_input(
        "Homes in the digital footprint",
        min_value=1,
        max_value=500000,
        key="demo_homes",
    )
    scenarios = controls[1].multiselect(
        "Customer and network stories",
        list(SCENARIO_LABELS),
        default=["slow_wifi", "fiber_cut", "power_outage"],
        format_func=lambda value: SCENARIO_LABELS[value],
    )

    st.markdown(
        """
        <div class="lpr-story-grid">
          <div class="lpr-story-card"><div class="lpr-story-no">A</div><strong>Predictive assurance</strong><span>Generate HFC/PON modem trajectories and surface forecast or proactive service risk.</span></div>
          <div class="lpr-story-card"><div class="lpr-story-no">B</div><strong>Customer correlation</strong><span>Connect later Care contacts to the same predictive evidence and root incident.</span></div>
          <div class="lpr-story-card"><div class="lpr-story-no">C</div><strong>Governed resolution</strong><span>Reconcile AI with deterministic controls and require evidence before closure.</span></div>
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
                "profile": "smoke",
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
            with st.spinner("Building the digital twin, predictive risks and Customer Care correlation…"):
                result = _request("/api/runs", "POST", payload)
            _remember_run(result["run_id"])
            st.success("Executive demo ready — all governed quality checks passed." if result["quality"]["passed"] else "Demo generated, but the quality gate needs attention.")
            metrics = st.columns(4)
            metrics[0].metric("Homes", f"{result['operational_scale'].get('homes', 0):,}")
            metrics[1].metric("Predictive risks", f"{result['operational_scale'].get('predictive_tickets', 0):,}")
            metrics[2].metric("Customer Care tickets", f"{result['operational_scale'].get('care_tickets', 0):,}")
            metrics[3].metric("Quality checks", f"{result['quality'].get('checks', 0)} passed")
            _run_chip(result["run_id"])
            with st.expander("Technical generation record", expanded=False):
                st.json(result)
        except Exception as exc:
            st.error(str(exc))


def _predictive_health() -> None:
    _section(
        "Prevent",
        "Predictive network health",
        "See which modems are healthy, which are trending toward failure, and which are already degraded — without starting from raw telemetry.",
    )
    run_id = _run_id("predictive_run")
    if not run_id:
        _empty("No demo run selected", "Create a demo first. Predictive health will populate automatically from the latest run.")
        return
    _run_chip(run_id)

    try:
        tickets = _load_dataset(run_id, "predictive_tickets")
        pulls = _load_dataset(run_id, "predictive_modem_pulls")
        care = _load_dataset(run_id, "care_tickets")
    except Exception as exc:
        st.error(str(exc))
        return

    matched = sum(bool(row.get("predictive_match")) for row in care)
    forecast = sum(row.get("ticket_class") == "forecast" for row in tickets)
    proactive = sum(row.get("ticket_class") == "proactive" for row in tickets)
    risk_rate = len(tickets) / len(pulls) if pulls else 0.0
    cols = st.columns(5)
    cols[0].metric("Modems observed", f"{len(pulls):,}")
    cols[1].metric("Healthy", f"{max(0, len(pulls) - len(tickets)):,}")
    cols[2].metric("Forecast risk", f"{forecast:,}")
    cols[3].metric("Already degraded", f"{proactive:,}")
    cols[4].metric("Risk rate", f"{risk_rate:.1%}")

    if matched:
        st.markdown(
            f'<div class="lpr-insight"><strong>Customer impact connection.</strong> {matched:,} Care contact(s) in this run are already linked to predictive modem evidence. Open Customer Experience to show the end-to-end story.</div>',
            unsafe_allow_html=True,
        )

    _section("Prioritized view", "Service risks worth discussing")
    if tickets:
        ranked = sorted(
            tickets,
            key=lambda row: ({"critical": 0, "high": 1, "medium": 2, "low": 3}.get(str(row.get("severity")), 9), 0 if row.get("ticket_class") == "proactive" else 1),
        )
        st.dataframe(_predictive_table(ranked[:100]), hide_index=True, use_container_width=True)
    else:
        st.success("No predictive service risks in the current run.")

    with st.expander("Run a fresh predictive scan", expanded=False):
        st.caption("Use this for a live demo of the scanner. It creates an immutable child scan and does not alter the parent run.")
        pcols = st.columns(3)
        population = pcols[0].number_input("Modems to scan", min_value=1, max_value=500000, value=500, step=100)
        days = pcols[1].slider("Trend days", 7, 60, 14)
        day_index = pcols[2].number_input("Simulation day", min_value=0, max_value=365, value=0)
        if st.button("Refresh predictive intelligence", type="primary"):
            try:
                summary = _request(
                    f"/api/runs/{urllib.parse.quote(run_id)}/predictive/scans",
                    "POST",
                    {"population": int(population), "days": int(days), "day_index": int(day_index)},
                )
                st.session_state["predictive_scan_id"] = summary["scan_id"]
                st.session_state["predictive_summary"] = summary
            except Exception as exc:
                st.error(str(exc))

        summary = st.session_state.get("predictive_summary")
        if summary and summary.get("canonical_run_id") == run_id:
            _show_predictive_summary(summary)
            scan_id = summary["scan_id"]
            try:
                detail = _request(
                    f"/api/runs/{urllib.parse.quote(run_id)}/predictive/scans/{urllib.parse.quote(scan_id)}?limit=500"
                )
                st.dataframe(_predictive_table(detail["tickets"]), hide_index=True, use_container_width=True)
                with st.expander("Raw modem pull evidence"):
                    st.dataframe(detail["pulls"], use_container_width=True)
            except Exception as exc:
                st.error(str(exc))


def _customer_experience() -> None:
    _section(
        "Connect",
        "Customer experience & Care correlation",
        "Show what the customer reported, whether the network saw it first, and how the contact attaches to one governed root incident.",
    )
    st.caption(
        "DvSum CADDI provides AI analytics and correlation for Call Center and Network "
        "Operations; Genesys is the customer-interaction channel. This demo does not "
        "connect to a live CADDI endpoint. The DvSum CADDI & Genesys tab documents the "
        "declared source and authority boundaries."
    )
    run_id = _run_id("care_run")
    if not run_id:
        _empty("No Care story yet", "Create a demo first. The Customer Care queue is generated and correlated automatically.")
        return
    _run_chip(run_id)

    filters = st.columns(3)
    status = filters[0].selectbox("Ticket status", ["ALL", "OPEN", "CLOSED"], format_func=lambda value: "All statuses" if value == "ALL" else _friendly(value))
    priority = filters[1].selectbox("Customer priority", ["ALL", "P1", "P2", "P3"], format_func=lambda value: "All priorities" if value == "ALL" else value)
    pred_filter = filters[2].selectbox("Network saw it first", ["ALL", "MATCHED", "UNMATCHED"], format_func=lambda value: {"ALL": "All tickets", "MATCHED": "Yes — predictive evidence", "UNMATCHED": "No — reactive only"}[value])

    params = {}
    if status != "ALL":
        params["status"] = status
    if priority != "ALL":
        params["priority"] = priority
    if pred_filter != "ALL":
        params["predictive_match"] = "true" if pred_filter == "MATCHED" else "false"
    suffix = f"?{urllib.parse.urlencode(params)}" if params else ""
    try:
        queue = _request(f"/api/runs/{urllib.parse.quote(run_id)}/care/tickets{suffix}")["rows"]
    except Exception as exc:
        st.error(str(exc))
        return

    matched = sum(bool(row.get("predictive_match")) for row in queue)
    open_count = sum(row.get("status") == "OPEN" for row in queue)
    p1 = sum(row.get("priority") == "P1" for row in queue)
    repeats = sum(bool(row.get("repeat_contact")) for row in queue)
    cols = st.columns(4)
    cols[0].metric("Care tickets", f"{len(queue):,}")
    cols[1].metric("Network saw it first", f"{matched:,}")
    cols[2].metric("P1 customer impact", f"{p1:,}")
    cols[3].metric("Repeat contacts", f"{repeats:,}")
    if open_count:
        st.caption(f"{open_count:,} ticket(s) remain open in this filtered view.")

    if not queue:
        st.info("No Customer Care tickets match the current filters.")
        return

    st.dataframe(_care_table(queue), hide_index=True, use_container_width=True)
    care_id = st.selectbox(
        "Choose a customer story",
        [row["care_ticket_id"] for row in queue],
        format_func=lambda value: next(
            f"{row['priority']} · {_friendly(row['category'])} · {'predictive match' if row['predictive_match'] else 'reactive only'}"
            for row in queue
            if row["care_ticket_id"] == value
        ),
    )
    try:
        detail = _request(
            f"/api/runs/{urllib.parse.quote(run_id)}/care/tickets/{urllib.parse.quote(care_id)}"
        )
    except Exception as exc:
        st.error(str(exc))
        return

    ticket = detail["ticket"]
    predictive = detail.get("predictive")
    review = detail.get("review") or {}
    case = detail.get("case") or {}

    st.markdown(
        f'<div class="lpr-insight"><strong>{html.escape(str(ticket.get("priority")))}</strong> · {html.escape(_friendly(ticket.get("category")))} — {html.escape(str(ticket.get("issue_summary", "Customer reported a service issue.")))}</div>',
        unsafe_allow_html=True,
    )
    left, middle, right = st.columns(3)
    with left:
        st.markdown("### Customer")
        st.metric("Status", _friendly(ticket.get("status")))
        st.write(f"**Channel:** {_friendly(ticket.get('channel'))}")
        st.write(f"**Opened:** {_timestamp(ticket.get('opened_at'))}")
        st.write(f"**Repeat contact:** {'Yes' if ticket.get('repeat_contact') else 'No'}")
    with middle:
        st.markdown("### Network intelligence")
        if predictive:
            signal, eta = _predictive_headline(predictive)
            st.metric("Seen before call", "Yes")
            st.write(f"**Risk:** {_friendly(predictive.get('ticket_class'))} · {_friendly(predictive.get('severity'))}")
            st.write(f"**Leading signal:** {signal}")
            st.write(f"**Threshold timing:** {eta}")
        else:
            st.metric("Seen before call", "No")
            st.caption("This is a reactive-only Care case in the synthetic run.")
    with right:
        st.markdown("### Governed decision")
        st.metric("Human review", "Required" if review.get("reconciled_human_review_required") else "Not required")
        st.write(f"**Domain:** {_friendly(review.get('deterministic_domain'))}")
        st.write(f"**Recommended action:** {_friendly(review.get('deterministic_action'))}")
        st.write(f"**Case state:** {_friendly(case.get('state'))}")

    if ticket.get("predictive_match"):
        st.success("Duplicate incident suppressed: Customer Care is attached to the existing predictive root incident and inherits its context.")

    with st.expander("Technical evidence & reconciliation", expanded=False):
        detail_tabs = st.tabs(["Care ticket", "Predictive evidence", "Decision review", "Control-plane case"])
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
        "Existing AI analytics layer",
        "DvSum CADDI · Genesys · ServAssure NXT boundary",
        (
            "Make DvSum CADDI's product scope explicit while preserving the declared LPR "
            "deployment as Call Center-facing through Genesys, and identify where the LPR "
            "assurance workflow should build on it rather than create a second truth."
        ),
    )

    cols = st.columns(4)
    cols[0].metric("Mapped capability domains", summary["capability_domains"])
    cols[1].metric("Declared in DvSum CADDI", summary["declared_existing"])
    cols[2].metric("Known data gaps", summary["known_gaps"])
    cols[3].metric("Live CADDI adapter", "Not connected")

    st.warning(
        "Contract-only status. DvSum CADDI product scope is externally verified; the LPR "
        "mapping below is stakeholder supplied. APIs, fields, source precedence, latency, "
        "retention, ownership and the contractor roadmap still require joint discovery."
    )
    st.info(contract["source_of_truth_policy"] + " " + contract["operations_boundary"])

    left, right = st.columns(2)
    with left:
        st.markdown("### DvSum CADDI provides")
        st.markdown(
            """
            - AI analytics and correlation for Call Center and Network Operations.
            - Network-aware subscriber context in the Genesys customer-service journey.
            - Analysis of ServAssure NXT and other declared LPR data sources.
            """
        )
    with right:
        st.markdown("### LPR assurance workflow owns")
        st.markdown(
            """
            - A separate Operations/VPTO execution workflow, not a claimed CADDI deployment.
            - Deterministic controls, dispatch, Clean Boots, jTrack MR and repair state.
            - Objective validation, closure and customer-safe status back to CADDI/Genesys.
            """
        )

    st.dataframe(caddi_contract_rows(), hide_index=True, use_container_width=True)
    with st.expander("DvSum CADDI architecture decision gate", expanded=False):
        st.markdown(
            f"""
            **Preferred pattern:** `{contract['preferred_pattern']}`

            **Replacement policy:** `{contract['replacement_policy']}`


            Stage 1 documents the contract only. A live adapter or replacement decision is
            out of scope until the DvSum CADDI owner, Genesys owner, source-system teams and
            the current contractor confirm the architecture and operating responsibilities.
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
        cols[0].metric("Runtime", "Python 3.14.2")
        cols[1].metric("Canonical datasets", "20")
        cols[2].metric("Production writes", "Disabled")
        cols[3].metric("Operating model", "Fail closed")
        st.success("Unified Docker stack · one Streamlit experience · predictive + Customer Care + governed action flow")
        st.markdown(
            """
            **What the demo proves**
            - Predictive modem evidence and Customer Care are correlated through the same service and root incident.
            - DvSum CADDI product scope includes Call Center and Network Operations; the declared LPR deployment remains Call Center/Genesys only and no live adapter is claimed.
            - Deterministic operating controls remain authoritative when an AI recommendation differs.
            - Dispatch requires diagnosis plus skills, parts and access readiness.
            - CPE replacement requires failed diagnostics or a documented reason.
            - Closure requires objective restoration evidence and the repair checklist.
            - Repeat cases remain linked and escalate rather than resetting the operating clock.
            """
        )


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
