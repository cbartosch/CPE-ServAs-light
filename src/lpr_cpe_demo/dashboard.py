"""Build the control-tower dashboard spec from the live model.

Format
------
Adopts the block structure, dark theme and accent palette of the supplied
`e2e_fixed_access_assurance_orchestration_dashboard.json`: title and badges, a
control strip, a KPI row, four charts, a hotspot table, domain observability,
closed-loop confidence and a playbook backlog.

Two deliberate departures from the supplied file
-----------------------------------------------
**Areas are Puerto Rico, not Dubai.** The template's hotspots sit in Jumeirah,
Business Bay, DIFC, Marina and Palm. Hotspots here are generated from the
footprint model, so they land in real municipios with real dispatch hubs behind
them.

**Numbers are computed where a model exists, and labelled where they are not.**
The template asserts "Truck rolls avoided: 128, +18%". Two rounds of analysis
established that figure is a range — roughly 6 to 27 per thousand incidents,
depending on the share of wasted dispatch attributable to domain
misclassification and on gate recall, neither of which is known. Every block
therefore carries a `provenance`:

``computed``   derived from the model in this repository and reproducible
``assumed``    a stated parameter, replaceable in one place
``synthetic``  invented for shape only, because no telemetry source exists

A dashboard that mixes the three without saying which is which is the fastest way
to have a number quoted back as fact in a steering committee.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .agents.status import RECORDER, describe_provider
from .benchmarks import citation
from .caddi import caddi_contract, caddi_contract_rows
from .commercial import BLAST_RADIUS_PLANT_EVENT, PROTECTION_REASON
from .effort import false_positive_cost
from .fault_generator import DOMAIN_MIX, generate_faults, summarise
from .geography import sites_in_cpe_footprint
from .plant import PLANT_ASSUMPTIONS, footprint_totals, households
from .telemetry import DATA_CONTRACT, Aggregator, IncidentRecord, contract_summary

Provenance = Literal["computed", "assumed", "synthetic"]

THEME: dict[str, Any] = {
    "background_gradient": "from-slate-950 via-slate-900 to-indigo-950",
    "card": "bg-white/8 border-white/10",
    "colors": {"cyan": "#22D3EE", "blue": "#60A5FA", "violet": "#A78BFA",
               "amber": "#FBBF24", "red": "#FB7185", "green": "#34D399"},
}

# Root-cause groups, mapped from the model's responsibility domains onto the
# template's five buckets so the chart shape matches while the values do not.
DOMAIN_TO_BUCKET: dict[str, str] = {
    "hfc_tap": "Outside plant", "pon_odp": "Outside plant", "drop": "Outside plant",
    "cpe": "CPE / WiFi", "wifi_or_home": "CPE / WiFi", "premise_wiring": "CPE / WiFi",
    "plant": "OLT / CMTS", "shared_network": "Backhaul",
    "provisioning": "Config / auth", "unknown": "Config / auth",
}
BUCKET_COLOUR = {"Outside plant": "#FB7185", "CPE / WiFi": "#FBBF24",
                 "OLT / CMTS": "#22D3EE", "Backhaul": "#A78BFA",
                 "Config / auth": "#34D399"}


@dataclass(slots=True)
class Block:
    """One dashboard panel, with its provenance attached rather than implied."""

    key: str
    title: str
    provenance: Provenance
    note: str
    data: Any

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "title": self.title,
                "provenance": self.provenance, "note": self.note, "data": self.data}


@dataclass(slots=True)
class Dashboard:
    dashboard_id: str
    title: str
    subtitle: str
    version: str
    theme: dict[str, Any]
    badges: list[dict[str, str]]
    control_panel: dict[str, Any]
    blocks: list[Block] = field(default_factory=list)

    def block(self, key: str) -> Block:
        for b in self.blocks:
            if b.key == key:
                return b
        raise KeyError(key)

    def provenance_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for b in self.blocks:
            counts[b.provenance] = counts.get(b.provenance, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {"dashboard_id": self.dashboard_id, "title": self.title,
                "subtitle": self.subtitle, "version": self.version,
                "data_status": "mixed: see provenance on each block",
                "theme": self.theme, "badges": self.badges,
                "control_panel": self.control_panel,
                "blocks": [b.to_dict() for b in self.blocks],
                "provenance_counts": self.provenance_counts()}


# --------------------------------------------------------------------- KPIs
def _kpis(faults, stats) -> Block:
    incidents = len(faults)
    remote = sum(1 for f in faults if f.truck_rolls == 0)
    dirty = sum(1 for f in faults if f.crew_type == "dirty")
    off_premise = stats["off_premise_interventions"]

    # Wasted-dispatch avoidance. Kept as a RANGE because the two governing
    # parameters are unknown: the share of no-fault-found attributable to domain
    # misclassification, and gate recall. See docs/AB_MEASUREMENT.md.
    wasted_per_1000 = 45.0
    low = wasted_per_1000 * 0.25 * 0.50          # low attribution, low recall
    high = wasted_per_1000 * 0.60 * 1.00         # high attribution, perfect recall

    return Block(
        key="kpis", title="Assurance KPIs", provenance="computed",
        note=("Derived from the generated incident set, the effort model and the "
              "published truck-roll benchmark. Truck-roll avoidance is a range, "
              "not a point: the template's single figure cannot be supported."),
        data=[
            {"label": "Incidents in scope", "value": f"{incidents}",
             "delta": None, "trend_positive": None,
             "description": "Synthetic incidents generated for this view"},
            {"label": "Resolved without dispatch", "value": f"{remote / incidents:.0%}",
             "delta": None, "trend_positive": True,
             "description": f"{remote} of {incidents} closed remotely"},
            {"label": "Dirty-boots share", "value": f"{dirty / incidents:.0%}",
             "delta": None, "trend_positive": False,
             "description": f"{off_premise} worked away from the premise"},
            {"label": "Wasted rolls avoidable",
             "value": f"{low:.0f}\u2013{high:.0f} / 1k",
             "delta": None, "trend_positive": True,
             "description": "Per thousand incidents. A range, not a point: "
                            "depends on misclassification share and gate recall, "
                            "neither of which is measured"},
            {"label": "Field cost at stake",
             "value": f"${stats['total_cost_usd']:,.0f}",
             "delta": None, "trend_positive": False,
             "description": "Effort-model cost of resolving this incident set"},
        ])


# ------------------------------------------------------------------- charts
def _root_cause_mix() -> Block:
    """Household-weighted from DOMAIN_MIX, not asserted."""
    weights: dict[str, float] = {}
    total_hh = 0.0
    for site in sites_in_cpe_footprint():
        hh = float(households(site))
        total_hh += hh
        mix = DOMAIN_MIX[site.archetype]
        pon = float(PLANT_ASSUMPTIONS["pon_share_by_archetype"][site.archetype])  # type: ignore[index]
        for key, share in mix.items():
            if key == "delimiter":
                for dom, tech_share in (("pon_odp", pon), ("hfc_tap", 1 - pon)):
                    bucket = DOMAIN_TO_BUCKET[dom]
                    weights[bucket] = weights.get(bucket, 0.0) + hh * share * tech_share
                continue
            if key == "plant":
                # fault_generator sends PON 'plant' to plant, and splits HFC
                # 'plant' evenly between plant and shared_network.
                olt = pon + (1 - pon) * 0.5
                for dom, tech_share in (("plant", olt), ("shared_network", 1 - olt)):
                    bucket = DOMAIN_TO_BUCKET[dom]
                    weights[bucket] = weights.get(bucket, 0.0) + hh * share * tech_share
                continue
            bucket = DOMAIN_TO_BUCKET.get(key, "Config / auth")
            weights[bucket] = weights.get(bucket, 0.0) + hh * share
    grand = sum(weights.values()) or 1.0
    data = sorted(({"name": name,
                    "value": round(100 * value / grand, 1),
                    "color": BUCKET_COLOUR[name]}
                   for name, value in weights.items()),
                  key=lambda d: -d["value"])
    return Block(
        key="incident_root_cause_mix", title="Expected footprint-weighted root-cause mix",
        provenance="computed",
        note=("Household-weighted across the footprint from the archetype domain "
              "mix. Outside plant leads because tap, ODP and drop faults are "
              "grouped, which is also where dispatch cost concentrates."),
        data=data)


def _automation_funnel(faults) -> Block:
    """Detect through Learn. The Diagnose stage is real; the rest are assumed."""
    gated = sum(1 for f in faults if f.crew_type == "dirty")
    autonomous_diagnose = round(100 * (1 - gated / max(len(faults), 1)))
    return Block(
        key="automation_funnel", title="Autonomy by stage", provenance="assumed",
        note=("Only Diagnose is model-derived: the human share equals the rate at "
              "which the RCA gate routes to a person. Detect, Correlate, Act, "
              "Validate and Learn are ASSUMED positions, not measurements. See "
              "telemetry.DATA_CONTRACT for what would make each one real."),
        data=[
            {"stage": "Detect", "autonomous_pct": 91, "human_pct": 9,
             "source": "assumed"},
            {"stage": "Correlate", "autonomous_pct": 82, "human_pct": 18,
             "source": "assumed"},
            {"stage": "Diagnose", "autonomous_pct": autonomous_diagnose,
             "human_pct": 100 - autonomous_diagnose, "source": "computed"},
            {"stage": "Act", "autonomous_pct": 55, "human_pct": 45,
             "source": "assumed"},
            {"stage": "Validate", "autonomous_pct": 76, "human_pct": 24,
             "source": "assumed"},
            {"stage": "Learn", "autonomous_pct": 44, "human_pct": 56,
             "source": "assumed"},
        ])


def _cost_by_archetype(faults) -> Block:
    """Replaces the template's synthetic MTTR curve with something computable."""
    buckets: dict[str, dict[str, float]] = {}
    for f in faults:
        row = buckets.setdefault(f.archetype, {"count": 0.0, "cost": 0.0,
                                               "dispatched": 0.0, "benchmark": 0.0})
        row["count"] += 1
        row["cost"] += f.total_cost_usd
        if f.truck_rolls:
            row["dispatched"] += 1
            row["benchmark"] += f.benchmark_wasted_usd
    data = []
    for archetype in ("metro", "coastal", "mountain", "remote_island"):
        row = buckets.get(archetype)
        if not row or not row["count"]:
            continue
        # Averaged over DISPATCHED incidents, not all of them. Averaging over all
        # makes the figure depend on how many remote-fixable faults the sample
        # happened to draw, which reads as zero for a small island sample.
        dispatched = row["dispatched"]
        data.append({"archetype": archetype.replace("_", " "),
                     "incidents": int(row["count"]),
                     "dispatched": int(dispatched),
                     "mean_cost": round(row["cost"] / row["count"], 2),
                     "mean_wasted_visit": (round(row["benchmark"] / dispatched, 2)
                                           if dispatched else None)})
    return Block(
        key="cost_by_archetype", title="Cost per incident by archetype",
        provenance="computed",
        note=("Mean cost to resolve is over all incidents; the wasted-visit "
              "figure is over DISPATCHED incidents only, so it does not collapse "
              "when a small sample draws mostly remote-fixable faults. Island "
              "work separates sharply because a ferry crossing and an overnight "
              "sit outside the published benchmark range."),
        data=data)


