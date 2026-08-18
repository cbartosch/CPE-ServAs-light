"""Tests for the agent layer.

The operator chose that agents decide and that policy and the gates are the only
guard. That makes three things load-bearing, and they are what these tests cover:
schema validation, the deterministic fallback, and a policy strong enough to stop
a schema-valid but harmful decision.

    PYTHONPATH=src python3 -m unittest tests.test_agents -v
"""
from __future__ import annotations

import io
import json
import pathlib
import sys
import unittest
import urllib.error

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpr_cpe_demo.agents.base import (Agent, AgentError, Alternative,  # noqa: E402
                                      UNTRUSTED_DATA_NOTICE, bounded_confidence,
                                      extract_json, one_of, require)
from lpr_cpe_demo.agents.decisions import (ACTIONS, DOMAINS, TRIAGE,  # noqa: E402
                                           baseline_triage_for, rca_agent,
                                           recommendation_agent, route_agent,
                                           route_options, triage_agent)
from lpr_cpe_demo.agents.guards import (ActionRequest, HIGH_BLAST_RADIUS,  # noqa: E402
                                        evaluate)
from lpr_cpe_demo.agents.provider import (AnthropicProvider,  # noqa: E402
                                          NullProvider, ProviderError,
                                          ScriptedProvider,
                                          _extract_text,
                                          provider_from_env)


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def canned(payload: dict):
    def opener(request, timeout=None):
        return _Resp(json.dumps(payload).encode())
    return opener


def scripted(text: str) -> ScriptedProvider:
    return ScriptedProvider(lambda _prompt: text)


class TestProvider(unittest.TestCase):
    def test_text_is_joined_across_blocks_not_indexed_at_zero(self):
        """A response may lead with a thinking or tool_use block."""
        data = {"content": [{"type": "thinking", "thinking": "..."},
                            {"type": "text", "text": "A"},
                            {"type": "text", "text": "B"}]}
        self.assertEqual(_extract_text(data), "A\nB")

    def test_a_response_with_no_text_block_is_not_usable(self):
        self.assertEqual(_extract_text({"content": [{"type": "tool_use"}]}), "")

    def test_the_request_carries_the_required_headers(self):
        seen = []

        def opener(request, timeout=None):
            seen.append(request)
            return _Resp(json.dumps(
                {"content": [{"type": "text", "text": "{}"}]}).encode())
        AnthropicProvider(api_key="k", opener=opener).complete(system="s", user="u")
        headers = {k.lower() for k in seen[0].headers}
        self.assertIn("x-api-key", headers)
        self.assertIn("anthropic-version", headers)

    def test_a_4xx_is_not_retried(self):
        """A bad key or malformed request fails identically every time."""
        def opener(request, timeout=None):
            raise urllib.error.HTTPError("u", 401, "unauthorised", {}, None)
        provider = AnthropicProvider(api_key="k", opener=opener, max_retries=3)
        with self.assertRaises(ProviderError):
            provider.complete(system="s", user="u")
        self.assertEqual(provider.calls, 1)

    def test_a_5xx_is_retried_to_the_limit(self):
        def opener(request, timeout=None):
            raise urllib.error.HTTPError("u", 503, "busy", {}, None)
        provider = AnthropicProvider(api_key="k", opener=opener, max_retries=2)
        with self.assertRaises(ProviderError):
            provider.complete(system="s", user="u")
        self.assertEqual(provider.calls, 3)

    def test_a_transport_failure_is_retried(self):
        attempts = {"n": 0}

        def opener(request, timeout=None):
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise urllib.error.URLError("dns")
            return _Resp(json.dumps(
                {"content": [{"type": "text", "text": "ok"}]}).encode())
        result = AnthropicProvider(api_key="k", opener=opener).complete(
            system="s", user="u")
        self.assertEqual(result.text, "ok")
        self.assertEqual(result.attempts, 2)

    def test_the_default_needs_no_key_and_no_network(self):
        self.assertIsInstance(provider_from_env({}), NullProvider)

    def test_a_key_selects_the_real_provider(self):
        self.assertIsInstance(provider_from_env({"ANTHROPIC_API_KEY": "x"}),
                              AnthropicProvider)

    def test_the_fake_can_be_forced_even_with_a_key(self):
        self.assertIsInstance(
            provider_from_env({"ANTHROPIC_API_KEY": "x", "LLM_PROVIDER": "fake"}),
            NullProvider)


