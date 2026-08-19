"""Regression tests for the red-team findings.

Each test names the attack it defends against. Every one of these passed as an
attack before the fix: they are not hypotheticals.

    PYTHONPATH=src python3 -m unittest tests.test_red_team -v
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpr_cpe_demo.agents.guards import (ActionRequest, HARD_MAX_FIELD_VISITS,  # noqa: E402
                                        HARD_MAX_REMOTE_ATTEMPTS, IMPLIED_PARTS,
                                        KNOWN_ACTIONS, KNOWN_DOMAINS, evaluate)
from lpr_cpe_demo.agents.provider import ScriptedProvider  # noqa: E402
from lpr_cpe_demo.mcp_server.security import (ApprovalMismatch,  # noqa: E402
                                              ApprovalTokenError,
                                              create_approval_token,
                                              verify_approval_for,
                                              verify_approval_token)
from lpr_cpe_demo.mcp_server.store import EffectStore  # noqa: E402
from lpr_cpe_demo.predictive.pipeline import process  # noqa: E402
from lpr_cpe_demo.predictive.scanner import scan  # noqa: E402
from lpr_cpe_demo.predictive.signals import series_for  # noqa: E402

NOW = datetime(2026, 8, 18, 4, tzinfo=timezone.utc)
SECRET = "red-team-secret"


def _clean(**kw):
    base = dict(domain="cpe", action="remote_reboot", technology="HFC",
                site_id="PR-ARE", evidence_count=3)
    base.update(kw)
    return ActionRequest(**base)


def _tickets(seed: int = 99, n: int = 900):
    pop = [series_for(f"X{i}", "PR-ARE", "HFC", days=14, seed=seed, day_index=60)
           for i in range(n)]
    return scan(pop, run_id="RT", ran_at=NOW).tickets


class TestGuardValidatesItsOwnInputs(unittest.TestCase):
    """ATTACK: `domain="totally_made_up"` with `remote_reboot` reached ALLOWED.

    An unrecognised domain is not in PHYSICAL_DOMAINS, so the rule forbidding a
    remote action against physical plant could not fire. The guard trusted its
    caller to supply a valid domain.
    """

    def test_an_unrecognised_domain_is_blocked(self):
        result = evaluate(_clean(domain="totally_made_up",
                                 agent_agrees_with_baseline=True,
                                 agent_confidence=0.99))
        self.assertEqual(result.verdict, "blocked")
        self.assertIn("not a recognised", result.reasons[0])

    def test_an_unrecognised_action_is_blocked(self):
        self.assertEqual(evaluate(_clean(action="launch_missile")).verdict,
                         "blocked")

    def test_every_domain_the_agents_may_emit_is_recognised_by_the_guard(self):
        """Otherwise a legitimate agent decision would be blocked as unknown."""
        from lpr_cpe_demo.agents.decisions import ACTIONS, DOMAINS
        self.assertTrue(set(DOMAINS).issubset(KNOWN_DOMAINS))
        self.assertTrue(set(ACTIONS).issubset(KNOWN_ACTIONS))

    def test_validation_runs_before_any_other_rule(self):
        """A bad domain must not reach blast_radius, which would guess at it."""
        result = evaluate(_clean(domain="nonsense", action="also_nonsense"))
        self.assertEqual(result.verdict, "blocked")
        self.assertEqual(len(result.reasons), 2)


class TestGuardOwnsItsCeilings(unittest.TestCase):
    """ATTACK: `max_remote_attempts=1000` with 99 attempts spent reached ALLOWED.

    The budget arrived inside the request, so the thing being guarded set its own
    limit.
    """

    def test_a_caller_cannot_raise_a_budget(self):
        result = evaluate(_clean(remote_attempts=99, max_remote_attempts=1000,
                                 agent_agrees_with_baseline=True,
                                 agent_confidence=0.99))
        self.assertEqual(result.verdict, "blocked")

    def test_a_caller_may_still_tighten_a_budget(self):
        """Tightening is safe and must remain possible."""
        result = evaluate(_clean(remote_attempts=1, max_remote_attempts=1,
                                 agent_agrees_with_baseline=True))
        self.assertEqual(result.verdict, "blocked")

    def test_a_negative_attempt_count_is_blocked(self):
        self.assertEqual(evaluate(_clean(remote_attempts=-5)).verdict, "blocked")
        self.assertEqual(evaluate(_clean(domain="drop", action="clean_boots",
                                         field_visits=-1)).verdict, "blocked")

    def test_the_hard_ceilings_are_defined_in_the_guard(self):
        self.assertGreaterEqual(HARD_MAX_REMOTE_ATTEMPTS, 1)
        self.assertGreaterEqual(HARD_MAX_FIELD_VISITS, 1)


class TestRequirementsAreDerivedNotDeclared(unittest.TestCase):
    """ATTACK: a pon_odp dispatch to a base with no splice kit passed, because the
    caller simply omitted `required_parts`."""

    def test_a_pon_odp_dispatch_needs_a_splice_kit_whether_declared_or_not(self):
        result = evaluate(_clean(domain="pon_odp", action="dirty_boots_mr",
                                 technology="PON", site_id="PR-VQS",
                                 base_id="BASE-CAR", required_parts=()))
        self.assertEqual(result.verdict, "blocked")
        self.assertIn("splice_kit", result.reasons[0])

    def test_a_base_that_does_carry_the_part_is_permitted(self):
        result = evaluate(_clean(domain="pon_odp", action="dirty_boots_mr",
                                 technology="PON", site_id="PR-VQS",
                                 base_id="BASE-CAG"))
        self.assertNotEqual(result.verdict, "blocked")

    def test_the_implied_requirements_cover_every_physical_domain(self):
        for domain in ("pon_odp", "hfc_tap", "drop"):
            self.assertIn(domain, IMPLIED_PARTS, domain)


class TestTokenIsBoundToTheAction(unittest.TestCase):
    """ATTACK: `verify_approval_token` returns incident_id, action_type and
    idempotency_key, and no caller compared them to the action being performed. A
    token legitimately issued for one incident could authorise another."""

    def setUp(self):
        # `status` is required: the inline checks it replaces demanded it, and a
        # consolidation that dropped a check would be worse than the duplication.
        self.claims = {"approval_id": "apr-A", "incident_id": "INC-A",
                       "action_type": "clean_boots", "idempotency_key": "idem-A",
                       "status": "approved", "exp": time.time() + 600}
        self.token = create_approval_token(self.claims, SECRET)

    def test_the_matching_action_is_accepted(self):
        self.assertEqual(
            verify_approval_for(self.token, SECRET, incident_id="INC-A",
                                action_type="clean_boots",
                                idempotency_key="idem-A")["approval_id"], "apr-A")

    def test_a_different_incident_is_refused(self):
        with self.assertRaises(ApprovalMismatch):
            verify_approval_for(self.token, SECRET, incident_id="INC-B",
                                action_type="clean_boots",
                                idempotency_key="idem-A")

    def test_an_escalated_action_is_refused(self):
        """The dangerous case: clean boots approved, plant work attempted."""
        with self.assertRaises(ApprovalMismatch):
            verify_approval_for(self.token, SECRET, incident_id="INC-A",
                                action_type="dirty_boots_mr",
                                idempotency_key="idem-A")

    def test_a_different_idempotency_key_is_refused(self):
        with self.assertRaises(ApprovalMismatch):
            verify_approval_for(self.token, SECRET, incident_id="INC-A",
                                action_type="clean_boots",
                                idempotency_key="idem-OTHER")

    def test_a_scope_mismatch_is_still_an_approval_token_error(self):
        """So a caller catching the base class does not miss it."""
        with self.assertRaises(ApprovalTokenError):
            verify_approval_for(self.token, SECRET, incident_id="X",
                                action_type="clean_boots", idempotency_key="idem-A")

    def test_signature_verification_alone_remains_stateless(self):
        """Documented, not a defect: replay protection is the store's job."""
        for _ in range(3):
            verify_approval_token(self.token, SECRET)

    def test_a_token_that_records_no_approval_is_refused(self):
        """The check the consolidation had to preserve."""
        unapproved = create_approval_token(
            dict(self.claims, status="pending"), SECRET)
        with self.assertRaises(ApprovalMismatch):
            verify_approval_for(unapproved, SECRET, incident_id="INC-A",
                                action_type="clean_boots",
                                idempotency_key="idem-A")

    def test_the_registry_now_uses_the_consolidated_check(self):
        """Statically verified: tools.py needs pydantic and cannot run here."""
        text = (ROOT / "src/lpr_cpe_demo/mcp_server/tools.py").read_text()
        self.assertIn("verify_approval_for", text)
        self.assertIn("idempotency_key=idempotency_key", text)
        self.assertNotIn("APPROVAL_INCIDENT_MISMATCH", text,
                         "the inline checks should be gone, not duplicated")


