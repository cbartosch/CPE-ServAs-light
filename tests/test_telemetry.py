"""Tests for the dashboard data contract and the workflow projection.

The projector reads a duck-typed state, so it is fully testable with a stub even
though the real `IncidentState` needs pydantic. That is deliberate: the engine is
one of the modules this environment cannot execute, and the projection is the part
that must not silently drift.

    PYTHONPATH=src python3 -m unittest tests.test_telemetry -v
"""
from __future__ import annotations

import ast
import pathlib
import sys
import unittest
from dataclasses import dataclass, field
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpr_cpe_demo.dashboard import build, build_from_flow  # noqa: E402
from lpr_cpe_demo.telemetry import (DATA_CONTRACT, FUNNEL_STAGES,  # noqa: E402
                                    Aggregator, contract_summary, project)


@dataclass
class StubState:
    """Only the attributes `project` reads."""

    incident_id: str = "INC-1"
    stage: str = "closed"
    technology: str = "HFC"
    parent_incident_id: str | None = None
    gate_reason: str | None = None
    approved_rca: Any = None
    approval_result: Any = None
    pending_approval_id: str | None = None
    action_history: list = field(default_factory=list)
    verification_passed: bool | None = True
    remote_attempts: int = 0
    field_visits: int = 0
    mr_attempts: int = 0
    diagnostic_cycles: int = 1
    delimiter: Any = None
    selected_action: Any = None
    rca_domain_deterministic: str | None = "drop"


@dataclass
class StubRCA:
    recommended_domain: str = "hfc_tap"


@dataclass
class StubDelimiter:
    kind: str = "tap"
    identifier: str = "TAP-ARE-0530"


@dataclass
class StubAction:
    action_type: str = "clean_boots"


class TestDataContract(unittest.TestCase):
    def test_every_panel_declares_a_refresh_and_requirements(self):
        for panel in DATA_CONTRACT:
            self.assertTrue(panel.refresh, panel.panel)
            self.assertTrue(panel.requirements, panel.panel)

    def test_every_requirement_names_a_source_system(self):
        for panel in DATA_CONTRACT:
            for req in panel.requirements:
                self.assertTrue(req.source_system, f"{panel.panel}.{req.field}")
                self.assertIn(req.availability,
                              {"in_flow", "modelled", "missing"}, req.field)

    def test_every_missing_field_names_what_would_satisfy_it(self):
        """A gap without a named source is a caveat, not a work item."""
        for panel in DATA_CONTRACT:
            for req in panel.blocking:
                self.assertTrue(req.source_system, req.field)

    def test_service_health_is_entirely_blocked(self):
        panel = next(p for p in DATA_CONTRACT
                     if p.panel == "service_health_by_layer")
        self.assertEqual(len(panel.blocking), len(panel.requirements))
        self.assertIn("blocked", panel.status)

    def test_the_funnel_stages_the_flow_can_measure_are_marked_in_flow(self):
        panel = next(p for p in DATA_CONTRACT if p.panel == "automation_funnel")
        in_flow = {r.field for r in panel.requirements if r.satisfied}
        self.assertIn("Correlate autonomy", in_flow)
        self.assertIn("Diagnose autonomy", in_flow)
        self.assertIn("Act autonomy", in_flow)
        self.assertIn("Validate autonomy", in_flow)

    def test_detect_and_learn_are_honestly_marked_missing(self):
        panel = next(p for p in DATA_CONTRACT if p.panel == "automation_funnel")
        missing = {r.field for r in panel.blocking}
        self.assertIn("Detect autonomy", missing)
        self.assertIn("Learn autonomy", missing)

    def test_summary_counts_add_up(self):
        summary = contract_summary()
        total = sum(summary["by_availability"].values())
        self.assertEqual(total, summary["fields"])
        self.assertEqual(summary["panels"], len(DATA_CONTRACT))

    def test_no_panel_claims_to_be_fully_satisfied_yet(self):
        """If this ever passes with a non-zero count, the note must be rewritten."""
        self.assertEqual(contract_summary()["panels_fully_in_flow"], 0)


