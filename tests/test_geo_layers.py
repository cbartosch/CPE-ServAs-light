"""Tests for the OpenStreetMap layer specification.

Everything here runs on the standard library. It validates the structure and the
coordinates that pydeck or folium will consume, which is the part that can be
wrong silently; it does not launch a browser.

    PYTHONPATH=src python3 -m unittest tests.test_geo_layers -v
"""

from __future__ import annotations

import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpr_cpe_demo.geo_layers import (ARCHETYPE_RGBA, INITIAL_VIEW,  # noqa: E402
                                     OSM_ATTRIBUTION, TILE_URL, dispatch_route,
                                     ferry_arcs, hub_records,
                                     marker_records, site_records, )
from lpr_cpe_demo.geography import (DISPATCH_BASES, SITE_BY_ID,  # noqa: E402
                                    core_sites, ferry_terminals,
                                    sites_in_cpe_footprint)

# Puerto Rico including Vieques and Culebra, with a small margin.
LAT_RANGE = (17.85, 18.60)
LON_RANGE = (-67.40, -65.15)


class TestBasemap(unittest.TestCase):


    def test_attribution_is_defined(self):
        self.assertIn("OpenStreetMap", OSM_ATTRIBUTION)


    def test_initial_view_frames_the_footprint(self):
        self.assertTrue(LAT_RANGE[0] < INITIAL_VIEW["latitude"] < LAT_RANGE[1])
        self.assertTrue(LON_RANGE[0] < INITIAL_VIEW["longitude"] < LON_RANGE[1])


class TestCoordinatesAreOnTheRealMap(unittest.TestCase):
    """A real basemap makes wrong coordinates visible, so bound them."""

    def test_every_site_falls_inside_the_footprint_bounds(self):
        for rec in site_records():
            self.assertTrue(LAT_RANGE[0] <= rec["lat"] <= LAT_RANGE[1], rec["name"])
            self.assertTrue(LON_RANGE[0] <= rec["lon"] <= LON_RANGE[1], rec["name"])

    def test_every_hub_falls_inside_the_footprint_bounds(self):
        for rec in hub_records():
            self.assertTrue(LAT_RANGE[0] <= rec["lat"] <= LAT_RANGE[1], rec["name"])
            self.assertTrue(LON_RANGE[0] <= rec["lon"] <= LON_RANGE[1], rec["name"])

    def test_hub_coordinates_match_their_site(self):
        for base in DISPATCH_BASES:
            site = SITE_BY_ID[base.site_id]
            self.assertAlmostEqual(base.lat, site.lat, places=4, msg=base.base_id)
            self.assertAlmostEqual(base.lon, site.lon, places=4, msg=base.base_id)

    def test_island_sites_sit_east_of_the_mainland(self):
        """Vieques and Culebra are east of Fajardo, which the map must show."""
        fajardo = SITE_BY_ID["PR-FAJ"]
        for sid in ("PR-VQS", "PR-CUL"):
            self.assertGreater(SITE_BY_ID[sid].lon, fajardo.lon, sid)

    def test_west_coast_sites_sit_west_of_san_juan(self):
        sj = SITE_BY_ID["PR-SJU"]
        for sid in ("PR-MAY", "PR-AGU", "PR-CAB"):
            self.assertLess(SITE_BY_ID[sid].lon, sj.lon, sid)

    def test_south_coast_sites_sit_south_of_the_metro(self):
        bay = SITE_BY_ID["PR-BAY"]
        for sid in ("PR-PON", "PR-GUA"):
            self.assertLess(SITE_BY_ID[sid].lat, bay.lat, sid)








class TestRecords(unittest.TestCase):
    def test_site_records_cover_the_footprint_exactly(self):
        self.assertEqual(len(site_records()), len(sites_in_cpe_footprint()))

    def test_usvi_is_absent_from_the_map(self):
        names = {r["name"] for r in site_records()}
        for excluded in ("St Thomas", "St Croix", "St John"):
            self.assertNotIn(excluded, names)

    def test_archetype_colours_are_all_defined(self):
        for rec in site_records():
            self.assertIn(rec["archetype"], ARCHETYPE_RGBA)
            self.assertEqual(len(rec["colour"]), 4)

    def test_very_high_hubs_render_larger(self):
        by_likelihood = {r["likelihood"]: r["radius"] for r in hub_records()}
        self.assertGreater(by_likelihood["very_high"], by_likelihood["high"])

    def test_hub_records_carry_the_provenance_forward(self):
        """The map must not present judgement as a confirmed address."""
        for rec in hub_records():
            self.assertIn("not a published", rec["basis"], rec["name"])
            self.assertTrue(rec["rationale"], rec["name"])

    def test_markers_cover_core_sites_and_terminals(self):
        self.assertEqual(len(marker_records()),
                         len(core_sites()) + len(ferry_terminals()))
        roles = " ".join(r["role"] for r in marker_records())
        self.assertIn("Core site", roles)
        self.assertIn("Ferry terminal", roles)

    def test_ferry_arcs_connect_the_terminal_to_both_islands(self):
        arcs = ferry_arcs()
        self.assertEqual(len(arcs), 2)
        for arc in arcs:
            self.assertAlmostEqual(arc["from_lon"], SITE_BY_ID["PR-FAJ"].lon, places=4)


class TestDispatchRoute(unittest.TestCase):
    def test_mainland_route_is_two_points(self):
        route = dispatch_route(SITE_BY_ID["PR-UTU"])
        self.assertEqual(len(route["path_record"]["path"]), 2)

    def test_island_route_passes_through_the_terminal(self):
        route = dispatch_route(SITE_BY_ID["PR-CUL"])
        path = route["path_record"]["path"]
        self.assertEqual(len(path), 3)
        terminal = SITE_BY_ID["PR-FAJ"]
        self.assertAlmostEqual(path[1][0], terminal.lon, places=4)
        self.assertAlmostEqual(path[1][1], terminal.lat, places=4)

    def test_route_path_uses_lon_lat_order(self):
        """deck.gl expects [lon, lat]. Reversing it silently lands in Somalia."""
        route = dispatch_route(SITE_BY_ID["PR-PON"])
        for lon, lat in route["path_record"]["path"]:
            self.assertTrue(LON_RANGE[0] <= lon <= LON_RANGE[1], f"lon {lon}")
            self.assertTrue(LAT_RANGE[0] <= lat <= LAT_RANGE[1], f"lat {lat}")

    def test_route_label_states_the_travel_time(self):
        route = dispatch_route(SITE_BY_ID["PR-CUL"])
        self.assertIn("min one way", route["path_record"]["label"])

    def test_parts_requirement_changes_the_route_origin(self):
        plain = dispatch_route(SITE_BY_ID["PR-AGU"])
        spliced = dispatch_route(SITE_BY_ID["PR-AGU"],
                                 required_skills=("fibre_splice",),
                                 required_parts=("splice_kit",))
        self.assertNotEqual(plain["path_record"]["path"][0],
                            spliced["path_record"]["path"][0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