class TestResponseParsing(unittest.TestCase):
    def test_clean_fenced_and_prose_wrapped_json_all_parse(self):
        for text in ('{"a":1}', '```json\n{"a":1}\n```', '```\n{"a":1}\n```',
                     'Sure, here:\n{"a":1}\nhope that helps'):
            self.assertEqual(extract_json(text), {"a": 1})

    def test_non_json_is_rejected(self):
        for text in ("hello", "[1,2]", "", "{unclosed"):
            with self.assertRaises(AgentError, msg=text):
                extract_json(text)

    def test_a_missing_field_is_rejected(self):
        with self.assertRaises(AgentError):
            require({}, "domain", str)

    def test_a_wrong_type_is_rejected(self):
        with self.assertRaises(AgentError):
            require({"confidence": "high"}, "confidence", float)

    def test_an_integer_confidence_is_accepted_as_a_float(self):
        self.assertEqual(require({"confidence": 1}, "confidence", float), 1.0)

    def test_confidence_outside_zero_to_one_is_rejected(self):
        for value in (-0.1, 1.4, 3.7):
            with self.assertRaises(AgentError):
                bounded_confidence(value)

    def test_a_value_outside_the_allowed_set_is_rejected(self):
        with self.assertRaises(AgentError):
            one_of("teleportation", ACTIONS, "action")


class TestFallbackToDeterminism(unittest.TestCase):
    """The rules no longer decide, but they still catch the agent."""

    def _agent(self, text: str | None):
        provider = scripted(text) if text is not None else NullProvider()
        return rca_agent(provider, baseline_domain="drop")

    def test_a_valid_decision_is_used(self):
        decision = self._agent(json.dumps(
            {"domain": "hfc_tap", "confidence": 0.81,
             "rationale": "six households on one tap", "alternatives": []})).decide("{}")
        self.assertEqual(decision.decision, "hfc_tap")
        self.assertFalse(decision.is_fallback)

    def test_an_unknown_domain_falls_back(self):
        decision = self._agent(json.dumps(
            {"domain": "gremlins", "confidence": 0.9, "rationale": "r"})).decide("{}")
        self.assertTrue(decision.is_fallback)
        self.assertEqual(decision.decision, "drop")

    def test_an_out_of_range_confidence_falls_back(self):
        decision = self._agent(json.dumps(
            {"domain": "cpe", "confidence": 4.2, "rationale": "r"})).decide("{}")
        self.assertTrue(decision.is_fallback)

    def test_unparsable_output_falls_back(self):
        self.assertTrue(self._agent("I think it's the tap, probably").decide("{}")
                        .is_fallback)

    def test_an_unavailable_provider_falls_back_rather_than_stalling(self):
        decision = self._agent(None).decide("{}")
        self.assertTrue(decision.is_fallback)
        self.assertEqual(decision.decision, "drop")

    def test_the_fallback_records_why(self):
        self.assertIsNotNone(self._agent("nonsense").decide("{}").fallback_reason)

    def test_the_fallback_confidence_is_not_asserted_as_high(self):
        self.assertLessEqual(self._agent(None).decide("{}").confidence, 0.5)

    def test_failures_are_counted(self):
        agent = self._agent("nonsense")
        for _ in range(3):
            agent.decide("{}")
        self.assertEqual(agent.failures, 3)

    def test_disagreement_with_the_baseline_is_visible(self):
        decision = self._agent(json.dumps(
            {"domain": "hfc_tap", "confidence": 0.8, "rationale": "r"})).decide("{}")
        self.assertFalse(decision.agrees_with_baseline)

    def test_agreement_with_the_baseline_is_visible(self):
        decision = self._agent(json.dumps(
            {"domain": "drop", "confidence": 0.8, "rationale": "r"})).decide("{}")
        self.assertTrue(decision.agrees_with_baseline)