class TestProjection(unittest.TestCase):
    def test_a_remote_close_is_recorded_as_no_truck_roll(self):
        rec = project(StubState(approved_rca=StubRCA("provisioning")))
        self.assertEqual(rec.truck_rolls, 0)
        self.assertTrue(rec.resolved_remotely)
        self.assertFalse(rec.dispatched)

    def test_truck_rolls_count_field_visits_and_mr_attempts(self):
        rec = project(StubState(field_visits=1, mr_attempts=1))
        self.assertEqual(rec.truck_rolls, 2)
        self.assertTrue(rec.dispatched)

    def test_enum_like_values_are_unwrapped(self):
        class Enumish:
            value = "PON"
        rec = project(StubState(technology=Enumish()))
        self.assertEqual(rec.technology, "PON")

    def test_delimiter_is_projected_when_present(self):
        rec = project(StubState(delimiter=StubDelimiter()))
        self.assertEqual(rec.delimiter_type, "tap")
        self.assertEqual(rec.delimiter_id, "TAP-ARE-0530")

    def test_missing_delimiter_does_not_raise(self):
        self.assertIsNone(project(StubState()).delimiter_id)

    def test_approved_domain_prefers_the_approved_rca(self):
        rec = project(StubState(approved_rca=StubRCA("pon_odp")))
        self.assertEqual(rec.approved_domain, "pon_odp")

    def test_approved_domain_falls_back_to_the_deterministic_result(self):
        rec = project(StubState(approved_rca=None,
                                rca_domain_deterministic="drop"))
        self.assertEqual(rec.approved_domain, "drop")

    def test_a_gate_reason_marks_diagnose_as_human(self):
        rec = project(StubState(gate_reason="domain_disagreement"))
        self.assertIn("Diagnose", rec.human_gates)
        self.assertNotIn("Diagnose", rec.autonomous_stages)

    def test_no_gate_reason_with_an_approved_rca_marks_diagnose_autonomous(self):
        rec = project(StubState(gate_reason="none", approved_rca=StubRCA()))
        self.assertIn("Diagnose", rec.autonomous_stages)

    def test_an_approval_marks_act_as_human(self):
        rec = project(StubState(approval_result={"response": "approve"}))
        self.assertIn("Act", rec.human_gates)

    def test_an_action_without_an_approval_marks_act_autonomous(self):
        rec = project(StubState(action_history=[{"action": "remote"}]))
        self.assertIn("Act", rec.autonomous_stages)

    def test_parent_attachment_marks_correlate_autonomous(self):
        rec = project(StubState(parent_incident_id="INC-PARENT"))
        self.assertIn("Correlate", rec.autonomous_stages)

    def test_detect_and_learn_are_never_guessed(self):
        """They appear in neither tuple, rather than being invented."""
        rec = project(StubState(gate_reason="none", approved_rca=StubRCA(),
                                parent_incident_id="P",
                                action_history=[{"a": 1}]))
        for stage in ("Detect", "Learn"):
            self.assertNotIn(stage, rec.human_gates, stage)
            self.assertNotIn(stage, rec.autonomous_stages, stage)

    def test_failed_verification_marks_validate_as_human(self):
        rec = project(StubState(verification_passed=False))
        self.assertIn("Validate", rec.human_gates)

    def test_escalated_and_closed_are_mutually_exclusive(self):
        closed = project(StubState(stage="closed"))
        escalated = project(StubState(stage="escalated"))
        self.assertTrue(closed.closed)
        self.assertFalse(closed.escalated)
        self.assertTrue(escalated.escalated)
        self.assertFalse(escalated.closed)

    def test_passed_in_context_is_carried_through(self):
        rec = project(StubState(), site_id="PR-ARE", archetype="coastal",
                      municipio="Arecibo", subscribers_affected=6,
                      cost_usd=1048.5, travel_minutes=84, crew_type="dirty",
                      dispatch_base="BASE-AGU")
        self.assertEqual(rec.site_id, "PR-ARE")
        self.assertEqual(rec.subscribers_affected, 6)
        self.assertEqual(rec.cost_usd, 1048.5)
        self.assertEqual(rec.dispatch_base, "BASE-AGU")


