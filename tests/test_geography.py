"""Tests for the location model.

    PYTHONPATH=src python3 -m unittest tests.test_geography -v
"""

from __future__ import annotations

import json
import pathlib
import sys
import unittest
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpr_cpe_demo.geography import (BASE_BY_ID, DISPATCH_BASES,  # noqa: E402
                                    FERRY_MINUTES, SITE_BY_ID, SITES,
                                    assumed_bases, bases_by_likelihood,
                                    core_sites, ferry_terminals, haversine_km,
                                    select_base, sites_by_archetype,
                                    sites_in_cpe_footprint, travel_plan)

MAP_SVG = ROOT / "src/lpr_cpe_demo/ui/assets/footprint_map.svg"
FIXTURES = ROOT / "src/lpr_cpe_demo/fixtures"
BENCH = ROOT / "src/lpr_cpe_demo/kb/benchmark.json"


class TestFootprintScope(unittest.TestCase):
    """The fixed CPE footprint is Puerto Rico. USVI is mobile under LPR."""

    def test_usvi_is_excluded_from_the_cpe_footprint(self):
        usvi = [s for s in SITES if s.site_id.startswith("VI-")]
        self.assertTrue(usvi, "USVI should be modelled, so the exclusion is explicit")
        self.assertTrue(all(not s.in_cpe_footprint for s in usvi))

    def test_island_municipios_are_in_scope(self):
        ids = {s.site_id for s in sites_in_cpe_footprint()}
        self.assertIn("PR-VQS", ids)
        self.assertIn("PR-CUL", ids)

    def test_every_archetype_is_represented(self):
        for archetype in ("metro", "coastal", "mountain", "remote_island"):
            self.assertTrue(sites_by_archetype(archetype), archetype)

    def test_island_sites_declare_their_embarkation_point(self):
        for site in sites_in_cpe_footprint():
            if site.island:
                self.assertIsNotNone(site.ferry_from, site.site_id)
                self.assertIn(site.ferry_from, SITE_BY_ID)


class TestBasesAreHonestlyLabelled(unittest.TestCase):
    """Operations-centre locations are not public. The model must say so."""

    def test_all_bases_are_flagged_as_assumed(self):
        self.assertEqual(len(assumed_bases()), len(DISPATCH_BASES))

    def test_every_base_sits_on_a_known_site(self):
        for base in DISPATCH_BASES:
            self.assertIn(base.site_id, SITE_BY_ID, base.base_id)

    def test_every_hub_records_a_likelihood_and_rationale(self):
        for base in DISPATCH_BASES:
            self.assertIn(base.likelihood, {"very_high", "high", "assumed"}, base.base_id)
            self.assertTrue(base.rationale, base.base_id)

    def test_basis_names_the_source_as_judgement_not_fact(self):
        for base in DISPATCH_BASES:
            self.assertIn("not a published", base.basis, base.base_id)

    def test_the_practitioner_hub_set_is_the_one_modelled(self):
        expected = {"BASE-BAY", "BASE-CAG", "BASE-PON", "BASE-MAY", "BASE-AGU", "BASE-CAR"}
        self.assertEqual({b.base_id for b in DISPATCH_BASES}, expected)

    def test_four_hubs_are_rated_very_high(self):
        self.assertEqual({b.base_id for b in bases_by_likelihood("very_high")},
                         {"BASE-BAY", "BASE-CAG", "BASE-PON", "BASE-MAY"})

    def test_san_juan_is_a_core_site_not_a_dispatch_hub(self):
        """The public reference is to a core platform site: headend and NOC."""
        self.assertIn(SITE_BY_ID["PR-SJU"], core_sites())
        self.assertNotIn("PR-SJU", {b.site_id for b in DISPATCH_BASES})

    def test_fajardo_is_a_ferry_terminal_not_a_dispatch_hub(self):
        self.assertIn(SITE_BY_ID["PR-FAJ"], ferry_terminals())
        self.assertNotIn("PR-FAJ", {b.site_id for b in DISPATCH_BASES})