def _service_health() -> Block:
    return Block(
        key="service_health_by_layer", title="Service health by layer",
        provenance="synthetic",
        note=("SHAPE ONLY. There is no telemetry source in this deployment, so "
              "these curves are invented. Wire NXT, CMTS and OLT counters before "
              "showing this to an operations audience."),
        data=[
            {"time": t, "HFC": h, "PON": p, "Core": c, "WiFi": w}
            for t, h, p, c, w in (
                ("00:00", 97, 98, 99, 94), ("03:00", 98, 99, 99, 95),
                ("06:00", 96, 98, 99, 93), ("09:00", 91, 97, 98, 89),
                ("12:00", 94, 98, 99, 92), ("15:00", 95, 96, 99, 91),
                ("18:00", 97, 98, 99, 94), ("21:00", 98, 99, 99, 95))])


# ----------------------------------------------------------------- hotspots
SEVERITY_BY_HOUSEHOLDS = ((100, "Critical"), (24, "High"), (4, "Medium"))


def _severity(households_affected: int) -> str:
    for floor, label in SEVERITY_BY_HOUSEHOLDS:
        if households_affected >= floor:
            return label
    return "Low"


def _hotspots(faults, limit: int = 6) -> Block:
    ranked = sorted(faults, key=lambda f: (-f.households_affected, -f.total_cost_usd))
    data = []
    for f in ranked[:limit]:
        data.append({
            "id": f.intervention_id,
            "technology": f.technology,
            "area": f.municipio,
            "subscribers_impacted": f.households_affected,
            "severity": _severity(f.households_affected),
            "root_cause": f.true_domain.replace("_", " "),
            "recommended_orchestration": (
                "Remote re-provision, no dispatch" if f.truck_rolls == 0 else
                f"{f.crew_type} boots from {f.base_id.replace('BASE-', '')}"
                + (" via ferry" if f.requires_ferry else "")),
            "eta_to_restore": f"{f.total_minutes}m",
            "cost_usd": f.total_cost_usd,
            "same_day": f.same_day_feasible,
        })
    return Block(
        key="hotspots", title="Hotspots ranked by households affected",
        provenance="computed",
        note=("Generated from the footprint model, so areas are Puerto Rico "
              "municipios with a real dispatch hub behind each. Blast radius "
              "drives severity: a drop fault is one household, a tap is four to "
              "eight, a node is several hundred."),
        data=data)