class TestAggregator(unittest.TestCase):
    def _rec(self, **kw):
        return project(StubState(**{k: v for k, v in kw.items()
                                    if k in StubState.__annotations__}),
                       **{k: v for k, v in kw.items()
                          if k not in StubState.__annotations__})

    def test_re_adding_an_incident_replaces_rather_than_duplicates(self):
        """Replay safety: the engine emits on every stage transition."""
        agg = Aggregator()
        agg.add(self._rec(incident_id="INC-1", stage="verify"))
        agg.add(self._rec(incident_id="INC-1", stage="closed"))
        self.assertEqual(len(agg), 1)
        self.assertEqual(agg.records[0].stage, "closed")

    def test_kpis_count_remote_and_dispatched_separately(self):
        agg = Aggregator()
        agg.add(self._rec(incident_id="A", approved_rca=StubRCA("cpe")))
        agg.add(self._rec(incident_id="B", field_visits=1, crew_type="dirty"))
        kpis = agg.kpis()
        self.assertEqual(kpis["incidents"], 2)
        self.assertEqual(kpis["dispatched"], 1)
        self.assertEqual(kpis["resolved_remotely_pct"], 50.0)

    def test_funnel_reports_no_observation_rather_than_zero(self):
        """Zero percent autonomous would be a claim. None is the truth."""
        agg = Aggregator()
        agg.add(self._rec(incident_id="A"))
        rows = {r["stage"]: r for r in agg.autonomy_funnel()}
        self.assertIsNone(rows["Detect"]["autonomous_pct"])
        self.assertEqual(rows["Detect"]["observations"], 0)
        self.assertIn("no observation", rows["Detect"]["source"])

    def test_funnel_computes_stages_it_can_observe(self):
        agg = Aggregator()
        agg.add(self._rec(incident_id="A", gate_reason="low_confidence"))
        agg.add(self._rec(incident_id="B", gate_reason="none",
                          approved_rca=StubRCA()))
        rows = {r["stage"]: r for r in agg.autonomy_funnel()}
        self.assertEqual(rows["Diagnose"]["observations"], 2)
        self.assertEqual(rows["Diagnose"]["autonomous_pct"], 50)

    def test_funnel_covers_every_declared_stage(self):
        rows = {r["stage"] for r in Aggregator().autonomy_funnel()}
        self.assertEqual(rows, set(FUNNEL_STAGES))

    def test_root_cause_mix_weights_by_subscribers(self):
        agg = Aggregator()
        agg.add(self._rec(incident_id="A", approved_rca=StubRCA("hfc_tap"),
                          subscribers_affected=8))
        agg.add(self._rec(incident_id="B", approved_rca=StubRCA("drop"),
                          subscribers_affected=1))
        mix = {m["domain"]: m["value"] for m in agg.root_cause_mix()}
        self.assertGreater(mix["hfc_tap"], mix["drop"])
        self.assertAlmostEqual(sum(mix.values()), 100.0, delta=0.2)

    def test_guardrail_counters_are_counts_not_scores(self):
        agg = Aggregator()
        agg.add(self._rec(incident_id="A", delimiter=StubDelimiter(),
                          replayed_effects=2, rejected_approvals=1))
        counters = agg.guardrail_counters()
        self.assertEqual(counters["replayed_effects"], 2)
        self.assertEqual(counters["rejected_approvals"], 1)
        self.assertEqual(counters["delimiter_resolved_pct"], 100.0)

    def test_playbook_success_is_per_action_type(self):
        agg = Aggregator()
        agg.add(self._rec(incident_id="A", selected_action=StubAction("remote"),
                          verification_passed=True))
        agg.add(self._rec(incident_id="B", selected_action=StubAction("remote"),
                          verification_passed=False))
        rows = {r["action_type"]: r for r in agg.playbook_success()}
        self.assertEqual(rows["remote"]["attempts"], 2)
        self.assertEqual(rows["remote"]["success_pct"], 50)

    def test_empty_aggregator_is_safe(self):
        agg = Aggregator()
        self.assertEqual(agg.kpis()["incidents"], 0)
        self.assertEqual(agg.root_cause_mix(), [])
        self.assertEqual(agg.playbook_success(), [])


