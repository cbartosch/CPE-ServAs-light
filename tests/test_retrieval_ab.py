"""Tests for the v1.3 retrieval, gating and A/B measurement layer.

Runs on the standard library alone:

    PYTHONPATH=src python3 -m unittest tests.test_retrieval_ab -v

Also collected by pytest on a developer machine.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpr_cpe_demo.ab_metrics import ArmReport, CaseResult  # noqa: E402
from lpr_cpe_demo.controls import (GATE_HUMAN_REVIEW, GATE_PROCEED,  # noqa: E402
                                   fuse_and_gate)
from lpr_cpe_demo.retrieval import (BM25Index, Document, build_index,  # noqa: E402
                                    tokenize, vote_domain)

KB = ROOT / "src/lpr_cpe_demo/kb/prior_cases.json"
BENCH = ROOT / "src/lpr_cpe_demo/kb/benchmark.json"


class TestFuseAndGate(unittest.TestCase):
    """The rule extracted from WorkflowEngine._fusion. Behaviour must not drift."""

    def test_model_never_sets_the_domain(self):
        out = fuse_and_gate(deterministic_domain="drop", deterministic_confidence=0.9,
                            model_domain="hfc_tap", model_confidence=0.99, threshold=0.7)
        self.assertEqual(out.approved_domain, "drop")

    def test_disagreement_above_threshold_still_gates(self):
        out = fuse_and_gate(deterministic_domain="drop", deterministic_confidence=0.74,
                            model_domain="hfc_tap", model_confidence=0.78, threshold=0.70)
        self.assertEqual(out.route, GATE_HUMAN_REVIEW)
        self.assertEqual(out.gate_reason, "domain_disagreement")

    def test_confidence_is_the_minimum(self):
        out = fuse_and_gate(deterministic_domain="drop", deterministic_confidence=0.9,
                            model_domain="drop", model_confidence=0.55, threshold=0.7)
        self.assertEqual(out.fused_confidence, 0.55)
        self.assertEqual(out.gate_reason, "low_confidence")

    def test_model_cannot_raise_confidence(self):
        out = fuse_and_gate(deterministic_domain="drop", deterministic_confidence=0.60,
                            model_domain="drop", model_confidence=0.99, threshold=0.70)
        self.assertEqual(out.route, GATE_HUMAN_REVIEW)

    def test_low_confidence_reported_before_disagreement(self):
        out = fuse_and_gate(deterministic_domain="drop", deterministic_confidence=0.40,
                            model_domain="hfc_tap", model_confidence=0.95, threshold=0.70)
        self.assertEqual(out.gate_reason, "low_confidence")

    def test_deterministic_only_arm_has_no_agreement_signal(self):
        out = fuse_and_gate(deterministic_domain="drop", deterministic_confidence=0.9,
                            threshold=0.7)
        self.assertIsNone(out.domain_agreement)
        self.assertEqual(out.route, GATE_PROCEED)

    def test_model_confidence_required_when_domain_given(self):
        with self.assertRaises(ValueError):
            fuse_and_gate(deterministic_domain="drop", deterministic_confidence=0.9,
                          model_domain="hfc_tap", threshold=0.7)


class TestRetrieval(unittest.TestCase):
    def setUp(self):
        self.index = build_index(KB)

    def test_corpus_loads(self):
        self.assertGreaterEqual(len(self.index.docs), 25)

    def test_tokenizer_drops_stopwords_and_singletons(self):
        toks = tokenize("The customer reported a fault on the drop cable")
        self.assertNotIn("the", toks)
        self.assertNotIn("a", toks)
        self.assertIn("drop", toks)

    def test_technology_filter_excludes_other_access(self):
        hits = self.index.search("optical Rx low at the ONT", k=10, technology="HFC")
        self.assertTrue(all(h.technology in {"HFC", "ANY"} for h in hits))

    def test_multi_subscriber_tap_signature_votes_tap(self):
        hits = self.index.search(
            "ingress on several premises sharing one tap, corroded fittings",
            k=5, technology="HFC")
        self.assertEqual(vote_domain(hits).domain, "hfc_tap")

    def test_single_premise_signature_votes_drop(self):
        hits = self.index.search(
            "one premise low upstream power, tap reading correct, weathered drop cable",
            k=5, technology="HFC")
        self.assertEqual(vote_domain(hits).domain, "drop")

    def test_odp_group_signature_votes_odp(self):
        hits = self.index.search(
            "loss of signal for a group of ONTs behind one distribution point",
            k=5, technology="PON")
        self.assertEqual(vote_domain(hits).domain, "pon_odp")

    def test_confidence_is_bounded_and_derived(self):
        hits = self.index.search("tap ingress corrosion", k=5, technology="HFC")
        vote = vote_domain(hits)
        self.assertLessEqual(vote.confidence, 0.92)
        self.assertGreaterEqual(vote.confidence, 0.40)

    def test_no_hits_yields_no_vote(self):
        vote = vote_domain(self.index.search("zzzz unrelated gibberish", k=5))
        self.assertIsNone(vote.domain)
        self.assertEqual(vote.confidence, 0.0)

    def test_procedures_never_vote_on_domain(self):
        procs = [Document("P-1", "procedure", "ANY", "tap ingress boundary", "hfc_tap", "x")]
        self.assertIsNone(vote_domain(BM25Index().add(procs).search("tap ingress")).domain)

    def test_every_cited_reference_resolves(self):
        """Citation validity must be measurable, so ids have to be real."""
        known = {d.doc_id for d in self.index.docs}
        hits = self.index.search("optical loss at the distribution point", k=5,
                                 technology="PON")
        self.assertTrue(hits)
        self.assertTrue(all(h.doc_id in known for h in hits))


class TestBenchmarkCorpus(unittest.TestCase):
    def setUp(self):
        self.cases = json.loads(BENCH.read_text(encoding="utf-8"))["cases"]

    def test_every_case_has_ground_truth(self):
        self.assertTrue(all(c.get("true_domain") for c in self.cases))

    def test_corpus_contains_rules_errors_to_find(self):
        wrong = [c for c in self.cases if c["deterministic"]["domain"] != c["true_domain"]]
        self.assertGreaterEqual(len(wrong), 3,
                                "a benchmark with no rules errors cannot measure dissent")

    def test_corpus_contains_correct_hard_boundary_cases(self):
        """Without these, an arm that always dissents would score perfectly."""
        correct_drop = [c for c in self.cases
                        if c["true_domain"] == "drop"
                        and c["deterministic"]["domain"] == "drop"]
        self.assertGreaterEqual(len(correct_drop), 3)

    def test_benchmark_signatures_are_not_copied_from_the_kb(self):
        kb = {d.signature for d in build_index(KB).docs}
        overlap = [c["case_id"] for c in self.cases if c["signature"] in kb]
        self.assertFalse(overlap, f"verbatim reuse would make retrieval look better: {overlap}")


class TestMetrics(unittest.TestCase):
    @staticmethod
    def _case(det, true, gated, reason="none", **kw):
        return CaseResult(case_id="X", deterministic_domain=det, true_domain=true,
                          gate_raised=gated, gate_reason=reason, **kw)

    def test_gate_precision_counts_all_gates(self):
        report = ArmReport("t", [
            self._case("drop", "hfc_tap", True, "domain_disagreement"),
            self._case("drop", "drop", True, "low_confidence"),
        ])
        self.assertEqual(report.gate_precision, 0.5)
        self.assertEqual(report.false_alarms, 1)

    def test_dissent_precision_ignores_low_confidence_gates(self):
        report = ArmReport("t", [
            self._case("drop", "hfc_tap", True, "domain_disagreement"),
            self._case("drop", "drop", True, "low_confidence"),
        ])
        self.assertEqual(report.dissent_precision, 1.0)

    def test_recall_counts_any_gate(self):
        report = ArmReport("t", [
            self._case("drop", "hfc_tap", True, "low_confidence"),
            self._case("drop", "pon_odp", False),
        ])
        self.assertEqual(report.dissent_recall, 0.5)

    def test_avoided_and_missed_require_a_crew_change(self):
        report = ArmReport("t", [
            self._case("drop", "hfc_tap", True, "domain_disagreement"),   # clean -> dirty
            self._case("cpe", "wifi_or_home", True, "domain_disagreement"),  # clean -> clean
            self._case("drop", "pon_odp", False),                          # missed
        ])
        self.assertEqual(report.avoided_misdispatch, 1)
        self.assertEqual(report.missed_misdispatch, 1)

    def test_citation_validity_is_none_without_citations(self):
        self.assertIsNone(ArmReport("t", [self._case("drop", "drop", False)]).citation_validity)

    def test_citation_validity_penalises_unresolvable_refs(self):
        report = ArmReport("t", [self._case("drop", "drop", False,
                                            cited_refs=("A", "B"), valid_refs=("A",))])
        self.assertEqual(report.citation_validity, 0.5)


class TestHarnessEndToEnd(unittest.TestCase):
    def setUp(self):
        out = subprocess.run([sys.executable, "scripts/run_ab_matrix.py", "--json",
                              "/tmp/ab_result.json"],
                             cwd=ROOT, capture_output=True, text=True,
                             env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"})
        self.assertEqual(out.returncode, 0, out.stderr)
        self.result = json.loads(pathlib.Path("/tmp/ab_result.json").read_text(encoding="utf-8"))
        self.arms = {a["arm"]: a for a in self.result["arms"]}

    def test_every_arm_runs(self):
        """The fourth arm was added in v1.16.1 when the operator inverted authority.

        Asserting exactly three arms would now force the harness to keep measuring
        a configuration the bundle no longer uses.
        """
        self.assertEqual(set(self.arms),
                         {"deterministic", "plus_scripted_model", "plus_retrieval",
                          "agent_decides"})

    def test_the_agent_arm_makes_accuracy_a_real_outcome(self):
        """In the advisory arms the approved domain is always deterministic, so
        `rules_wrong` is identical across them by construction. Under agent
        authority it changes, which is the whole point of the inversion."""
        advisory = self.arms["plus_retrieval"]["rules_wrong"]
        decisive = self.arms["agent_decides"]["rules_wrong"]
        self.assertEqual(advisory, self.arms["deterministic"]["rules_wrong"])
        self.assertLess(decisive, advisory)

    def test_scripted_model_adds_nothing(self):
        """The shipped default echoes the rules, so it can never dissent.

        This is the finding the harness exists to make visible. If a future
        change gives the scripted fake an independent opinion, this test should
        fail and the claim in docs/AB_MEASUREMENT.md must be revisited.
        """
        det, scripted = self.arms["deterministic"], self.arms["plus_scripted_model"]
        self.assertEqual(scripted["gates"], det["gates"])
        self.assertEqual(scripted["missed_misdispatch"], det["missed_misdispatch"])
        self.assertEqual(scripted["gates"], 0)

    def test_retrieval_catches_rules_errors_the_others_miss(self):
        det, retr = self.arms["deterministic"], self.arms["plus_retrieval"]
        self.assertGreater(retr["avoided_misdispatch"], det["avoided_misdispatch"])
        self.assertLess(retr["missed_misdispatch"], det["missed_misdispatch"])

    def test_retrieval_advantage_is_not_free(self):
        """Guards against a rigged benchmark: the gain must cost interruptions."""
        retr = self.arms["plus_retrieval"]
        self.assertGreater(retr["interruption_per_100"], 0.0)
        self.assertLess(retr["gate_precision"], 1.0,
                        "zero false alarms across a realistic corpus is suspicious")

    def test_citation_validity_only_reported_where_retrieval_is_real(self):
        self.assertIsNone(self.arms["deterministic"]["citation_validity"])
        self.assertIsNone(self.arms["plus_scripted_model"]["citation_validity"])
        self.assertEqual(self.arms["plus_retrieval"]["citation_validity"], 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