class TestDistanceAndTravel(unittest.TestCase):
    def test_haversine_is_symmetric_and_zero_on_identity(self):
        a, b = SITE_BY_ID["PR-SJU"], SITE_BY_ID["PR-MAY"]
        self.assertAlmostEqual(haversine_km(a.lat, a.lon, b.lat, b.lon),
                               haversine_km(b.lat, b.lon, a.lat, a.lon), places=6)
        self.assertAlmostEqual(haversine_km(a.lat, a.lon, a.lat, a.lon), 0.0, places=6)

    def test_san_juan_to_mayaguez_is_roughly_the_real_distance(self):
        a, b = SITE_BY_ID["PR-SJU"], SITE_BY_ID["PR-MAY"]
        km = haversine_km(a.lat, a.lon, b.lat, b.lon)
        self.assertTrue(100 <= km <= 125, f"expected about 110 km, got {km:.1f}")

    def test_island_plan_contains_a_ferry_leg(self):
        plan = travel_plan(BASE_BY_ID["BASE-CAR"], SITE_BY_ID["PR-VQS"])
        self.assertTrue(plan.requires_ferry)
        self.assertEqual([l.kind for l in plan.legs], ["road", "ferry"])

    def test_mainland_plan_has_no_ferry_leg(self):
        plan = travel_plan(BASE_BY_ID["BASE-PON"], SITE_BY_ID["PR-UTU"])
        self.assertFalse(plan.requires_ferry)

    def test_neither_island_is_same_day_feasible(self):
        """With no hub at the terminal, both islands need the drive first.

        This changed in 1.5.0: modelling Fajardo as a terminal rather than a base
        pushed Vieques from marginal to infeasible, which is the constraint the
        remote-island archetype exists to express.
        """
        for sid in ("PR-VQS", "PR-CUL"):
            sel = select_base(SITE_BY_ID[sid], crew_type="dirty")
            self.assertFalse(sel.plan.same_day_feasible, sid)
            self.assertEqual([l.kind for l in sel.plan.legs], ["road", "ferry"], sid)
            self.assertGreater(sel.plan.legs[0].minutes, 0,
                               "the drive to the terminal must be real")

    def test_metro_travel_is_slower_per_km_than_coastal(self):
        """Congestion, not distance, is what makes metro dispatch expensive."""
        bay, gua = SITE_BY_ID["PR-BAY"], SITE_BY_ID["PR-GUY"]
        pon, gum = SITE_BY_ID["PR-PON"], SITE_BY_ID["PR-GUA"]
        metro_km = haversine_km(bay.lat, bay.lon, gua.lat, gua.lon)
        coastal_km = haversine_km(pon.lat, pon.lon, gum.lat, gum.lon)
        metro_min = travel_plan(BASE_BY_ID["BASE-BAY"], gua).total_minutes
        coastal_min = travel_plan(BASE_BY_ID["BASE-PON"], gum).total_minutes
        self.assertGreater(metro_min / metro_km, coastal_min / coastal_km)


class TestBaseSelection(unittest.TestCase):
    def test_nearest_capable_base_is_chosen(self):
        sel = select_base(SITE_BY_ID["PR-UTU"], crew_type="dirty")
        alternatives = [travel_plan(b, SITE_BY_ID["PR-UTU"]).total_minutes
                        for b in DISPATCH_BASES if "dirty" in b.crew_types]
        self.assertEqual(sel.plan.total_minutes, min(alternatives))

    def test_parts_filter_can_override_proximity(self):
        """A nearer hub without a splice kit is not a candidate.

        Aguadilla carries no splice kit in this model, so a fibre splice in the
        north-west is served from Mayaguez instead.
        """
        site = SITE_BY_ID["PR-AGU"]
        near = select_base(site, crew_type="dirty")
        with_kit = select_base(site, crew_type="dirty",
                               required_skills=["fibre_splice"],
                               required_parts=["splice_kit"])
        self.assertEqual(near.base.base_id, "BASE-AGU")
        self.assertEqual(with_kit.base.base_id, "BASE-MAY")
        self.assertGreater(with_kit.plan.total_minutes, near.plan.total_minutes)
        self.assertIn("BASE-AGU", with_kit.rejected_for_parts)

    def test_impossible_skill_rejects_every_base(self):
        with self.assertRaises(LookupError):
            select_base(SITE_BY_ID["PR-BAY"], crew_type="dirty",
                        required_skills=["headend"])

    def test_impossible_requirement_raises_rather_than_guessing(self):
        with self.assertRaises(LookupError):
            select_base(SITE_BY_ID["PR-SJU"], crew_type="dirty",
                        required_skills=["submarine_cable_repair"])

    def test_island_work_is_staged_from_the_nearest_mainland_hub(self):
        for sid in ("PR-VQS", "PR-CUL"):
            sel = select_base(SITE_BY_ID[sid], crew_type="dirty")
            self.assertEqual(sel.base.base_id, "BASE-CAR",
                             "Carolina is the nearest hub to the Fajardo terminal")
            self.assertTrue(sel.plan.requires_ferry)

    def test_selection_reports_how_many_bases_were_considered(self):
        sel = select_base(SITE_BY_ID["PR-PON"], crew_type="dirty")
        self.assertEqual(sel.considered, len(DISPATCH_BASES))