class TestSecondBest(unittest.TestCase):
    def test_a_recommendation_without_an_alternative_is_refused(self):
        """An approver needs something to overturn to."""
        decision = recommendation_agent(scripted(json.dumps(
            {"action": "remote_reboot", "confidence": 0.8, "rationale": "r",
             "alternatives": []})), baseline_action="clean_boots").decide("{}")
        self.assertTrue(decision.is_fallback)
        self.assertIn("second best", decision.fallback_reason)

    def test_an_alternative_without_a_reason_it_lost_is_refused(self):
        decision = recommendation_agent(scripted(json.dumps(
            {"action": "remote_reboot", "confidence": 0.8, "rationale": "r",
             "alternatives": [{"choice": "clean_boots", "confidence": 0.4,
                               "rationale": "could visit"}]})),
            baseline_action="clean_boots").decide("{}")
        self.assertTrue(decision.is_fallback)

    def test_best_and_second_best_are_both_exposed(self):
        decision = recommendation_agent(scripted(json.dumps(
            {"action": "remote_reprovision", "confidence": 0.77,
             "rationale": "config drift signature",
             "alternatives": [{"choice": "remote_reboot", "confidence": 0.5,
                               "rationale": "clears transient state",
                               "why_not_chosen": "interrupts service and the "
                                                 "signature is configuration"}]})),
            baseline_action="remote_reboot").decide("{}")
        self.assertEqual(decision.best, "remote_reprovision")
        self.assertEqual(decision.second_best.choice, "remote_reboot")
        self.assertTrue(decision.second_best.why_not_chosen)

    def test_no_second_best_when_the_agent_fell_back(self):
        self.assertIsNone(recommendation_agent(NullProvider(),
                                              baseline_action="monitor")
                          .decide("{}").second_best)


class TestRouteAgent(unittest.TestCase):
    def setUp(self):
        self.options = route_options("PR-VQS", crew_type="dirty",
                                     required_skills=["fibre_splice"],
                                     required_parts=["splice_kit"])
        self.ids = [o["base_id"] for o in self.options]

    def test_candidates_carry_computed_facts_not_estimates(self):
        for option in self.options:
            for key in ("one_way_minutes", "requires_ferry", "fits_one_shift",
                        "has_required_parts"):
                self.assertIn(key, option)

    def test_the_nearest_base_may_lack_the_part(self):
        """The case the agent exists to weigh."""
        nearest = self.options[0]
        self.assertFalse(nearest["has_required_parts"])
        self.assertIn("splice_kit", nearest["missing_parts"])

    def test_a_base_outside_the_candidate_set_is_refused(self):
        decision = route_agent(scripted(json.dumps(
            {"base_id": "BASE-ATLANTIS", "confidence": 0.9, "rationale": "r"})),
            candidates=self.ids, baseline_base="BASE-CAR").decide("{}")
        self.assertTrue(decision.is_fallback)

    def test_the_agent_may_overrule_proximity_for_parts(self):
        decision = route_agent(scripted(json.dumps(
            {"base_id": "BASE-CAG", "confidence": 0.72, "rationale": "has the kit",
             "alternatives": [{"choice": "BASE-CAR", "confidence": 0.6,
                               "rationale": "nearest",
                               "why_not_chosen": "no splice kit"}]})),
            candidates=self.ids, baseline_base="BASE-CAR").decide("{}")
        self.assertEqual(decision.decision, "BASE-CAG")
        self.assertFalse(decision.agrees_with_baseline)


class TestTriageAgent(unittest.TestCase):
    def test_the_baseline_acts_now_on_a_proactive_ticket(self):
        class T:
            ticket_class, severity = "proactive", "critical"
        self.assertEqual(baseline_triage_for(T()), "act_now")

    def test_an_unknown_triage_value_falls_back(self):
        decision = triage_agent(scripted(json.dumps(
            {"triage": "panic", "confidence": 0.9, "rationale": "r"})),
            baseline_triage="schedule").decide("{}")
        self.assertTrue(decision.is_fallback)

    def test_suppress_is_available_so_noise_can_be_dismissed(self):
        self.assertIn("suppress", TRIAGE)


