"""Every public symbol must be reachable from application code.

Why this is a committed test and not a script
---------------------------------------------
The v1.12.1 audit ran exactly this check as a throwaway script and found four
orphans. It was never committed. It would have caught both of the failures that
followed:

  v1.16.0  five agent modules and 55 tests the running system never called
  v1.23.0  a dispatch rule measured at 2.2x the incumbent and wired to nothing

After the second I added a standing check and a test — but the test I wrote was
specific to agents, so it did not generalise and the third occurrence went
undetected. The lesson is not "check reachability"; it is that a guard written for
one instance of a class of bug does not guard the class.

A symbol that only tests call is indistinguishable from a symbol that does not
exist. Unit tests cannot detect it, because each test supplies its own caller.

    PYTHONPATH=src python3 -m unittest tests.test_reachability -v
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
TESTS = ROOT / "tests"

# Symbols that are legitimately library-only, each with the reason. Anything added
# here should be justified: the point of the list is to make an exemption a
# deliberate act rather than an oversight.
INTENTIONALLY_LIBRARY_ONLY: dict[str, str] = {
    # Public API surface a consumer of the package would import, with no internal
    # caller by design.
    "Provider": "a Protocol, implemented rather than called",
    "StateLike": "a Protocol used for structural typing",
    "AnthropicProvider": "constructed by provider_from_env, never named elsewhere",
    "ScriptedProvider": "for tests and offline demonstration only",
    "AgentError": "raised and caught within the agents package",
    "ProviderError": "raised and caught within the agents package",
    "CustomerDataError": "raised at the CustomerRecord boundary",
    "ApprovalMismatch": "raised by verify_approval_for",
    "ApprovalTokenError": "the base class callers catch",
    "AdapterError": "raised by the northbound adapters",
    "CapacityPlan": "returned by allocate_capacity",
    "DaySchedule": "returned by schedule_day",
    "Job": "returned by build_jobs",
    "ValueAtRisk": "returned by value_at_risk",
    "RankedDispatch": "returned by rank",
    "IncidentRecord": "returned by telemetry.project",
    "AgentRun": "recorded by StatusRecorder",
    "ProviderDescription": "returned by describe_provider",
    "Alternative": "returned inside AgentDecision",
    "AgentDecision": "returned by Agent.decide",
    "Completion": "returned by Provider.complete",
    "Attempt": "returned inside Outcome",
    "Outcome": "returned by predictive.pipeline.process",
    "MergeDecision": "returned by attach_customer_call",
    "IncidentSeed": "returned by seed_from",
    "PredictiveTicket": "returned by scanner.scan",
    "ScanResult": "returned by scanner.scan",
    "RunReport": "returned by service.run_once",
    "Finding": "returned inside PredictiveTicket",
    "ModemSeries": "returned by signals.series_for",
    "CustomerRecord": "constructed by callers of the package",
    "FieldSpec": "returned inside SystemContract",
    "SystemContract": "returned by contract_for",
    "CpeSample": "returned by parse_cpe_usp",
    "NxtSnapshot": "returned by parse_nxt_snapshot",
    "WorkOrder": "returned by parse_wfm_work_order",
    "TroubleTicket": "returned by parse_jtrack_ticket",
    "Block": "returned inside Dashboard",
    "Dashboard": "returned by dashboard.build",
    "FieldRequirement": "returned inside PanelContract",
    "PanelContract": "returned inside DATA_CONTRACT",
    "ContrastCheck": "returned by contrast_report",
    "FlagHistory": "constructed by callers of run_once",
    "StatusRecorder": "the module default RECORDER is what code uses",
    # Diagnostics and reporting helpers, called from a console or a notebook rather
    # than from the running system. Each is exercised by a test.
    "band_for_profile": "benchmark lookup for a caller doing its own costing",
    "bases_by_likelihood": "reporting helper for the hub assumption table",
    "sites_by_archetype": "reporting helper for footprint summaries",
    "failing_checks": "contrast diagnostic, run when a palette changes",
    "build_from_flow": "the flow-fed dashboard, for when telemetry is wired",
    "rca_agent": "belongs in WorkflowEngine, which needs pydantic and cannot be "
                 "exercised in this environment; listed here rather than wired "
                 "untested",
    "rca_prompt": "prompt builder, paired with rca_agent",
    "recommendation_prompt": "prompt builder, paired with recommendation_agent",
    "route_prompt": "prompt builder, paired with route_agent",
    "sla_hours_for": "predictive SLA lookup for a caller outside the scanner",
    "build_estate": "estate builder for a caller supplying its own population",
    "bar_row": "inline SVG meter, for a caller composing its own table",
}


def _public_definitions() -> dict[str, tuple[str, int]]:
    """Public top-level callables and classes, by name, with where they live."""
    found: dict[str, tuple[str, int]] = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                if node.name.startswith("_"):
                    continue
                found.setdefault(node.name, (str(path.relative_to(ROOT)),
                                             node.lineno))
    return found


def _references(name: str, roots: tuple[pathlib.Path, ...],
                exclude: str | None = None) -> int:
    """Count references, excluding the definition line only.

    An earlier version excluded the whole defining module, which made a symbol used
    by its own module look orphaned: `truck_roll_cost` is called by `rank` in the
    same file and was flagged. Intra-module use IS reachability; what matters is
    whether anything other than a test ever reaches it.
    """
    pattern = re.compile(rf"\b{re.escape(name)}\b")
    definition = re.compile(rf"(async +)?(def|class) +{re.escape(name)}\b")
    count = 0
    for root in roots:
        for path in root.rglob("*.py"):
            if exclude and exclude in str(path):
                continue
            for line in path.read_text().splitlines():
                if definition.match(line.strip()):
                    continue
                count += len(pattern.findall(line))
    return count


class TestNoOrphanedPublicSymbols(unittest.TestCase):
    def setUp(self):
        self.definitions = _public_definitions()

    def test_the_bundle_defines_a_substantial_public_surface(self):
        """A sanity check on the collector itself: if it finds nothing, the test
        below passes vacuously."""
        self.assertGreater(len(self.definitions), 100)

    def test_every_public_symbol_is_reachable_from_application_code(self):
        orphans = []
        for name, (where, line) in sorted(self.definitions.items()):
            if name in INTENTIONALLY_LIBRARY_ONLY:
                continue
            app = _references(name, (SRC, SCRIPTS))
            if app:
                continue
            tested = _references(name, (TESTS,))
            orphans.append(f"{where}:{line} {name} "
                           f"({tested} test references, 0 application references)")
        self.assertFalse(orphans,
                         "public symbols no application code calls. A symbol only "
                         "tests reach is indistinguishable from one that does not "
                         "exist:\n  " + "\n  ".join(orphans))

    def test_every_exemption_carries_a_reason(self):
        """The allowlist exists to make an exemption deliberate, not to hide one."""
        for name, reason in INTENTIONALLY_LIBRARY_ONLY.items():
            self.assertGreater(len(reason), 10, name)

    def test_the_exemption_list_has_no_stale_entries(self):
        """An exempted symbol that no longer exists means the list is drifting."""
        stale = [n for n in INTENTIONALLY_LIBRARY_ONLY if n not in self.definitions]
        self.assertFalse(stale, f"exempted but no longer defined: {stale}")

    def test_the_recommended_dispatch_rule_is_reachable(self):
        """Named explicitly because it is the third instance of this failure."""
        for name in ("schedule_day", "build_jobs", "schedule_disparate_impact",
                     "rule_description"):
            self.assertGreater(
                _references(name, (SCRIPTS,)), 0,
                f"{name} is not called from any application code, so the "
                f"recommended rule is not the rule the bundle uses")
