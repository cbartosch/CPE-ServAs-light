"""What the control tower needs, where it comes from, and what is still missing.

Why this module exists
----------------------
The control tower was populated by `fault_generator`, which invents incidents.
That is fine for a mockup and useless as an operational view. This module defines
the contract between the workflow and the dashboard:

* `IncidentRecord` is the flat row every panel is computed from.
* `project` turns a workflow `IncidentState` into that row. It accepts any object
  carrying the right attributes, so the projector is fully testable with a stub
  even though the engine itself needs pydantic.
* `Aggregator` rolls records into the panel shapes.
* `DATA_CONTRACT` states, field by field, which source system supplies it and
  whether the flow can supply it today.

The contract is the point. Four panels were previously labelled computed and four
were not; the honest reason was never written down. Now each missing field names
the system that would satisfy it, so the gap is a work list rather than a caveat.

Instrumentation
---------------
`project` is called by the engine at every stage transition and at terminal
stages, via the existing `append_event` hook, whose event identity already
depends only on durable state. Projection is therefore replay-safe for the same
reason the timeline is: re-running a node reproduces the same record rather than
appending a second one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Protocol

from .cadi import CADI_CAPABILITIES

Availability = Literal["in_flow", "modelled", "missing"]

# Stages, in the order the engine walks them, mapped onto the funnel the dashboard
# shows. Several engine stages collapse into one funnel stage.
FUNNEL_STAGES: dict[str, tuple[str, ...]] = {
    "Detect": ("new", "validate"),
    "Correlate": ("correlate",),
    "Diagnose": ("evidence", "deterministic_rca", "llm_rca", "fusion"),
    "Act": ("action_ranking", "policy", "waiting_approval", "execute"),
    "Validate": ("verify", "failure_review"),
    "Learn": ("reconcile", "closed"),
}


@dataclass(frozen=True, slots=True)
class FieldRequirement:
    field: str
    source_system: str
    grain: str
    availability: Availability
    note: str = ""

    @property
    def satisfied(self) -> bool:
        return self.availability == "in_flow"


@dataclass(frozen=True, slots=True)
class PanelContract:
    panel: str
    refresh: str
    requirements: tuple[FieldRequirement, ...]

    @property
    def satisfied(self) -> bool:
        return all(r.satisfied for r in self.requirements)

    @property
    def blocking(self) -> tuple[FieldRequirement, ...]:
        return tuple(r for r in self.requirements if r.availability == "missing")

    @property
    def status(self) -> str:
        if self.satisfied:
            return "computable from the flow"
        if self.blocking:
            return "blocked: needs a source system"
        return "computable, but on modelled inputs"


def _req(f: str, src: str, grain: str, avail: Availability, note: str = "") -> FieldRequirement:
    return FieldRequirement(f, src, grain, avail, note)


DATA_CONTRACT: tuple[PanelContract, ...] = (
    PanelContract("kpis", "per incident close", (
        _req("incident_id, lane, crew_type", "workflow state", "incident", "in_flow"),
        _req("truck_rolls, remote_attempts, field_visits", "workflow state",
             "incident", "in_flow"),
        _req("resolution_cost_usd", "effort model", "incident", "modelled",
             "rates are assumed; replace effort.RATES with LPR figures"),
        _req("no_fault_found_rate",
             "WFM TMF697 characteristic noFaultFound on completion", "monthly",
             "missing",
             "the denominator for truck-roll avoidance. Without it the KPI stays "
             "a range"),
        _req("misclassification_share", "OSS reclassification history", "monthly",
             "missing",
             "share of no-fault-found dispatch reclassified to another domain on "
             "the follow-up visit"),
    )),
    PanelContract("incident_root_cause_mix", "hourly", (
        _req("approved_rca.recommended_domain", "workflow state", "incident",
             "in_flow"),
        _req("subscribers_affected",
             "NXT topology.householdsBehindDelimiter",
             "plant element", "modelled",
             "MODELLED envelope: the NXT field name is a placeholder. Currently "
             "from plant.blast_radius on assumed serving ratios"),
    )),
    PanelContract("automation_funnel", "hourly", (
        _req("Detect autonomy", "alarm ingest: auto-raised vs operator-raised",
             "incident", "missing",
             "scenarios are fixtures, so nothing is actually detected"),
        _req("Correlate autonomy", "workflow state parent_incident_id",
             "incident", "in_flow",
             "an incident attached to a parent was correlated autonomously"),
        _req("Diagnose autonomy", "workflow gate_reason and rca_review approval",
             "incident", "in_flow"),
        _req("Act autonomy", "workflow approval_result on the action gate",
             "incident", "in_flow"),
        _req("Validate autonomy", "workflow verification_passed without a gate",
             "incident", "in_flow"),
        _req("Learn autonomy", "feedback loop into the KB and the classifier",
             "incident", "missing", "no learning loop is implemented"),
    )),
    PanelContract("cost_by_archetype", "per incident close", (
        _req("site_id, archetype", "workflow topology plus geography", "incident",
             "in_flow"),
        _req("dispatch base, travel minutes", "geography model", "incident",
             "modelled", "hub locations are a practitioner assessment"),
        _req("benchmark cost per dispatch", "AEX published bands", "archetype",
             "in_flow", "externally sourced and cited"),
    )),
    PanelContract("hotspots", "5 minutes", (
        _req("delimiter type and id", "workflow state delimiter", "incident",
             "in_flow"),
        _req("subscribers_impacted", "OSS inventory", "plant element", "modelled"),
        _req("eta_to_restore", "effort model plus travel", "incident", "modelled"),
        _req("recommended_orchestration", "workflow selected_action", "incident",
             "in_flow"),
    )),
    PanelContract("service_health_by_layer", "1 minute", (
        _req("HFC MER, codeword errors, upstream SNR",
             "CPE via TR-369 USP: docsIf3SignalQualityExtRxMER, "
             "docsIfSigQUncorrectables", "modem, hourly", "missing",
             "contract in northbound.contracts.CPE_CONTRACT; values arrive in "
             "tenths and counters are cumulative"),
        _req("PON optical Rx, LOS, BER",
             "CPE via TR-369 USP: Device.Optical.Interface.1.*",
             "ONT, hourly", "missing",
             "values arrive in hundredths of a dBm"),
        _req("core and aggregation health", "IP core telemetry", "device, 1 min",
             "missing"),
        _req("WiFi airtime, client counts", "TR-369 or CPE telemetry",
             "CPE, 5 min", "missing"),
    )),
    PanelContract("closed_loop_confidence", "hourly", (
        _req("replayed effects", "effect store", "effect", "in_flow",
             "a replay that produced no second effect is idempotency working"),
        _req("rejected approval tokens", "MCP server rejections", "attempt",
             "in_flow"),
        _req("delimiter resolved before MR", "workflow state", "incident",
             "in_flow"),
        _req("rollback coverage", "not implemented", "action type", "missing"),
        _req("inventory lineage", "OSS reconciliation against plant records",
             "plant element", "missing"),
    )),
    PanelContract("commercial_priority", "per dispatch decision", (
        _req("monthly recurring revenue, contract end, arrears age",
             "CRM via TMF629/TMF666", "account", "missing",
             "the exposure the whole ranking rests on"),
        _req("churn score", "retention model, if one exists", "account", "missing",
             "replaces the churn calculation in commercial.py outright"),
        _req("medical, vulnerability and Lifeline flags", "CRM account flags",
             "account", "missing",
             "these are PROTECTIONS. Absent, the safeguard silently disappears and "
             "the ranking becomes purely commercial"),
        _req("truck roll cost for this customer", "geography and effort model",
             "incident", "modelled"),
        _req("households behind the element", "plant model", "plant element",
             "modelled"),
    )),
    PanelContract("cadi_call_center_context", "per Genesys interaction", tuple(
        _req(
            capability.label,
            "CADI / Genesys backed by " + ", ".join(capability.authoritative_sources),
            capability.grain,
            "missing",
            (
                "CADI capability supplied by LPR stakeholders; no live CADI adapter is "
                "connected. " + capability.authority_note
            ),
        )
        for capability in CADI_CAPABILITIES
    )),
    PanelContract("playbook_backlog", "daily", (
        _req("action_type outcomes over time",
             "workflow action_history, plus WFM resolutionCode",
             "action", "in_flow",
             "success rate is computable once enough incidents have closed"),
        _req("ops effort saved", "time-and-motion baseline", "action type",
             "missing"),
    )),
)


def contract_summary() -> dict[str, Any]:
    total = sum(len(p.requirements) for p in DATA_CONTRACT)
    by_state: dict[str, int] = {}
    for panel in DATA_CONTRACT:
        for req in panel.requirements:
            by_state[req.availability] = by_state.get(req.availability, 0) + 1
    return {
        "panels": len(DATA_CONTRACT),
        "panels_fully_in_flow": sum(1 for p in DATA_CONTRACT if p.satisfied),
        "panels_blocked": sum(1 for p in DATA_CONTRACT if p.blocking),
        "fields": total,
        "by_availability": by_state,
        "missing_source_systems": sorted({
            r.source_system for p in DATA_CONTRACT for r in p.requirements
            if r.availability == "missing"}),
    }


# --------------------------------------------------------------- the flat row
@dataclass(frozen=True, slots=True)
class IncidentRecord:
    """One row per incident. Every panel is computed from a collection of these."""

    incident_id: str
    stage: str
    technology: str
    site_id: str
    archetype: str
    municipio: str

    approved_domain: str | None
    domain_agreement: str | None
    gate_reason: str | None

    delimiter_type: str | None
    delimiter_id: str | None
    subscribers_affected: int

    lane: str | None
    crew_type: str | None
    dispatch_base: str | None
    travel_minutes: int

    remote_attempts: int
    field_visits: int
    diagnostic_cycles: int
    truck_rolls: int

    human_gates: tuple[str, ...]          # funnel stages where a person was asked
    autonomous_stages: tuple[str, ...]    # funnel stages completed without one

    verification_passed: bool | None
    closed: bool
    escalated: bool

    total_minutes: int
    cost_usd: float
    benchmark_wasted_usd: float

    replayed_effects: int = 0
    rejected_approvals: int = 0

    @property
    def dispatched(self) -> bool:
        return self.truck_rolls > 0

    @property
    def resolved_remotely(self) -> bool:
        return self.closed and self.truck_rolls == 0


class StateLike(Protocol):
    """The attributes `project` reads. A stub satisfying these is enough to test."""

    incident_id: str
    stage: Any
    technology: Any


def _val(obj: Any, name: str, default: Any = None) -> Any:
    """Read an attribute, unwrapping enum-like values to their `.value`."""
    got = getattr(obj, name, default)
    if got is None:
        return default
    return getattr(got, "value", got)


def _gates_from_state(state: Any) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Which funnel stages involved a human, inferred from durable state.

    Diagnose is gated when a gate_reason was recorded. Act is gated when an
    approval was requested. Validate is autonomous when verification passed with
    no failure review. Detect and Learn are not inferable, so they appear in
    neither tuple rather than being guessed.
    """
    gated: list[str] = []
    autonomous: list[str] = []

    if _val(state, "parent_incident_id"):
        autonomous.append("Correlate")

    gate_reason = _val(state, "gate_reason")
    if gate_reason and gate_reason != "none":
        gated.append("Diagnose")
    elif _val(state, "approved_rca") is not None:
        autonomous.append("Diagnose")

    approvals = _val(state, "approval_result") or _val(state, "pending_approval_id")
    history = _val(state, "action_history") or []
    if approvals:
        gated.append("Act")
    elif history:
        autonomous.append("Act")

    if _val(state, "verification_passed") is True:
        autonomous.append("Validate")
    elif _val(state, "verification_passed") is False:
        gated.append("Validate")

    return tuple(gated), tuple(autonomous)