class TestScenariosAreLocated(unittest.TestCase):
    def setUp(self):
        self.fixtures = {p.stem: json.loads(p.read_text())
                         for p in FIXTURES.glob("*.json")}

    def test_every_scenario_has_a_real_site(self):
        for name, d in self.fixtures.items():
            self.assertIn("site_id", d, name)
            self.assertIn(d["site_id"], SITE_BY_ID, name)

    def test_every_scenario_records_its_dirty_boots_base(self):
        for name, d in self.fixtures.items():
            base = d.get("dirty_boots_base")
            self.assertIsNotNone(base, name)
            self.assertIn(base["base_id"], BASE_BY_ID, name)
            self.assertTrue(base["assumed_location"],
                            "a base presented as real would be misleading")
            self.assertIn(base["likelihood"], {"very_high", "high", "assumed"}, name)
            self.assertTrue(base["legs"], name)

    def test_recorded_travel_matches_the_live_model(self):
        """Stops the fixtures drifting away from geography.py."""
        for name, d in self.fixtures.items():
            expected = select_base(SITE_BY_ID[d["site_id"]], crew_type="dirty")
            self.assertEqual(d["dirty_boots_base"]["travel_minutes"],
                             expected.plan.total_minutes, name)

    def test_island_scenarios_are_flagged_for_ferry(self):
        for name, d in self.fixtures.items():
            if SITE_BY_ID[d["site_id"]].island:
                self.assertTrue(d["dirty_boots_base"]["requires_ferry"], name)

    def test_benchmark_cases_are_located(self):
        cases = json.loads(BENCH.read_text())["cases"]
        for case in cases:
            self.assertIn(case.get("site_id"), SITE_BY_ID, case["case_id"])

    def test_benchmark_spans_more_than_one_archetype(self):
        cases = json.loads(BENCH.read_text())["cases"]
        self.assertGreaterEqual(len({c["archetype"] for c in cases}), 3)


