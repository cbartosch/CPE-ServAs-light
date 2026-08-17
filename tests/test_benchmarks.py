"""Tests for the third-party truck roll cost benchmark.

    PYTHONPATH=src python3 -m unittest tests.test_benchmarks -v
"""
from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpr_cpe_demo.benchmarks import (BANDS, FIRST_VISIT_COMPLETION,  # noqa: E402
                                     ISLAND_ADDER_USD, RURAL_ARCHETYPES,
                                     RURAL_UPLIFT, RURAL_UPLIFT_RANGE, SOURCE,
                                     band_for_profile, citation, roll_cost,
                                     wasted_visit_cost)
from lpr_cpe_demo.fault_generator import generate_faults  # noqa: E402


class TestSourceIsAttributable(unittest.TestCase):
    def test_source_carries_a_url_and_retrieval_date(self):
        self.assertTrue(SOURCE["url"].startswith("https://"))
        self.assertEqual(SOURCE["retrieved"], "2026-08-17")

    def test_citation_names_publisher_and_range(self):
        text = citation()
        self.assertIn("AEX", text)
        self.assertIn("$150", text)
        self.assertIn("$300", text)

    def test_inclusions_and_exclusions_are_recorded(self):
        self.assertIn("dispatch and back-office allocation", SOURCE["includes"])
        self.assertIn("corporate overhead", SOURCE["excludes"])

    def test_bands_sit_inside_the_headline_range_apart_from_the_extremes(self):
        low, high = SOURCE["headline_range_usd"]
        self.assertLessEqual(BANDS["mid"]["range"][0], high)
        self.assertGreaterEqual(BANDS["mid"]["range"][1], low)

    def test_every_band_records_the_operational_profile_behind_it(self):
        for band, data in BANDS.items():
            self.assertIn("first-visit completion", str(data["profile"]), band)


class TestBands(unittest.TestCase):
    def test_bands_are_ordered_and_do_not_overlap(self):
        lo, mid, hi = (BANDS[b]["range"] for b in ("low", "mid", "high"))
        self.assertLessEqual(lo[1], mid[0])
        self.assertLessEqual(mid[1], hi[0])

    def test_midpoints_sit_inside_their_range(self):
        for band, data in BANDS.items():
            low, high = data["range"]
            self.assertTrue(low <= data["midpoint"] <= high, band)

    def test_band_inferred_from_first_visit_completion(self):
        self.assertEqual(band_for_profile(0.93), "low")
        self.assertEqual(band_for_profile(0.82), "mid")
        self.assertEqual(band_for_profile(0.70), "high")

    def test_rural_uplift_is_the_midpoint_of_the_cited_range(self):
        self.assertAlmostEqual(RURAL_UPLIFT,
                               sum(RURAL_UPLIFT_RANGE) / 2, places=6)


class TestRollCost(unittest.TestCase):
    def test_rural_archetypes_carry_the_uplift_and_others_do_not(self):
        for archetype in ("metro", "coastal"):
            self.assertEqual(roll_cost(archetype, "HFC").rural_uplift_usd, 0.0)
        for archetype in RURAL_ARCHETYPES:
            self.assertGreater(roll_cost(archetype, "HFC").rural_uplift_usd, 0.0)

    def test_island_adder_is_kept_separate_from_the_cited_figure(self):
        """Blending it in would imply the source covers ferry and overnight."""
        mainland = roll_cost("mountain", "HFC", island=False)
        island = roll_cost("remote_island", "HFC", island=True)
        self.assertEqual(mainland.island_adder_usd, 0.0)
        self.assertEqual(island.island_adder_usd, ISLAND_ADDER_USD)
        self.assertTrue(mainland.within_benchmark_scope)
        self.assertFalse(island.within_benchmark_scope)

    def test_per_completed_exceeds_per_dispatch_whenever_fvc_is_imperfect(self):
        for archetype in ("metro", "coastal", "mountain"):
            for tech in ("HFC", "PON"):
                cost = roll_cost(archetype, tech)
                self.assertLess(cost.first_visit_completion, 1.0)
                self.assertGreater(cost.per_completed_usd, cost.per_dispatch_usd)
                self.assertGreater(cost.repeat_visit_premium_usd, 0.0)

    def test_the_sources_worked_example_reproduces(self):
        """$200 at 75% first-visit completion is about $267 per completed job."""
        self.assertAlmostEqual(200.0 / 0.75, 266.67, places=2)

    def test_pon_costs_less_per_completed_job_than_hfc(self):
        """Higher first-visit completion on PON, same band."""
        for archetype in ("metro", "coastal", "mountain"):
            self.assertLess(roll_cost(archetype, "PON").per_completed_usd,
                            roll_cost(archetype, "HFC").per_completed_usd, archetype)

    def test_mainland_costs_stay_inside_the_published_range(self):
        low, high = SOURCE["headline_range_usd"]
        for archetype in ("metro", "coastal", "mountain"):
            for tech in ("HFC", "PON"):
                cost = wasted_visit_cost(archetype, tech)
                self.assertTrue(low <= cost <= high * 1.25,
                                f"{archetype}/{tech} = {cost}")

    def test_higher_band_costs_more(self):
        self.assertLess(wasted_visit_cost("metro", "HFC", band="low"),
                        wasted_visit_cost("metro", "HFC", band="mid"))
        self.assertLess(wasted_visit_cost("metro", "HFC", band="mid"),
                        wasted_visit_cost("metro", "HFC", band="high"))

    def test_wasted_visit_uses_per_dispatch_not_per_completed(self):
        """Using per-completed would double count the repeat visits."""
        cost = roll_cost("coastal", "HFC")
        self.assertEqual(wasted_visit_cost("coastal", "HFC"), cost.per_dispatch_usd)

    def test_first_visit_completion_covers_every_archetype(self):
        for tech in ("HFC", "PON"):
            for archetype in ("metro", "coastal", "mountain", "remote_island"):
                self.assertIn(archetype, FIRST_VISIT_COMPLETION[tech])


class TestFaultsCarryBenchmarkFigures(unittest.TestCase):
    def setUp(self):
        self.faults = generate_faults(120, seed=51)

    def test_every_fault_has_a_benchmark_cost(self):
        for f in self.faults:
            self.assertGreater(f.benchmark_per_dispatch_usd, 0.0, f.fault_id)
            self.assertGreater(f.benchmark_per_completed_usd,
                               f.benchmark_per_dispatch_usd, f.fault_id)

    def test_island_faults_are_flagged_outside_benchmark_scope(self):
        for f in self.faults:
            if f.requires_ferry:
                self.assertFalse(f.benchmark_in_scope, f.fault_id)

    def test_mainland_faults_are_inside_benchmark_scope(self):
        for f in self.faults:
            if not f.requires_ferry:
                self.assertTrue(f.benchmark_in_scope, f.fault_id)

    def test_blended_benchmark_cost_lands_in_the_published_range(self):
        """The whole point of anchoring: the blend must be defensible."""
        mainland = [f.benchmark_wasted_usd for f in self.faults if f.benchmark_in_scope]
        blended = sum(mainland) / len(mainland)
        low, high = SOURCE["headline_range_usd"]
        self.assertTrue(low <= blended <= high, f"blend {blended}")
