"""Tests for the plant topology and the effort/cost model.

    PYTHONPATH=src python3 -m unittest tests.test_plant_effort -v
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpr_cpe_demo.effort import (DURATIONS, RATES, ArmCost, assumptions,  # noqa: E402
                                 cost_arm, false_negative_cost,
                                 false_positive_cost, simulate_resolution)
from lpr_cpe_demo.geography import SITE_BY_ID  # noqa: E402
from lpr_cpe_demo.plant import (PLANT_ASSUMPTIONS, blast_radius,  # noqa: E402
                                chain_for, delimiter_for, footprint_totals,
                                households, site_plant)

FIXTURES = ROOT / "src/lpr_cpe_demo/fixtures"


class TestPlantIsHonestlyLabelled(unittest.TestCase):
    def test_assumptions_state_their_basis(self):
        self.assertIn("not LPR plant records", str(PLANT_ASSUMPTIONS["basis"]))
        self.assertIn("populations", str(PLANT_ASSUMPTIONS["household_basis"]))

    def test_every_element_is_flagged_assumed(self):
        for element in chain_for("PR-ARE", "HFC"):
            self.assertTrue(element.assumed, element.element_id)

    def test_modelled_scale_is_below_the_fcc_anchor(self):
        """23 of 78 municipios are modelled, so the total must be well under 1.22M."""
        total = footprint_totals()["households"]
        self.assertLess(total, 1_220_000)
        self.assertGreater(total, 300_000)


class TestPlantTopology(unittest.TestCase):
    def test_identifiers_are_deterministic_across_processes(self):
        code = ("import sys;sys.path.insert(0,'src');"
                "from lpr_cpe_demo.plant import delimiter_for;"
                "print(delimiter_for('PR-ARE','HFC').element_id)")
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                             capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), delimiter_for("PR-ARE", "HFC").element_id)

    def test_hfc_delimiter_is_a_tap_and_pon_is_an_odp(self):
        self.assertEqual(delimiter_for("PR-ARE", "HFC").kind, "tap")
        self.assertEqual(delimiter_for("PR-VQS", "PON").kind, "odp")

    def test_chain_runs_household_to_upstream(self):
        kinds = [e.kind for e in chain_for("PR-VQS", "PON")]
        self.assertEqual(kinds, ["household", "drop", "odp", "pon_port"])

    def test_only_the_delimiter_is_flagged_as_such(self):
        flagged = [e.kind for e in chain_for("PR-ARE", "HFC") if e.is_delimiter]
        self.assertEqual(flagged, ["tap"])

    def test_household_and_drop_are_clean_boots_delimiter_is_dirty(self):
        chain = {e.kind: e.crew_type for e in chain_for("PR-ARE", "HFC")}
        self.assertEqual(chain["household"], "clean")
        self.assertEqual(chain["drop"], "clean")
        self.assertEqual(chain["tap"], "dirty")

    def test_blast_radius_separates_drop_from_tap(self):
        """The number that makes a tap fault operationally different."""
        self.assertEqual(blast_radius("drop", "PR-ARE", "HFC"), 1)
        self.assertGreater(blast_radius("hfc_tap", "PR-ARE", "HFC"), 1)
        self.assertGreater(blast_radius("shared_network", "PR-ARE", "HFC"),
                           blast_radius("hfc_tap", "PR-ARE", "HFC"))

    def test_metro_taps_serve_more_homes_than_mountain_taps(self):
        self.assertGreater(blast_radius("hfc_tap", "PR-SJU", "HFC"),
                           blast_radius("hfc_tap", "PR-UTU", "HFC"))

    def test_site_plant_counts_are_internally_consistent(self):
        for sid in ("PR-SJU", "PR-UTU", "PR-CUL"):
            plant = site_plant(SITE_BY_ID[sid])
            self.assertEqual(plant["hfc_households"] + plant["pon_households"],
                             plant["households"], sid)
            self.assertGreaterEqual(plant["taps"], 1, sid)
            self.assertGreaterEqual(plant["odps"], 1, sid)

    def test_culebra_is_smaller_than_san_juan(self):
        self.assertLess(households(SITE_BY_ID["PR-CUL"]),
                        households(SITE_BY_ID["PR-SJU"]) / 100)


class TestEffortLedger(unittest.TestCase):
    def test_rates_are_labelled_as_placeholders(self):
        self.assertIn("not LPR actuals", str(assumptions()["basis"]))

    def test_remote_resolution_costs_no_truck_roll(self):
        led = simulate_resolution(incident_id="X", site_id="PR-BAY", technology="HFC",
                                  true_domain="provisioning")
        self.assertEqual(led.truck_rolls, 0)

    def test_failed_remote_attempts_add_time_and_a_visit(self):
        clean = simulate_resolution(incident_id="X", site_id="PR-BAY",
                                    technology="HFC", true_domain="cpe")
        retried = simulate_resolution(incident_id="X", site_id="PR-BAY",
                                      technology="HFC", true_domain="cpe",
                                      remote_attempts_failed=2)
        self.assertGreater(retried.total_minutes, clean.total_minutes)
        self.assertGreater(retried.truck_rolls, clean.truck_rolls)

    def test_misdispatch_produces_two_truck_rolls(self):
        led = simulate_resolution(incident_id="X", site_id="PR-ARE", technology="HFC",
                                  true_domain="hfc_tap", misdispatch=True)
        self.assertEqual(led.truck_rolls, 2)

    def test_misdispatch_costs_more_than_a_correct_dispatch(self):
        right = simulate_resolution(incident_id="X", site_id="PR-ARE",
                                    technology="HFC", true_domain="hfc_tap",
                                    gate_raised=True)
        wrong = simulate_resolution(incident_id="X", site_id="PR-ARE",
                                    technology="HFC", true_domain="hfc_tap",
                                    misdispatch=True)
        self.assertGreater(wrong.total_cost, right.total_cost)

    def test_island_dispatch_bills_ferry_and_overnight(self):
        led = simulate_resolution(incident_id="X", site_id="PR-CUL", technology="PON",
                                  true_domain="pon_odp")
        steps = {row["step"] for row in led.as_rows()}
        self.assertIn("ferry", steps)
        self.assertIn("overnight", steps)

    def test_mainland_dispatch_bills_neither(self):
        led = simulate_resolution(incident_id="X", site_id="PR-BAY", technology="HFC",
                                  true_domain="hfc_tap")
        steps = {row["step"] for row in led.as_rows()}
        self.assertNotIn("ferry", steps)
        self.assertNotIn("overnight", steps)

    def test_gate_review_is_billed_only_when_a_gate_fires(self):
        gated = simulate_resolution(incident_id="X", site_id="PR-ARE", technology="HFC",
                                    true_domain="hfc_tap", gate_raised=True)
        plain = simulate_resolution(incident_id="X", site_id="PR-ARE", technology="HFC",
                                    true_domain="hfc_tap")
        self.assertIn("gate review", {r["step"] for r in gated.as_rows()})
        self.assertNotIn("gate review", {r["step"] for r in plain.as_rows()})


class TestErrorCosts(unittest.TestCase):
    def test_false_negative_costs_far_more_than_a_false_positive(self):
        """The asymmetry is the whole argument for tolerating false alarms."""
        fp = false_positive_cost()
        for sid, domain in (("PR-ARE", "hfc_tap"), ("PR-CUL", "pon_odp")):
            fn = false_negative_cost(sid, domain)
            self.assertGreater(fn.cost_usd, 10 * fp.cost_usd, sid)

    def test_island_false_negative_costs_more_than_mainland(self):
        self.assertGreater(false_negative_cost("PR-CUL", "pon_odp").cost_usd,
                           false_negative_cost("PR-ARE", "hfc_tap").cost_usd)

    def test_false_negative_explains_what_is_and_is_not_counted(self):
        detail = false_negative_cost("PR-ARE", "hfc_tap").detail
        self.assertIn("wasted", detail)
        self.assertIn("still", detail)

    def test_cost_arm_counts_only_gated_right_and_ungated_wrong(self):
        cases = [
            # gated but the rules were right: a false positive
            {"gate_raised": True, "rules_wrong": False, "crew_would_differ": False,
             "site_id": "PR-ARE", "true_domain": "drop"},
            # rules wrong, not gated, crew differs: a false negative
            {"gate_raised": False, "rules_wrong": True, "crew_would_differ": True,
             "site_id": "PR-ARE", "true_domain": "hfc_tap"},
            # gated and the rules were wrong: correct, costs nothing here
            {"gate_raised": True, "rules_wrong": True, "crew_would_differ": True,
             "site_id": "PR-ARE", "true_domain": "hfc_tap"},
        ]
        cost = cost_arm("t", cases)
        self.assertEqual(cost.false_positives, 1)
        self.assertEqual(cost.false_negatives, 1)
        self.assertGreater(cost.fn_cost, cost.fp_cost)

    def test_a_wrong_domain_that_keeps_the_same_crew_is_not_billed(self):
        """cpe and wifi_or_home are both clean boots; no wasted visit."""
        cases = [{"gate_raised": False, "rules_wrong": True, "crew_would_differ": False,
                  "site_id": "PR-ARE", "true_domain": "wifi_or_home"}]
        self.assertEqual(cost_arm("t", cases).false_negatives, 0)


class TestScenariosCarryPlant(unittest.TestCase):
    def setUp(self):
        self.fixtures = {p.stem: json.loads(p.read_text(encoding="utf-8"))
                         for p in FIXTURES.glob("*.json")}

    def test_located_scenarios_have_a_plant_chain(self):
        for name, d in self.fixtures.items():
            if "site_id" not in d:
                continue
            plant = d.get("plant")
            self.assertIsNotNone(plant, name)
            self.assertTrue(plant["assumed"], name)
            for key in ("household", "drop", "delimiter_id", "upstream_id"):
                self.assertTrue(plant[key], f"{name}.{key}")

    def test_delimiter_matches_the_technology(self):
        for name, d in self.fixtures.items():
            if "plant" not in d:
                continue
            expected = "tap" if d["plant"]["technology"] == "HFC" else "odp"
            self.assertEqual(d["plant"]["delimiter_type"], expected, name)
            self.assertTrue(d["plant"]["delimiter_id"].startswith(expected.upper()), name)

    def test_recorded_plant_matches_the_live_model(self):
        """Stops the fixtures drifting away from plant.py."""
        for name, d in self.fixtures.items():
            if "plant" not in d:
                continue
            live = delimiter_for(d["site_id"], d["plant"]["technology"])
            self.assertEqual(d["plant"]["delimiter_id"], live.element_id, name)


class TestSimulationScript(unittest.TestCase):
    def test_dispatch_simulation_runs(self):
        out = subprocess.run([sys.executable, "scripts/run_dispatch_simulation.py"],
                             cwd=ROOT, capture_output=True, text=True,
                             env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"})
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("misdispatch", out.stdout)
        self.assertIn("false negative", out.stdout)

    def test_ab_matrix_reports_error_cost(self):
        out = subprocess.run([sys.executable, "scripts/run_ab_matrix.py",
                              "--json", "/tmp/ab_cost.json"],
                             cwd=ROOT, capture_output=True, text=True,
                             env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"})
        self.assertEqual(out.returncode, 0, out.stderr)
        payload = json.loads(pathlib.Path("/tmp/ab_cost.json").read_text(encoding="utf-8"))
        by_arm = {c["arm"]: c for c in payload["error_cost"]}
        self.assertEqual(set(by_arm),
                         {"deterministic", "plus_scripted_model", "plus_retrieval",
                          "agent_decides"})
        # retrieval trades false negatives for cheaper false positives
        self.assertEqual(by_arm["plus_retrieval"]["false_negatives"], 0)
        self.assertGreater(by_arm["deterministic"]["false_negatives"], 0)
        self.assertLess(by_arm["plus_retrieval"]["total_cost"],
                        by_arm["deterministic"]["total_cost"])


class TestPlantIdentifierUniqueness(unittest.TestCase):
    """Synthetic ids must be unique within a site, or a work order names the
    wrong element.

    The original `_seq` truncated sha256 to four decimal digits: 10,000 slots.
    San Juan models 8,709 taps, and 2,929 of them shared an id, 33.6%. By the
    birthday bound a 50% chance of one collision arrives at about 118 elements,
    so this was reachable at any realistic scale.
    """

    def test_no_collisions_at_full_modelled_scale(self):
        from lpr_cpe_demo.geography import sites_in_cpe_footprint
        from lpr_cpe_demo.plant import delimiter_for, site_plant
        collisions = []
        for site in sites_in_cpe_footprint():
            for count_key, tech in (("taps", "HFC"), ("odps", "PON")):
                total = site_plant(site)[count_key]
                seen: dict[str, int] = {}
                for index in range(total):
                    element = delimiter_for(site.site_id, tech, index).element_id
                    if element in seen:
                        collisions.append((element, seen[element], index))
                    seen[element] = index
        self.assertFalse(collisions[:5],
                         f"{len(collisions)} duplicate identifier(s), e.g. "
                         f"{collisions[:3]}")

    def test_the_birthday_bound_is_cleared_by_a_wide_margin(self):
        """A 4-digit space fails around 118 elements. Prove headroom well past that."""
        from lpr_cpe_demo.plant import delimiter_for
        ids = {delimiter_for("PR-SJU", "HFC", i).element_id for i in range(20_000)}
        self.assertEqual(len(ids), 20_000)

    def test_identifiers_differ_across_sites_at_the_same_index(self):
        from lpr_cpe_demo.plant import delimiter_for
        first = {delimiter_for(s, "HFC", 0).element_id
                 for s in ("PR-SJU", "PR-BAY", "PR-ARE", "PR-PON")}
        self.assertEqual(len(first), 4)

    def test_identifiers_differ_across_element_kinds(self):
        from lpr_cpe_demo.plant import chain_for
        ids = [e.element_id for e in chain_for("PR-ARE", "HFC", 7)]
        self.assertEqual(len(set(ids)), len(ids))

    def test_negative_index_is_rejected(self):
        from lpr_cpe_demo.plant import delimiter_for
        with self.assertRaises(ValueError):
            delimiter_for("PR-ARE", "HFC", -1)