def project(state: Any, *, site_id: str = "", archetype: str = "",
            municipio: str = "", subscribers_affected: int = 1,
            travel_minutes: int = 0, total_minutes: int = 0,
            cost_usd: float = 0.0, benchmark_wasted_usd: float = 0.0,
            dispatch_base: str | None = None, crew_type: str | None = None,
            replayed_effects: int = 0,
            rejected_approvals: int = 0) -> IncidentRecord:
    """Project a workflow state into the dashboard's row.

    The geography, plant and cost arguments are passed in rather than looked up,
    because the workflow state does not carry them and the projector must stay
    free of those imports to remain cheap and testable.
    """
    stage = str(_val(state, "stage", "unknown"))
    gated, autonomous = _gates_from_state(state)
    history = _val(state, "action_history") or []
    field_visits = int(_val(state, "field_visits", 0) or 0)
    mr_attempts = int(_val(state, "mr_attempts", 0) or 0)

    return IncidentRecord(
        incident_id=str(_val(state, "incident_id", "")),
        stage=stage,
        technology=str(_val(state, "technology", "")),
        site_id=site_id, archetype=archetype, municipio=municipio,
        approved_domain=(_val(_val(state, "approved_rca") or object(),
                              "recommended_domain")
                         or _val(state, "rca_domain_deterministic")),
        domain_agreement=_val(state, "domain_agreement"),
        gate_reason=_val(state, "gate_reason"),
        delimiter_type=_val(_val(state, "delimiter") or object(), "kind"),
        delimiter_id=_val(_val(state, "delimiter") or object(), "identifier"),
        subscribers_affected=int(subscribers_affected),
        lane=_val(_val(state, "selected_action") or object(), "action_type"),
        crew_type=crew_type,
        dispatch_base=dispatch_base,
        travel_minutes=int(travel_minutes),
        remote_attempts=int(_val(state, "remote_attempts", 0) or 0),
        field_visits=field_visits,
        diagnostic_cycles=int(_val(state, "diagnostic_cycles", 0) or 0),
        truck_rolls=field_visits + mr_attempts,
        human_gates=gated, autonomous_stages=autonomous,
        verification_passed=_val(state, "verification_passed"),
        closed=stage == "closed",
        escalated=stage == "escalated",
        total_minutes=int(total_minutes),
        cost_usd=float(cost_usd),
        benchmark_wasted_usd=float(benchmark_wasted_usd),
        replayed_effects=int(replayed_effects),
        rejected_approvals=int(rejected_approvals),
    )