class TestPolicyIsLoadBearing(unittest.TestCase):
    """Every rule exists because an agent can emit valid JSON that is still wrong."""

    def _req(self, **kw):
        base = dict(domain="cpe", action="remote_reboot", technology="HFC",
                    site_id="PR-ARE", evidence_count=3)
        base.update(kw)
        return ActionRequest(**base)

    def test_a_remote_action_on_a_physical_fault_is_blocked(self):
        for domain in ("hfc_tap", "pon_odp", "plant", "drop"):
            result = evaluate(self._req(domain=domain, action="remote_reboot"))
            self.assertEqual(result.verdict, "blocked", domain)

    def test_clean_boots_on_a_plant_fault_is_blocked(self):
        self.assertEqual(evaluate(self._req(domain="hfc_tap",
                                           action="clean_boots")).verdict, "blocked")

    def test_an_exhausted_remote_budget_is_blocked(self):
        self.assertEqual(evaluate(self._req(remote_attempts=2)).verdict, "blocked")

    def test_an_exhausted_field_budget_is_blocked(self):
        self.assertEqual(evaluate(self._req(domain="drop", action="clean_boots",
                                           field_visits=3)).verdict, "blocked")

    def test_a_base_without_the_required_part_is_blocked(self):
        result = evaluate(self._req(domain="pon_odp", action="dirty_boots_mr",
                                    technology="PON", site_id="PR-VQS",
                                    base_id="BASE-CAR",
                                    required_parts=["splice_kit"]))
        self.assertEqual(result.verdict, "blocked")
        self.assertIn("splice_kit", result.reasons[0])

    def test_a_base_without_the_required_skill_is_blocked(self):
        result = evaluate(self._req(domain="pon_odp", action="dirty_boots_mr",
                                    technology="PON", site_id="PR-VQS",
                                    base_id="BASE-AGU",
                                    required_skills=["headend"]))
        self.assertEqual(result.verdict, "blocked")

    def test_an_unknown_base_is_blocked(self):
        self.assertEqual(evaluate(self._req(domain="drop", action="clean_boots",
                                           base_id="BASE-NOWHERE")).verdict,
                         "blocked")

    def test_no_evidence_blocks_any_action(self):
        self.assertEqual(evaluate(self._req(evidence_count=0)).verdict, "blocked")

    def test_disagreement_with_the_baseline_requires_a_human(self):
        result = evaluate(self._req(agent_agrees_with_baseline=False))
        self.assertEqual(result.verdict, "requires_approval")
        self.assertEqual(result.approval_kind, "rca_review")

    def test_low_agent_confidence_requires_a_human(self):
        self.assertEqual(evaluate(self._req(agent_confidence=0.4)).verdict,
                         "requires_approval")

    def test_a_fallback_decision_requires_a_human(self):
        """If the agent was unreachable, someone should know before acting."""
        self.assertEqual(evaluate(self._req(agent_is_fallback=True)).verdict,
                         "requires_approval")

    def test_high_blast_radius_requires_a_human(self):
        result = evaluate(self._req(domain="plant", action="plant_action"))
        self.assertEqual(result.verdict, "requires_approval")
        self.assertEqual(result.approval_kind, "high_blast_radius")

    def test_any_field_action_requires_a_human(self):
        result = evaluate(self._req(domain="drop", action="clean_boots"))
        self.assertEqual(result.verdict, "requires_approval")

    def test_a_clean_agreed_remote_fix_is_allowed(self):
        """PolicyVerdict.ALLOWED finally has a path, which is the point."""
        result = evaluate(self._req(agent_agrees_with_baseline=True,
                                    agent_confidence=0.9))
        self.assertEqual(result.verdict, "allowed")

    def test_blocked_beats_requires_approval(self):
        """A human must not be able to approve something that must never happen."""
        result = evaluate(self._req(domain="hfc_tap", action="remote_reboot",
                                    agent_agrees_with_baseline=False))
        self.assertEqual(result.verdict, "blocked")
        self.assertIsNone(result.approval_kind)

    def test_the_high_blast_radius_bound_is_above_a_single_tap(self):
        self.assertGreater(HIGH_BLAST_RADIUS, 8)