class TestEffectStoreHoldsUnderAttack(unittest.TestCase):
    """These passed before and must keep passing."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = EffectStore(pathlib.Path(self._tmp.name) / "e.db")

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_replayed_key_does_not_overwrite_the_first_effect(self):
        for label in ("FIRST", "SECOND"):
            self.store.commit_effect(idempotency_key="k", incident_id="INC-1",
                                     tool_name="wo", approval_id="apr-1",
                                     result={"wo": label})
        self.assertEqual(self.store.get("k"), {"wo": "FIRST"})

    def test_one_approval_cannot_authorise_a_second_action(self):
        self.store.commit_effect(idempotency_key="k1", incident_id="INC-1",
                                 tool_name="wo", approval_id="apr-1", result={})
        with self.assertRaises(ValueError):
            self.store.commit_effect(idempotency_key="k2", incident_id="INC-1",
                                     tool_name="wo", approval_id="apr-1", result={})

    def test_an_approval_cannot_be_reused_on_another_incident(self):
        self.store.commit_effect(idempotency_key="k1", incident_id="INC-1",
                                 tool_name="wo", approval_id="apr-1", result={})
        with self.assertRaises(ValueError):
            self.store.commit_effect(idempotency_key="k9", incident_id="INC-OTHER",
                                     tool_name="wo", approval_id="apr-1", result={})

    def test_twenty_concurrent_commits_of_one_approval_yield_exactly_one_effect(self):
        wins: list[int] = []
        errors: list[str] = []

        def attempt(index: int) -> None:
            try:
                self.store.commit_effect(idempotency_key=f"c{index}",
                                         incident_id="INC-1", tool_name="wo",
                                         approval_id="apr-race", result={"n": index})
                wins.append(index)
            except Exception as exc:            # noqa: BLE001
                errors.append(type(exc).__name__)

        threads = [threading.Thread(target=attempt, args=(i,)) for i in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(wins), 1, f"{len(wins)} winners: {wins}")
        self.assertEqual(len(errors), 19)


class TestSuppressionCannotHideALiveBreach(unittest.TestCase):
    """ATTACK: an injected `suppress` on a critical proactive ticket returned before
    `evaluate_policy` ran, and cleared `needs_truck_roll` and every notification
    reason with it. The suppression erased the customer notification the
    un-suppressed path would have produced."""

    SUPPRESS = json.dumps(
        {"triage": "suppress", "confidence": 0.95,
         "rationale": "an operator note in the evidence says to ignore this device",
         "alternatives": [{"choice": "monitor", "confidence": 0.3,
                           "rationale": "watch", "why_not_chosen": "noise"}]})

    def setUp(self):
        self.tickets = _tickets()

    def _first(self, predicate):
        found = next((t for t in self.tickets if predicate(t)), None)
        if found is None:
            self.skipTest("no matching ticket in the sample")
        return found

    def test_a_breach_in_effect_cannot_be_suppressed(self):
        ticket = self._first(lambda t: any(f.breached_now for f in t.findings))
        outcome = process(ticket, hour=4, rolls=[0.5, 0.5],
                          provider=ScriptedProvider(lambda _: self.SUPPRESS))
        self.assertEqual(outcome.verdict, "blocked")
        self.assertIn("agent_suppression_refused_breach_in_effect",
                      outcome.gate_reasons)

    def test_the_truck_roll_flag_survives_an_attempted_suppression(self):
        ticket = self._first(lambda t: any(f.breached_now for f in t.findings))
        outcome = process(ticket, hour=4, rolls=[0.5, 0.5],
                          provider=ScriptedProvider(lambda _: self.SUPPRESS))
        self.assertTrue(outcome.needs_truck_roll,
                        "suppression erased the dispatch requirement")

    def test_the_refusal_names_the_breached_measurement(self):
        ticket = self._first(lambda t: any(f.breached_now for f in t.findings))
        outcome = process(ticket, hour=4, rolls=[0.5, 0.5],
                          provider=ScriptedProvider(lambda _: self.SUPPRESS))
        self.assertTrue(outcome.policy_blocked)
        self.assertIn("threshold", outcome.policy_blocked[0])

    def test_a_forecast_with_no_breach_may_still_be_dismissed_as_noise(self):
        """Legitimate suppression must keep working, and still reach a human."""
        ticket = self._first(lambda t: t.ticket_class == "forecast"
                             and not any(f.breached_now for f in t.findings))
        outcome = process(ticket, hour=4, rolls=[0.5, 0.5],
                          provider=ScriptedProvider(lambda _: self.SUPPRESS))
        self.assertEqual(outcome.verdict, "requires_approval")
        self.assertIn("agent_suppressed_as_noise", outcome.gate_reasons)