# ----------------------------------------------- closed-loop confidence
def _closed_loop() -> Block:
    """Scored against controls that exist in this repository, not aspirations."""
    guardrails = [
        {"name": "Blast radius known", "score_pct": 92,
         "basis": "plant.blast_radius returns households per domain"},
        {"name": "Idempotent execution", "score_pct": 96,
         "basis": "derive_action_key plus the idempotency store; tested"},
        {"name": "Approval integrity", "score_pct": 94,
         "basis": "HMAC approval token; ten forgery attempts rejected"},
        {"name": "Inventory lineage", "score_pct": 58,
         "basis": "synthetic plant identifiers, not OSS records"},
        {"name": "Rollback safe", "score_pct": 45,
         "basis": "no rollback path is implemented"},
    ]
    overall = round(sum(g["score_pct"] for g in guardrails) / len(guardrails))
    return Block(
        key="closed_loop_confidence", title="Closed-loop confidence",
        provenance="assumed",
        note=("Scores are judgement, but each names the control it rests on. Two "
              "are deliberately low: plant identifiers are synthetic rather than "
              "OSS-derived, and no rollback path exists. The template's 86% "
              "overall is not reproducible here."),
        data={"overall_confidence_pct": overall, "guardrails": guardrails})


def _playbooks() -> Block:
    fp = false_positive_cost().cost_usd
    return Block(
        key="playbook_backlog", title="Playbook backlog",
        provenance="assumed",
        note=(f"Success rates are ASSUMED and effort saved is illustrative. The one "
              f"grounded comparison: an RCA "
              f"gate false alarm costs ${fp:,.2f}, against a wasted dispatch at "
              f"{citation().split('Headline range ')[-1]}"),
        data=[
            {"name": "HFC tap ingress quarantine", "success_pct": 84,
             "risk": "Low", "action": "Isolate ingress candidates, raise one MR"},
            {"name": "PON low optical Rx triage", "success_pct": 72,
             "risk": "Medium", "action": "Correlate ONT LOS with the splitter map"},
            {"name": "CPE firmware rollback", "success_pct": 88,
             "risk": "Low", "action": "Cohort rollback with canary guardrails"},
            {"name": "Domain-disagreement gate", "success_pct": 57,
             "risk": "Low",
             "action": "Route rules-versus-model disagreement to L2; measured "
                       "gate precision 0.571"},
        ])


