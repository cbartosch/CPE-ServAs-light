"""Tests for the fault generator and its map layers.

    PYTHONPATH=src python3 -m unittest tests.test_fault_generator -v
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import unittest
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpr_cpe_demo.fault_generator import (DOMAIN_MIX, generate_faults,  # noqa: E402
                                          summarise)
from lpr_cpe_demo.geo_layers import (COST_BANDS, cost_colour,  # noqa: E402
                                     cost_radius,
                                     fault_records, premise_link_records)
from lpr_cpe_demo.geography import SITE_BY_ID  # noqa: E402
from lpr_cpe_demo.plant import households  # noqa: E402

LAT_RANGE = (17.80, 18.65)
LON_RANGE = (-67.45, -65.10)


class TestReproducibility(unittest.TestCase):
    def test_same_seed_gives_identical_faults(self):
        a = generate_faults(30, seed=4242)
        b = generate_faults(30, seed=4242)
        self.assertEqual([f.fault_id for f in a], [f.fault_id for f in b])
        self.assertEqual([f.intervention_id for f in a], [f.intervention_id for f in b])
        self.assertEqual([f.total_cost_usd for f in a], [f.total_cost_usd for f in b])

    def test_different_seed_gives_different_faults(self):
        a = generate_faults(30, seed=1)
        b = generate_faults(30, seed=2)
        self.assertNotEqual([f.municipio for f in a], [f.municipio for f in b])

    def test_seed_survives_a_process_restart(self):
        """A demo must be able to quote a number and reproduce it later."""
        code = ("import sys;sys.path.insert(0,'src');"
                "from lpr_cpe_demo.fault_generator import generate_faults;"
                "print(sum(f.total_cost_usd for f in generate_faults(20, seed=99)))")
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                             capture_output=True, text=True)
        local = sum(f.total_cost_usd for f in generate_faults(20, seed=99))
        self.assertAlmostEqual(float(out.stdout.strip()), local, places=2)

    def test_a_given_tap_always_sits_in_the_same_place(self):
        """Jitter is hashed from the element id, not drawn from the RNG."""
        seen: dict[str, tuple[float, float]] = {}
        for seed in (1, 2, 3, 4, 5):
            for f in generate_faults(60, seed=seed):
                key = f.delimiter_id
                pos = (f.delimiter_lat, f.delimiter_lon)
                if key in seen:
                    self.assertEqual(seen[key], pos, key)
                else:
                    seen[key] = pos
        self.assertGreater(len(seen), 20)

    def test_count_must_be_positive(self):
        with self.assertRaises(ValueError):
            generate_faults(0)


class TestSampling(unittest.TestCase):
    def test_density_follows_households_not_municipios(self):
        counts = Counter(f.municipio for f in generate_faults(600, seed=11))
        self.assertGreater(counts["San Juan"], counts["Culebra"] * 20)

    def test_the_largest_site_is_the_most_frequent(self):
        counts = Counter(f.site_id for f in generate_faults(600, seed=12))
        biggest = max(SITE_BY_ID.values(), key=lambda s: households(s)
                      if s.in_cpe_footprint else 0)
        self.assertEqual(counts.most_common(1)[0][0], biggest.site_id)

    def test_every_archetype_has_a_domain_mix_summing_to_one(self):
        for archetype, mix in DOMAIN_MIX.items():
            self.assertAlmostEqual(sum(mix.values()), 1.0, places=6, msg=archetype)

    def test_mountain_and_island_skew_to_plant_more_than_metro(self):
        metro = DOMAIN_MIX["metro"]["delimiter"] + DOMAIN_MIX["metro"]["plant"]
        island = (DOMAIN_MIX["remote_island"]["delimiter"]
                  + DOMAIN_MIX["remote_island"]["plant"])
        self.assertGreater(island, metro)

    def test_generated_domains_are_all_recognised(self):
        allowed = {"provisioning", "cpe", "wifi_or_home", "premise_wiring", "drop",
                   "hfc_tap", "pon_odp", "plant", "shared_network"}
        for f in generate_faults(200, seed=13):
            self.assertIn(f.true_domain, allowed)

    def test_pon_faults_never_produce_an_hfc_delimiter(self):
        for f in generate_faults(200, seed=14):
            if f.technology == "PON":
                self.assertNotEqual(f.true_domain, "hfc_tap")
                self.assertEqual(f.delimiter_kind, "odp")
            else:
                self.assertNotEqual(f.true_domain, "pon_odp")
                self.assertEqual(f.delimiter_kind, "tap")


class TestInterventionLocation(unittest.TestCase):
    def test_premise_faults_are_worked_at_the_household(self):
        for f in generate_faults(150, seed=21):
            if f.true_domain in {"cpe", "wifi_or_home", "premise_wiring",
                                 "provisioning"}:
                self.assertTrue(f.intervention_is_at_premise, f.fault_id)
                self.assertAlmostEqual(f.intervention_lat, f.household_lat, places=5)

    def test_delimiter_faults_are_worked_away_from_the_household(self):
        """The point of the whole exercise: a tap fault is not at the address."""
        checked = 0
        for f in generate_faults(200, seed=22):
            if f.true_domain in {"hfc_tap", "pon_odp"}:
                self.assertFalse(f.intervention_is_at_premise, f.fault_id)
                self.assertNotEqual((f.intervention_lat, f.intervention_lon),
                                    (f.household_lat, f.household_lon))
                self.assertEqual(f.intervention_id, f.delimiter_id)
                checked += 1
        self.assertGreater(checked, 5)

    def test_delimiter_faults_affect_more_than_one_household(self):
        for f in generate_faults(200, seed=23):
            if f.true_domain in {"hfc_tap", "pon_odp"}:
                self.assertGreater(f.households_affected, 1, f.fault_id)

    def test_premise_faults_affect_exactly_one_household(self):
        for f in generate_faults(200, seed=24):
            if f.true_domain in {"cpe", "wifi_or_home", "drop", "premise_wiring"}:
                self.assertEqual(f.households_affected, 1, f.fault_id)

    def test_all_coordinates_land_inside_the_footprint(self):
        for f in generate_faults(300, seed=25):
            for lat, lon, label in ((f.household_lat, f.household_lon, "household"),
                                    (f.delimiter_lat, f.delimiter_lon, "delimiter"),
                                    (f.intervention_lat, f.intervention_lon,
                                     "intervention")):
                self.assertTrue(LAT_RANGE[0] <= lat <= LAT_RANGE[1],
                                f"{f.fault_id} {label} lat {lat}")
                self.assertTrue(LON_RANGE[0] <= lon <= LON_RANGE[1],
                                f"{f.fault_id} {label} lon {lon}")

    def test_plant_work_is_always_dirty_boots(self):
        for f in generate_faults(200, seed=26):
            if not f.intervention_is_at_premise:
                self.assertEqual(f.crew_type, "dirty", f.fault_id)


class TestCost(unittest.TestCase):
    def test_remote_fixable_faults_cost_less_than_plant_work(self):
        faults = generate_faults(200, seed=31)
        remote = [f.total_cost_usd for f in faults
                  if f.true_domain in {"provisioning", "cpe", "wifi_or_home"}]
        plant = [f.total_cost_usd for f in faults
                 if f.true_domain in {"hfc_tap", "pon_odp", "plant", "shared_network"}]
        self.assertLess(max(remote), min(plant))

    def test_misdispatch_always_costs_more(self):
        for f in generate_faults(150, seed=32):
            self.assertGreater(f.misdispatch_cost_usd, f.total_cost_usd, f.fault_id)
            self.assertGreater(f.misdispatch_premium_usd, 0.0, f.fault_id)

    def test_island_faults_are_the_most_expensive(self):
        faults = generate_faults(600, seed=33)
        island = [f.total_cost_usd for f in faults if f.requires_ferry]
        if island:
            mainland = [f.total_cost_usd for f in faults
                        if not f.requires_ferry and f.truck_rolls]
            self.assertGreater(max(island), max(mainland))

    def test_summary_totals_are_internally_consistent(self):
        faults = generate_faults(40, seed=34)
        stats = summarise(faults)
        self.assertEqual(stats["faults"], 40)
        self.assertAlmostEqual(float(stats["total_cost_usd"]),
                               sum(f.total_cost_usd for f in faults), places=2)
        self.assertEqual(stats["off_premise_interventions"],
                         sum(1 for f in faults if not f.intervention_is_at_premise))

    def test_summary_of_nothing_is_safe(self):
        self.assertEqual(summarise([])["faults"], 0)


class TestFaultLayers(unittest.TestCase):
    def setUp(self):
        self.faults = generate_faults(40, seed=41)



    def test_pins_sit_at_the_intervention_point(self):
        for record, fault in zip(fault_records(self.faults), self.faults):
            self.assertEqual(record["lat"], fault.intervention_lat)
            self.assertEqual(record["lon"], fault.intervention_lon)

    def test_premise_links_only_exist_for_off_premise_work(self):
        expected = sum(1 for f in self.faults if not f.intervention_is_at_premise)
        self.assertEqual(len(premise_link_records(self.faults)), expected)



    def test_cost_colour_and_radius_increase_with_cost(self):
        cheap, dear = cost_colour(50.0), cost_colour(2000.0)
        self.assertNotEqual(cheap, dear)
        self.assertGreater(cost_radius(2000.0), cost_radius(50.0))

    def test_cost_bands_are_ordered_and_cover_everything(self):
        ceilings = [c for c, _, _ in COST_BANDS]
        self.assertEqual(ceilings, sorted(ceilings))
        self.assertEqual(ceilings[-1], float("inf"))