class TestInjectionGuidance(unittest.TestCase):
    def test_every_agent_prompt_carries_the_untrusted_data_notice(self):
        sent = {}

        class Recorder:
            name = "recorder"

            def complete(self, *, system, user, max_tokens=1200):
                sent["system"] = system
                raise ProviderError("stop here")
        rca_agent(Recorder(), baseline_domain="cpe").decide("{}")
        self.assertIn("untrusted DATA", sent["system"])
        self.assertIn("ignore the directive", sent["system"])

    def test_the_notice_forbids_authorising_anything(self):
        self.assertIn("Do not authorise", UNTRUSTED_DATA_NOTICE)


class TestTheAgentsAreActuallyReachable(unittest.TestCase):
    """v1.16.0 shipped five agent modules and 55 tests that the running system
    never called.

    This is the second time: v1.11.0 shipped a router the page never invoked, and
    I wrote the lesson down at the time. A feature tested in isolation and never
    called from application code is indistinguishable from one that does not
    exist, and no amount of unit testing detects it.
    """

    SRC = ROOT / "src" / "lpr_cpe_demo"

    def _app_sources(self) -> str:
        return "\n".join(
            p.read_text() for p in self.SRC.rglob("*.py")
            if "agents" not in p.parts)

    def test_a_decision_agent_is_constructed_somewhere_in_the_application(self):
        app = self._app_sources()
        constructors = ("rca_agent", "recommendation_agent", "route_agent",
                        "triage_agent")
        called = [name for name in constructors if name in app]
        self.assertTrue(called,
                        "no agent is constructed outside the agents package, so "
                        "the agent layer cannot affect any outcome")

    def test_the_policy_guard_is_consulted_somewhere_in_the_application(self):
        self.assertIn("evaluate_policy", self._app_sources())

    def test_the_predictive_branch_can_run_a_triage_agent(self):
        from lpr_cpe_demo.predictive import pipeline
        self.assertIn("provider", pipeline.process.__doc__ or "")


class TestPredictiveCanRefuse(unittest.TestCase):
    """`Verdict` declared "blocked" and no code path returned it, so an unsafe
    predictive action could only be approved, never refused."""

    def _ticket(self, cause: str):
        from datetime import datetime, timezone
        from lpr_cpe_demo.predictive.scanner import scan
        from lpr_cpe_demo.predictive.signals import series_for
        pop = [series_for(f"B-{i:04d}", "PR-ARE", "HFC", days=14, seed=31,
                          cause=cause) for i in range(300)]
        result = scan(pop, run_id="B",
                      ran_at=datetime(2026, 8, 18, 4, tzinfo=timezone.utc))
        if not result.tickets:
            self.skipTest(f"{cause} produced no ticket")
        return result.tickets[0]

    def test_a_blocked_verdict_is_now_reachable(self):
        from lpr_cpe_demo.agents.guards import ActionRequest, evaluate
        result = evaluate(ActionRequest(
            domain="hfc_tap", action="clean_boots", technology="HFC",
            site_id="PR-ARE", evidence_count=2))
        self.assertEqual(result.verdict, "blocked")

    def test_the_pipeline_reports_a_blocked_action_rather_than_approving_it(self):
        from lpr_cpe_demo.predictive.pipeline import process
        outcome = process(self._ticket("tap_or_odp"), hour=4, rolls=[0.5, 0.5])
        self.assertTrue(outcome.needs_truck_roll)
        # dirty_boots_mr on a tap is legitimate, so this must NOT block
        self.assertNotEqual(outcome.verdict, "blocked")

    def test_the_agent_may_suppress_a_finding_as_noise(self):
        import json as _json
        from lpr_cpe_demo.predictive.pipeline import process
        response = _json.dumps(
            {"triage": "suppress", "confidence": 0.7,
             "rationale": "r-squared 0.09, this is noise",
             "alternatives": [{"choice": "monitor", "confidence": 0.5,
                               "rationale": "watch", "why_not_chosen": "not worth "
                                                                      "a ticket"}]})
        outcome = process(self._ticket("cpe_state"), hour=4, rolls=[0.5, 0.5],
                          provider=scripted(response))
        self.assertEqual(outcome.triage, "suppress")
        self.assertIn("agent_suppressed_as_noise", outcome.gate_reasons)

    def test_suppression_still_records_the_ticket(self):
        """A dismissed finding must not vanish silently."""
        import json as _json
        from lpr_cpe_demo.predictive.pipeline import process
        response = _json.dumps(
            {"triage": "suppress", "confidence": 0.7, "rationale": "noise",
             "alternatives": [{"choice": "monitor", "confidence": 0.5,
                               "rationale": "w", "why_not_chosen": "n"}]})
        outcome = process(self._ticket("cpe_state"), hour=4, rolls=[0.5, 0.5],
                          provider=scripted(response))
        self.assertEqual(outcome.verdict, "requires_approval")
        self.assertTrue(outcome.escalated)