def _commercial_priority_block() -> Block:
    """How the dispatch queue is ordered, and the two things that constrain it."""
    return Block(
        key="commercial_priority", title="Commercial dispatch priority",
        provenance="assumed",
        note=("Dispatches are ordered by value at risk minus the cost of the visit, "
              "where value at risk is lifetime value times the probability the "
              "customer leaves if the fault is not fixed. Contract and payment "
              "status enter through that probability rather than as free weights. "
              "Every churn and collectability figure is ASSUMED and is the first "
              "thing to replace. Two measured constraints are shown below, because "
              "both change what the ranking actually does."),
        data=[
            {"finding": "A positive-gap threshold would decline 87% of repairs",
             "detail": "A single residential account's value at risk is $20 to $150 "
                       "against a $212 to $654 visit. The gap orders a "
                       "capacity-constrained queue; it is not a test of whether a "
                       "fault deserves fixing."},
            {"finding": "Protections exceed a day's capacity",
             "detail": "23% of candidates are protected. Against 40 slots a day, "
                       "the schedule fills with protections alone and no "
                       "unprotected ticket is visited. Value still orders within "
                       "the protected band."},
            {"finding": "Cost is geography, so the ranking skews",
             "detail": "Island and mountain customers sit in the bottom quartile "
                       "structurally, not occasionally, because a ferry and an "
                       "overnight sit on the cost side of the gap."},
            {"finding": "Protections that override the ranking",
             "detail": "; ".join(sorted(PROTECTION_REASON))},
            {"finding": f"Faults above {BLAST_RADIUS_PLANT_EVENT} households",
             "detail": "Treated as a plant event. Value is multiplied by the "
                       "households affected; it is deliberately NOT also protected, "
                       "because counting it twice filled every slot."},
        ])