class TestFlowFedDashboard(unittest.TestCase):
    def setUp(self):
        self.records = [
            project(StubState(incident_id="INC-1", gate_reason="none",
                              approved_rca=StubRCA("provisioning"),
                              selected_action=StubAction("remote")),
                    site_id="PR-BAY", archetype="metro", municipio="Bayamon",
                    cost_usd=52.5),
            project(StubState(incident_id="INC-2",
                              gate_reason="domain_disagreement",
                              approved_rca=StubRCA("hfc_tap"), field_visits=1,
                              delimiter=StubDelimiter(),
                              selected_action=StubAction("dirty_boots_mr"),
                              approval_result={"response": "approve"}),
                    site_id="PR-ARE", archetype="coastal", municipio="Arecibo",
                    subscribers_affected=6, cost_usd=1048.0, crew_type="dirty"),
        ]

    def test_flow_build_uses_the_records(self):
        dash = build_from_flow(self.records)
        kpi = next(k for k in dash.block("kpis").data
                   if k["label"] == "Incidents")
        self.assertEqual(kpi["value"], "2")

    def test_flow_build_includes_the_data_contract_panel(self):
        self.assertIn("data_contract",
                      [b.key for b in build_from_flow(self.records).blocks])

    def test_flow_build_does_not_invent_a_service_health_panel(self):
        """Switching to live data must not fabricate an unwired panel."""
        keys = [b.key for b in build_from_flow(self.records).blocks]
        self.assertNotIn("service_health_by_layer", keys)

    def test_flow_funnel_marks_unobserved_stages(self):
        rows = {r["stage"]: r for r in
                build_from_flow(self.records).block("automation_funnel").data}
        self.assertIsNone(rows["Learn"]["autonomous_pct"])
        self.assertIsNotNone(rows["Diagnose"]["autonomous_pct"])

    def test_synthetic_build_also_carries_the_contract_panel(self):
        self.assertIn("data_contract", [b.key for b in build(count=20).blocks])


class TestEngineInstrumentation(unittest.TestCase):
    """The engine needs pydantic, so verify the hook statically."""

    SRC = ROOT / "src/lpr_cpe_demo/workflow/engine.py"

    def setUp(self):
        self.tree = ast.parse(self.SRC.read_text(encoding="utf-8"))
        self.text = self.SRC.read_text(encoding="utf-8")

    def test_the_sink_is_optional(self):
        self.assertIn("telemetry_sink", self.text)
        self.assertIn("| None = None", self.text)

    def test_the_hook_sits_in_run_one_so_every_transition_is_captured(self):
        fn = next(n for n in ast.walk(self.tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "run_one")
        body = ast.get_source_segment(self.text, fn) or ""
        self.assertIn("_emit_telemetry", body)

    def test_a_sink_failure_cannot_fail_an_incident(self):
        fn = next(n for n in ast.walk(self.tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "_emit_telemetry")
        body = ast.get_source_segment(self.text, fn) or ""
        self.assertIn("try:", body)
        self.assertIn("telemetry_failures += 1", body)
        self.assertNotIn("raise", body)

    def test_failures_are_counted_so_the_gap_is_visible(self):
        self.assertIn("self.telemetry_failures = 0", self.text)