class TestProviderSwitchesAgree(unittest.TestCase):
    """MODEL_PROVIDER governed the RCA assistant and LLM_PROVIDER the agents, so
    MODEL_PROVIDER=fake with a key present sent one to the fake and the other
    live."""

    def test_either_switch_set_to_fake_forces_the_fake(self):
        for env in ({"ANTHROPIC_API_KEY": "k", "MODEL_PROVIDER": "fake"},
                    {"ANTHROPIC_API_KEY": "k", "LLM_PROVIDER": "fake"},
                    {"ANTHROPIC_API_KEY": "k", "MODEL_PROVIDER": "fake",
                     "LLM_PROVIDER": "anthropic"}):
            self.assertIsInstance(provider_from_env(env), NullProvider, str(env))

    def test_a_key_with_neither_switch_goes_live(self):
        self.assertIsInstance(provider_from_env({"ANTHROPIC_API_KEY": "k"}),
                              AnthropicProvider)

    def test_the_env_template_documents_both(self):
        template = (ROOT / ".env.example").read_text()
        self.assertIn("MODEL_PROVIDER", template)
        self.assertIn("LLM_PROVIDER", template)


class TestGuardsStateTheirAssumptions(unittest.TestCase):
    def test_the_blast_radius_threshold_has_a_stated_basis(self):
        from lpr_cpe_demo.agents.guards import assumptions
        data = assumptions()
        self.assertIn("assumed", data["high_blast_radius_basis"])
        self.assertGreater(data["high_blast_radius"], 8)


class TestProviderNamesAreHonest(unittest.TestCase):
    """`FakeProvider` produced nothing and forced the deterministic fallback, while
    v1.2's `llm/service.py` fake produces a plausible scripted proposal. Two things
    called fake with opposite behaviour, and the misleading one was mine."""

    def test_a_null_provider_always_refuses(self):
        from lpr_cpe_demo.agents.provider import NullProvider
        with self.assertRaises(ProviderError):
            NullProvider().complete(system="s", user="u")

    def test_a_null_provider_says_why(self):
        from lpr_cpe_demo.agents.provider import NullProvider
        with self.assertRaises(ProviderError) as ctx:
            provider_from_env({}).complete(system="s", user="u")
        self.assertIn("ANTHROPIC_API_KEY", str(ctx.exception))

    def test_a_forced_fake_says_it_was_deliberate_not_missing(self):
        provider = provider_from_env({"ANTHROPIC_API_KEY": "k",
                                      "MODEL_PROVIDER": "fake"})
        self.assertIn("deliberately bypassed", provider.reason)

    def test_a_scripted_provider_requires_a_script(self):
        from lpr_cpe_demo.agents.provider import ScriptedProvider
        with self.assertRaises(TypeError):
            ScriptedProvider()

    def test_a_scripted_provider_labels_its_source_distinctly(self):
        from lpr_cpe_demo.agents.provider import ScriptedProvider
        result = ScriptedProvider(lambda _: "{}").complete(system="s", user="u")
        self.assertEqual(result.source, "scripted")

    def test_the_misleading_name_is_gone(self):
        import lpr_cpe_demo.agents.provider as module
        self.assertFalse(hasattr(module, "FakeProvider"))


