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
                                    assumed_bases, haversine_km, select_base,
                                    sites_by_archetype, sites_in_cpe_footprint,
                                    travel_plan)

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

    def test_san_juan_base_records_its_only_external_anchor(self):
        self.assertIn("core platform site", BASE_BY_ID["BASE-SJU"].notes)

    def test_fajardo_base_documents_the_island_staging_role(self):
        self.assertIn("Vieques", BASE_BY_ID["BASE-FAJ"].notes)


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
        plan = travel_plan(BASE_BY_ID["BASE-FAJ"], SITE_BY_ID["PR-VQS"])
        self.assertTrue(plan.requires_ferry)
        self.assertEqual([l.kind for l in plan.legs], ["road", "ferry"])

    def test_mainland_plan_has_no_ferry_leg(self):
        plan = travel_plan(BASE_BY_ID["BASE-ARE"], SITE_BY_ID["PR-UTU"])
        self.assertFalse(plan.requires_ferry)

    def test_culebra_is_not_same_day_feasible(self):
        """The constraint the remote-island archetype exists to express."""
        plan = travel_plan(BASE_BY_ID["BASE-FAJ"], SITE_BY_ID["PR-CUL"])
        self.assertFalse(plan.same_day_feasible)
        self.assertGreater(plan.total_minutes, FERRY_MINUTES["VIEQUES"])

    def test_metro_travel_is_slower_per_km_than_coastal(self):
        """Congestion, not distance, is what makes metro dispatch expensive."""
        sj, bay = SITE_BY_ID["PR-SJU"], SITE_BY_ID["PR-BAY"]
        are, man = SITE_BY_ID["PR-ARE"], SITE_BY_ID["PR-MAN"]
        metro_km = haversine_km(sj.lat, sj.lon, bay.lat, bay.lon)
        coastal_km = haversine_km(are.lat, are.lon, man.lat, man.lon)
        metro_min = travel_plan(BASE_BY_ID["BASE-SJU"], bay).total_minutes
        coastal_min = travel_plan(BASE_BY_ID["BASE-ARE"], man).total_minutes
        self.assertGreater(metro_min / metro_km, coastal_min / coastal_km)


class TestBaseSelection(unittest.TestCase):
    def test_nearest_capable_base_is_chosen(self):
        sel = select_base(SITE_BY_ID["PR-UTU"], crew_type="dirty")
        alternatives = [travel_plan(b, SITE_BY_ID["PR-UTU"]).total_minutes
                        for b in DISPATCH_BASES if "dirty" in b.crew_types]
        self.assertEqual(sel.plan.total_minutes, min(alternatives))

    def test_parts_filter_beats_proximity(self):
        """A nearer base without a splice kit is not a candidate."""
        site = SITE_BY_ID["PR-MAR"]
        near = select_base(site, crew_type="dirty")
        with_kit = select_base(site, crew_type="dirty",
                               required_skills=["fibre_splice"],
                               required_parts=["splice_kit"])
        self.assertGreater(with_kit.plan.total_minutes, near.plan.total_minutes)
        self.assertTrue(with_kit.rejected_for_parts)

    def test_missing_skill_rejects_a_base(self):
        sel = select_base(SITE_BY_ID["PR-SJU"], crew_type="dirty",
                          required_skills=["headend"])
        self.assertEqual(sel.base.base_id, "BASE-SJU")
        self.assertTrue(sel.rejected_for_skills)

    def test_impossible_requirement_raises_rather_than_guessing(self):
        with self.assertRaises(LookupError):
            select_base(SITE_BY_ID["PR-SJU"], crew_type="dirty",
                        required_skills=["submarine_cable_repair"])

    def test_island_work_is_staged_from_fajardo(self):
        for sid in ("PR-VQS", "PR-CUL"):
            sel = select_base(SITE_BY_ID[sid], crew_type="dirty")
            self.assertEqual(sel.base.base_id, "BASE-FAJ")
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

    def test_map_states_that_bases_are_assumed(self):
        self.assertIn("ASSUMED", self.svg)

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