def _agent_status_block() -> Block:
    """Whether the agent layer is actually doing anything.

    Added because it was possible to run the whole stack with no API key, see
    every panel populated, and have no way to tell that not one model call had
    succeeded. Every other figure in this bundle carries a provenance label; this
    was the one place a reader could be misled with no way to check.
    """
    snapshot = RECORDER.snapshot()
    rows = [{"metric": "provider", "value": snapshot["provider_kind"]},
            {"metric": "model", "value": snapshot["provider_model"] or "none"},
            {"metric": "API key present", "value": "yes" if snapshot["key_present"]
                                                   else "no"},
            {"metric": "decisions attempted", "value": snapshot["attempted"]},
            {"metric": "decisions accepted", "value": snapshot["accepted"]},
            {"metric": "fell back to the rules", "value": snapshot["fell_back"]},
            {"metric": "fallback rate",
             "value": "no observation" if snapshot["fallback_rate"] is None
                      else f"{snapshot['fallback_rate']:.0%}"}]
    for entry in snapshot["fallback_reasons"][:3]:
        rows.append({"metric": f"reason ({entry['count']})",
                     "value": entry["reason"]})

    provenance: Provenance = "computed" if snapshot["provider_active"] else "assumed"
    return Block(
        key="agent_status", title="Agent status", provenance=provenance,
        note=(f"{snapshot['verdict']} Reason: {snapshot['provider_reason']}. "
              f"When no model is active every decision below is the deterministic "
              f"rules and the panels look no different, which is why this one "
              f"exists. Any agent-derived figure on this dashboard is then ASSUMED "
              f"rather than model-produced."),
        data=rows)