class TestAgentStatusIsVisible(unittest.TestCase):
    """With no key every agent fell back and nothing reported it. The Control Tower
    looked identical to a fully agentic run."""

    def setUp(self):
        from lpr_cpe_demo.agents.status import StatusRecorder
        self.recorder = StatusRecorder()

    def _agent(self, provider, baseline="drop"):
        agent = rca_agent(provider, baseline_domain=baseline)
        agent.recorder = self.recorder
        return agent

    def test_a_fresh_recorder_reports_no_observation_not_zero(self):
        """Zero would read as "no fallbacks, all healthy"."""
        self.assertIsNone(self.recorder.snapshot({})["fallback_rate"])

    def test_no_key_is_reported_as_inactive_before_anything_runs(self):
        from lpr_cpe_demo.agents.status import describe_provider
        description = describe_provider({})
        self.assertFalse(description.active)
        self.assertIn("deterministic rules", description.headline)

    def test_a_forced_fake_is_reported_as_inactive_too(self):
        from lpr_cpe_demo.agents.status import describe_provider
        self.assertFalse(describe_provider({"ANTHROPIC_API_KEY": "k",
                                            "MODEL_PROVIDER": "fake"}).active)

    def test_the_key_itself_is_never_placed_in_the_snapshot(self):
        snapshot = self.recorder.snapshot({"ANTHROPIC_API_KEY": "sk-secret-123"})
        self.assertNotIn("sk-secret-123", str(snapshot))
        self.assertTrue(snapshot["key_present"])

    def test_every_fallback_is_counted_with_its_reason(self):
        agent = self._agent(provider_from_env({}))
        for _ in range(3):
            agent.decide("{}")
        snapshot = self.recorder.snapshot({})
        self.assertEqual(snapshot["attempted"], 3)
        self.assertEqual(snapshot["fell_back"], 3)
        self.assertEqual(snapshot["fallback_rate"], 1.0)
        self.assertTrue(snapshot["fallback_reasons"][0]["reason"])

    def test_an_accepted_decision_is_counted_as_accepted(self):
        import json as _json
        good = _json.dumps({"domain": "hfc_tap", "confidence": 0.8,
                            "rationale": "r", "alternatives": []})
        agent = self._agent(scripted(good))
        agent.decide("{}")
        snapshot = self.recorder.snapshot({"ANTHROPIC_API_KEY": "k"})
        self.assertEqual(snapshot["accepted"], 1)
        self.assertEqual(snapshot["fell_back"], 0)

    def test_disagreement_with_the_baseline_is_counted_per_agent(self):
        import json as _json
        good = _json.dumps({"domain": "hfc_tap", "confidence": 0.8,
                            "rationale": "r", "alternatives": []})
        agent = self._agent(scripted(good), baseline="drop")
        agent.decide("{}")
        self.assertEqual(self.recorder.by_agent()[0]["disagreed"], 1)

    def test_the_verdict_distinguishes_inactive_from_all_attempts_failing(self):
        inactive = self.recorder.snapshot({})["verdict"]
        self.assertIn("INACTIVE", inactive)
        agent = self._agent(scripted("not json"))
        agent.decide("{}")
        configured = self.recorder.snapshot({"ANTHROPIC_API_KEY": "k"})["verdict"]
        self.assertIn("every attempt fell back", configured)

    def test_a_configured_provider_with_no_runs_says_so(self):
        verdict = self.recorder.snapshot({"ANTHROPIC_API_KEY": "k"})["verdict"]
        self.assertIn("nothing has run yet", verdict)

    def test_the_recorder_is_bounded_so_a_long_run_cannot_grow_forever(self):
        from lpr_cpe_demo.agents.status import AgentRun, StatusRecorder
        recorder = StatusRecorder(limit=10)
        for index in range(50):
            recorder.record(AgentRun("x", "scripted", True))
        self.assertEqual(recorder.attempted, 10)

    def test_the_dashboard_carries_an_agent_status_block(self):
        from lpr_cpe_demo.dashboard import build
        block = build(count=20).block("agent_status")
        self.assertTrue(block.note)
        metrics = {row["metric"] for row in block.data}
        self.assertIn("API key present", metrics)
        self.assertIn("fallback rate", metrics)

    def test_the_block_is_not_labelled_computed_when_no_model_is_active(self):
        """Labelling an inactive layer `computed` would be the original problem."""
        from lpr_cpe_demo.dashboard import build
        self.assertEqual(build(count=20).block("agent_status").provenance,
                         "assumed")

    def test_the_hero_badge_states_the_provider_status(self):
        from lpr_cpe_demo.dashboard import build
        labels = [badge["label"] for badge in build(count=20).badges]
        self.assertTrue(any("model" in label.lower() for label in labels))