# ---------------------------------------------------------------- aggregation
@dataclass(slots=True)
class Aggregator:
    records: list[IncidentRecord] = field(default_factory=list)

    def add(self, record: IncidentRecord) -> None:
        """Replay-safe: a record for an incident already present replaces it."""
        for index, existing in enumerate(self.records):
            if existing.incident_id == record.incident_id:
                self.records[index] = record
                return
        self.records.append(record)

    def extend(self, records: Iterable[IncidentRecord]) -> None:
        for record in records:
            self.add(record)

    def __len__(self) -> int:
        return len(self.records)

    # ------------------------------------------------------------- panels
    def kpis(self) -> dict[str, Any]:
        n = len(self.records) or 1
        remote = sum(1 for r in self.records if r.resolved_remotely)
        dispatched = sum(1 for r in self.records if r.dispatched)
        return {
            "incidents": len(self.records),
            "resolved_remotely_pct": round(100 * remote / n, 1),
            "dispatched": dispatched,
            "dirty_share_pct": round(
                100 * sum(1 for r in self.records if r.crew_type == "dirty") / n, 1),
            "cost_usd": round(sum(r.cost_usd for r in self.records), 2),
            "escalated": sum(1 for r in self.records if r.escalated),
        }

    def autonomy_funnel(self) -> list[dict[str, Any]]:
        """Only stages with evidence are reported. The rest say so."""
        rows = []
        for stage in FUNNEL_STAGES:
            gated = sum(1 for r in self.records if stage in r.human_gates)
            auto = sum(1 for r in self.records if stage in r.autonomous_stages)
            observed = gated + auto
            if not observed:
                rows.append({"stage": stage, "autonomous_pct": None,
                             "human_pct": None, "observations": 0,
                             "source": "no observation in the flow"})
                continue
            rows.append({"stage": stage,
                         "autonomous_pct": round(100 * auto / observed),
                         "human_pct": round(100 * gated / observed),
                         "observations": observed, "source": "computed"})
        return rows

    def root_cause_mix(self) -> list[dict[str, Any]]:
        weights: dict[str, float] = {}
        for r in self.records:
            if not r.approved_domain:
                continue
            weights[r.approved_domain] = (weights.get(r.approved_domain, 0.0)
                                          + max(r.subscribers_affected, 1))
        total = sum(weights.values()) or 1.0
        return sorted(({"domain": d, "value": round(100 * w / total, 1),
                        "subscribers": int(w)} for d, w in weights.items()),
                      key=lambda x: -x["value"])

    def guardrail_counters(self) -> dict[str, Any]:
        with_delimiter = sum(1 for r in self.records if r.delimiter_id)
        return {
            "replayed_effects": sum(r.replayed_effects for r in self.records),
            "rejected_approvals": sum(r.rejected_approvals for r in self.records),
            "delimiter_resolved_pct": round(
                100 * with_delimiter / (len(self.records) or 1), 1),
        }

    def playbook_success(self) -> list[dict[str, Any]]:
        by_lane: dict[str, dict[str, int]] = {}
        for r in self.records:
            if not r.lane:
                continue
            row = by_lane.setdefault(r.lane, {"attempts": 0, "succeeded": 0})
            row["attempts"] += 1
            if r.verification_passed:
                row["succeeded"] += 1
        return sorted(({"action_type": lane,
                        "attempts": v["attempts"],
                        "success_pct": (round(100 * v["succeeded"] / v["attempts"])
                                        if v["attempts"] else None)}
                       for lane, v in by_lane.items()),
                      key=lambda x: -x["attempts"])