def _caddi_layer_block() -> Block:
    """Expose DvSum CADDI as the existing Genesys-facing correlation layer."""

    contract = caddi_contract()
    summary = contract["summary"]
    return Block(
        key="cadi_call_center_layer",
        title="DvSum CADDI / Genesys call-center context layer",
        provenance="assumed",
        note=(
            "ASSUMED stakeholder-supplied current-state contract, not a live connection. "
            "DvSum CADDI "
            "correlates and presents call-center context in Genesys; CSG, OTS, "
            "Intraway, NXT, Symphonica, Dvision/LLA, Plume and operational repair "
            "systems remain authoritative for their facts. The preferred target is to "
            "augment or federate with DvSum CADDI, avoiding a second source of truth."
        ),
        data={
            "status": contract["integration_status"],
            "live_connection": contract["live_connection"],
            "positioning": contract["positioning"],
            "source_of_truth_policy": contract["source_of_truth_policy"],
            "operations_boundary": contract["operations_boundary"],
            "summary": summary,
            "capabilities": caddi_contract_rows(),
        },
    )


def _data_contract_block() -> Block:
    """What every other panel needs, and what is still missing.

    This panel exists because the alternative is a caveat in a footnote. Naming
    the source system per missing field turns the gap into a work list.
    """
    summary = contract_summary()
    rows = []
    for panel in DATA_CONTRACT:
        rows.append({
            "panel": panel.panel,
            "refresh": panel.refresh,
            "status": panel.status,
            "in_flow": sum(1 for r in panel.requirements if r.availability == "in_flow"),
            "modelled": sum(1 for r in panel.requirements if r.availability == "modelled"),
            "missing": len(panel.blocking),
            "blocking_sources": ", ".join(sorted({r.source_system
                                                  for r in panel.blocking})) or "-",
        })
    return Block(
        key="data_contract", title="Data contract: what would make this real",
        provenance="computed",
        note=(f"{summary['fields']} fields across {summary['panels']} panels: "
              f"{summary['by_availability'].get('in_flow', 0)} available from the "
              f"workflow today, {summary['by_availability'].get('modelled', 0)} on "
              f"modelled inputs, {summary['by_availability'].get('missing', 0)} "
              f"needing a source system that is not wired. "
              f"{len(summary['missing_source_systems'])} distinct systems would "
              f"close the gap."),
        data=rows)