class TestGeneratedMap(unittest.TestCase):
    def setUp(self):
        self.svg = MAP_SVG.read_text()
        self.root = ET.fromstring(self.svg)

    def test_map_is_valid_svg(self):
        self.assertTrue(self.root.tag.endswith("svg"))

    def test_map_states_that_hub_locations_are_assumed(self):
        self.assertIn("ASSUMED", self.svg)
        self.assertIn("practitioner assessment", self.svg)

    def test_map_distinguishes_core_site_and_ferry_terminal(self):
        self.assertIn("CORE", self.svg)
        self.assertIn("FERRY", self.svg)
        self.assertIn("not a dispatch hub", self.svg)

    def test_map_declares_itself_schematic(self):
        self.assertIn("Schematic", self.svg)

    def test_map_explains_the_usvi_exclusion(self):
        self.assertIn("Virgin Islands", self.svg)

    def test_every_footprint_site_appears(self):
        for site in sites_in_cpe_footprint():
            self.assertIn(site.municipio, self.svg, site.site_id)

    def test_every_base_appears(self):
        for base in DISPATCH_BASES:
            self.assertIn(base.base_id.replace("BASE-", ""), self.svg, base.base_id)

    def test_map_is_regenerated_from_current_data(self):
        """Fails if SITES or DISPATCH_BASES changed without regenerating."""
        out = __import__("subprocess").run(
            [sys.executable, "scripts/generate_footprint_map.py"],
            cwd=ROOT, capture_output=True, text=True,
            env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"})
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(MAP_SVG.read_text(), self.svg,
                         "regenerate with scripts/generate_footprint_map.py")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestNoDispatchIsFree(unittest.TestCase):
    """A hub sits on its municipio centroid, and so does the site.

    `travel_plan` measured base to centroid, so any fault in a hub's own
    municipio returned exactly 0 km and was billed 0 minutes and no vehicle cost.
    Six of the 23 modelled sites host a hub, so this affected a large share of
    metro volume — and it is why the v1.9.0 benchmark reconciliation put metro at
    0.6x the published band.
    """

    HUB_SITES = ("PR-BAY", "PR-CAR", "PR-CAG", "PR-PON", "PR-MAY", "PR-AGU")

    def test_no_site_reports_zero_one_way_travel(self):
        for site in sites_in_cpe_footprint():
            plan = select_base(site, crew_type="dirty").plan
            self.assertGreater(plan.total_minutes, 0, site.municipio)

    def test_a_hub_serving_its_own_municipio_still_bills_the_floor(self):
        from lpr_cpe_demo.geography import MIN_ONE_WAY_MINUTES
        for site_id in self.HUB_SITES:
            site = SITE_BY_ID[site_id]
            plan = select_base(site, crew_type="dirty").plan
            self.assertGreaterEqual(plan.total_minutes,
                                    MIN_ONE_WAY_MINUTES[site.archetype],
                                    site.municipio)

    def test_the_floor_is_higher_in_metro_than_on_the_coast(self):
        """Congestion, not distance, dominates a short metro journey."""
        from lpr_cpe_demo.geography import MIN_ONE_WAY_MINUTES
        self.assertGreater(MIN_ONE_WAY_MINUTES["metro"],
                           MIN_ONE_WAY_MINUTES["coastal"])

    def test_travel_uses_the_destination_when_one_is_given(self):
        site = SITE_BY_ID["PR-ARE"]
        near = select_base(site, crew_type="dirty",
                           destination=(site.lat, site.lon)).plan.total_minutes
        far = select_base(site, crew_type="dirty",
                          destination=(site.lat + 0.25, site.lon)).plan.total_minutes
        self.assertGreater(far, near)

    def test_the_floor_does_not_mask_a_genuinely_long_journey(self):
        plan = select_base(SITE_BY_ID["PR-UTU"], crew_type="dirty").plan
        self.assertGreater(plan.total_minutes, 40)

    def test_island_road_leg_to_the_terminal_also_clears_the_floor(self):
        for site_id in ("PR-VQS", "PR-CUL"):
            plan = select_base(SITE_BY_ID[site_id], crew_type="dirty").plan
            road = next(leg for leg in plan.legs if leg.kind == "road")
            self.assertGreater(road.minutes, 0, site_id)

    def test_the_applied_floor_is_stated_in_the_leg_description(self):
        """An operator reading the ledger should see why it is 22 minutes."""
        plan = select_base(SITE_BY_ID["PR-BAY"], crew_type="dirty").plan
        self.assertIn("minimum applied", plan.legs[0].description)


class TestGeneratedFaultsPriceTheRealJourney(unittest.TestCase):
    def test_no_generated_fault_has_zero_travel(self):
        from lpr_cpe_demo.fault_generator import generate_faults
        for fault in generate_faults(400, seed=20260817):
            self.assertGreater(fault.travel_minutes, 0, fault.fault_id)

    def test_every_dispatched_fault_bills_travel_and_vehicle_cost(self):
        from lpr_cpe_demo.fault_generator import generate_faults
        for fault in generate_faults(120, seed=515):
            if not fault.truck_rolls:
                continue
            travel = [r for r in fault.ledger_rows if r["step"] == "travel"]
            self.assertTrue(travel, fault.fault_id)
            self.assertGreater(travel[0]["minutes"], 0, fault.fault_id)
            self.assertGreater(travel[0]["cost_usd"], 0.0, fault.fault_id)