def build_from_flow(records: list[IncidentRecord]) -> Dashboard:
    """Build from real workflow telemetry rather than the fault generator.

    Panels the contract marks as satisfiable are computed from the records and
    labelled `computed`. Panels needing an unwired source system keep their
    honest label, so switching to live data does not silently upgrade a synthetic
    panel.
    """
    agg = Aggregator(records=list(records))
    kpis = agg.kpis()
    dash = Dashboard(
        dashboard_id="lpr_e2e_fixed_access_assurance_orchestration_live",
        title="E2E Fixed Access HFC + PON Service Assurance Orchestration",
        subtitle=("Populated from workflow telemetry. Panels still needing a "
                  "source system are labelled, not filled in."),
        version="1.0-flow", theme=THEME,
        badges=[{"label": f"{len(agg)} incidents from the flow", "type": "scope"},
                {"label": "live telemetry", "type": "observability"},
                {"label": "DvSum CADDI contract mapped; adapter not connected",
                 "type": "caveat"},
                {"label": "unwired sources labelled", "type": "caveat"}],
        control_panel={"assurance_mode": "L2 assisted, human gate on every dispatch",
                       "incidents": len(agg),
                       "primary_action": "Refresh from the read model"})

    dash.blocks = [
        Block("kpis", "Assurance KPIs", "computed",
              "Counted from closed and in-flight incidents in the workflow.",
              [{"label": "Incidents", "value": str(kpis["incidents"]),
                "delta": None, "trend_positive": None,
                "description": "Projected from workflow state"},
               {"label": "Resolved remotely",
                "value": f"{kpis['resolved_remotely_pct']}%", "delta": None,
                "trend_positive": True, "description": "Closed with no truck roll"},
               {"label": "Dispatched", "value": str(kpis["dispatched"]),
                "delta": None, "trend_positive": False,
                "description": "Incidents that rolled a truck"},
               {"label": "Escalated", "value": str(kpis["escalated"]),
                "delta": None, "trend_positive": False,
                "description": "Hit a budget ceiling or a policy block"},
               {"label": "Field cost", "value": f"${kpis['cost_usd']:,.0f}",
                "delta": None, "trend_positive": False,
                "description": "Effort model; rates still assumed"}]),
        Block("automation_funnel", "Autonomy by stage", "computed",
              ("Each stage is counted from durable state: a gate_reason means "
               "Diagnose asked a person, an approval means Act did. Detect and "
               "Learn report no observation, because nothing in the flow "
               "measures them."),
              agg.autonomy_funnel()),
        Block("incident_root_cause_mix", "Incident root-cause mix", "computed",
              ("Approved domain weighted by affected subscribers. Subscriber "
               "counts are modelled until OSS inventory is wired."),
              agg.root_cause_mix()),
        Block("closed_loop_confidence", "Closed-loop counters", "computed",
              ("Three real counters, not scores: replayed effects that produced "
               "no second action, rejected approval tokens, and the share of "
               "incidents where a delimiter was resolved before an MR."),
              agg.guardrail_counters()),
        Block("playbook_backlog", "Action outcomes", "computed",
              "Success rate per action type from action_history.",
              agg.playbook_success()),
        _commercial_priority_block(),
        _agent_status_block(),
        _caddi_layer_block(),
        _data_contract_block(),
    ]
    return dash


def build(*, count: int = 60, seed: int = 20260817) -> Dashboard:
    faults = generate_faults(count, seed=seed)
    stats = summarise(faults)
    totals = footprint_totals()

    dash = Dashboard(
        dashboard_id="lpr_e2e_fixed_access_assurance_orchestration",
        title="E2E Fixed Access HFC + PON Service Assurance Orchestration",
        subtitle=("Puerto Rico footprint. CPE telemetry, HFC and PON access "
                  "events, plant topology, dispatch hubs and the RCA gate in one "
                  "view, with every panel labelled computed, assumed or synthetic."),
        version="1.0-lpr",
        theme=THEME,
        badges=[
            {"label": describe_provider().headline,
             "type": "observability" if describe_provider().active else "caveat"},
            {"label": f"{totals['households']:,} modelled households",
             "type": "scope"},
            {"label": f"{len(sites_in_cpe_footprint())} municipios, "
                      f"{totals['taps']:,} taps, {totals['odps']:,} ODPs",
             "type": "scope"},
            {"label": "Assumed hubs and rates", "type": "caveat"},
            {"label": "DvSum CADDI contract mapped; adapter not connected",
             "type": "caveat"},
            {"label": f"seed {seed}, reproducible", "type": "observability"},
        ],
        control_panel={
            "assurance_mode": "L2 assisted, human gate on every dispatch",
            "incidents": count,
            "seed": seed,
            "primary_action": "Regenerate incident set",
        })

    dash.blocks = [
        _kpis(faults, stats),
        _root_cause_mix(),
        _automation_funnel(faults),
        _cost_by_archetype(faults),
        _hotspots(faults),
        _service_health(),
        _closed_loop(),
        _playbooks(),
        _commercial_priority_block(),
        _agent_status_block(),
        _caddi_layer_block(),
        _data_contract_block(),
    ]
    return dash
