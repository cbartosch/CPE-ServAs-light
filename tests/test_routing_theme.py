"""Tests for road routing and for the readability of the GUI artwork.

    PYTHONPATH=src python3 -m unittest tests.test_routing_theme -v
"""
from __future__ import annotations

import io
import json
import pathlib
import sys
import unittest
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpr_cpe_demo.fault_generator import generate_faults  # noqa: E402
from lpr_cpe_demo.geo_layers import (ferry_leg_records,  # noqa: E402
                                     road_leg_records, routing_summary)
from lpr_cpe_demo.routing import (FallbackRouter, OSRMRouter,  # noqa: E402
                                  StraightLineRouter, router_from_env)
from lpr_cpe_demo.ui import artwork, theme  # noqa: E402

ASSETS = ROOT / "src/lpr_cpe_demo/ui/assets"

CANNED = {
    "code": "Ok",
    "routes": [{
        "distance": 63120.4, "duration": 3180.6,
        "geometry": {"coordinates": [[-66.1614, 18.3985], [-66.2510, 18.4211],
                                     [-66.4822, 18.4297], [-66.6002, 18.4460],
                                     [-66.7156, 18.4725]]},
    }],
}


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _opener(payload=CANNED, record=None):
    def open_url(url, timeout=None):
        if record is not None:
            record.append(url)
        return _Resp(json.dumps(payload).encode())
    return open_url


class TestStraightLineRouter(unittest.TestCase):
    def test_geometry_is_the_waypoints(self):
        route = StraightLineRouter().route([(-66.1, 18.4), (-66.7, 18.5)])
        self.assertEqual(route.path, [[-66.1, 18.4], [-66.7, 18.5]])

    def test_it_does_not_claim_to_be_on_roads(self):
        self.assertFalse(StraightLineRouter().route([(-66.1, 18.4),
                                                     (-66.7, 18.5)]).on_roads)

    def test_a_single_waypoint_is_rejected(self):
        with self.assertRaises(ValueError):
            StraightLineRouter().route([(-66.1, 18.4)])


class TestOSRMRouter(unittest.TestCase):
    def test_request_asks_for_geojson_so_no_polyline_decoding_is_needed(self):
        seen: list[str] = []
        OSRMRouter(opener=_opener(record=seen)).route([(-66.1614, 18.3985),
                                                       (-66.7156, 18.4725)])
        self.assertIn("geometries=geojson", seen[0])
        self.assertIn("overview=full", seen[0])

    def test_coordinates_are_sent_in_lon_lat_order(self):
        seen: list[str] = []
        OSRMRouter(opener=_opener(record=seen)).route([(-66.1614, 18.3985),
                                                      (-66.7156, 18.4725)])
        self.assertIn("-66.161400,18.398500", seen[0])

    def test_geometry_is_the_road_path_not_the_endpoints(self):
        route = OSRMRouter(opener=_opener()).route([(-66.1614, 18.3985),
                                                    (-66.7156, 18.4725)])
        self.assertEqual(len(route.coordinates), 5)
        self.assertTrue(route.on_roads)

    def test_distance_and_duration_come_from_the_engine(self):
        route = OSRMRouter(opener=_opener()).route([(-66.16, 18.40), (-66.72, 18.47)])
        self.assertEqual(route.distance_km, 63.1)
        self.assertEqual(route.duration_min, 53)

    def test_repeated_routes_hit_the_cache_not_the_network(self):
        seen: list[str] = []
        router = OSRMRouter(opener=_opener(record=seen))
        waypoints = [(-66.16, 18.40), (-66.72, 18.47)]
        for _ in range(4):
            router.route(waypoints)
        self.assertEqual(len(seen), 1)

    def test_disk_cache_survives_a_new_router_instance(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            seen: list[str] = []
            waypoints = [(-66.16, 18.40), (-66.72, 18.47)]
            OSRMRouter(opener=_opener(record=seen),
                       cache_dir=pathlib.Path(tmp)).route(waypoints)
            fresh = OSRMRouter(opener=_opener(record=seen),
                              cache_dir=pathlib.Path(tmp))
            route = fresh.route(waypoints)
            self.assertEqual(len(seen), 1, "second instance refetched")
            self.assertEqual(route.source, "osrm-cache")

    def test_malformed_responses_are_rejected_rather_than_half_drawn(self):
        for payload, label in (
            ({"code": "NoRoute", "routes": []}, "NoRoute"),
            ({"code": "Ok", "routes": []}, "no routes"),
            ({"code": "Ok", "routes": [{"geometry": {"coordinates": [[-66, 18]]}}]},
             "one vertex"),
        ):
            with self.assertRaises(ValueError, msg=label):
                OSRMRouter.parse(payload)


class TestFallback(unittest.TestCase):
    class _Broken:
        name = "broken"

        def route(self, waypoints):
            raise OSError("unreachable")

    def test_a_failed_route_degrades_to_a_straight_line(self):
        router = FallbackRouter(primary=self._Broken())
        route = router.route([(-66.1, 18.4), (-66.7, 18.5)])
        self.assertFalse(route.on_roads)
        self.assertEqual(router.failures, 1)

    def test_failures_are_counted_so_the_caption_can_be_honest(self):
        router = FallbackRouter(primary=self._Broken())
        for _ in range(3):
            router.route([(-66.1, 18.4), (-66.7, 18.5)])
        self.assertEqual(router.failures, 3)


class TestRouterSelection(unittest.TestCase):
    def test_default_needs_no_network(self):
        self.assertIsInstance(router_from_env({}), StraightLineRouter)

    def test_osrm_is_wrapped_in_a_fallback(self):
        self.assertIsInstance(router_from_env({"ROUTING_PROVIDER": "osrm"}),
                              FallbackRouter)

    def test_unknown_provider_falls_back_to_straight(self):
        self.assertIsInstance(router_from_env({"ROUTING_PROVIDER": "nonsense"}),
                              StraightLineRouter)


class TestRouteLegs(unittest.TestCase):
    def setUp(self):
        self.faults = generate_faults(400, seed=81)

    def test_ferry_legs_are_never_sent_to_the_router(self):
        """A driving profile asked to cross to Vieques invents a land path."""
        island = [f for f in self.faults if f.requires_ferry and f.truck_rolls]
        self.assertTrue(island, "sample should contain island work")
        legs = road_leg_records(island, OSRMRouter(opener=_opener()))
        for leg in legs:
            self.assertIn("ferry terminal", leg["label"],
                          "an island road leg must stop at the terminal")

    def test_island_crossings_stay_arcs(self):
        island = [f for f in self.faults if f.requires_ferry and f.truck_rolls]
        self.assertEqual(len(ferry_leg_records(island)), len(island))

    def test_router_upgrades_legs_to_real_roads(self):
        plain = routing_summary(road_leg_records(self.faults))
        routed = routing_summary(road_leg_records(self.faults,
                                                 OSRMRouter(opener=_opener())))
        self.assertEqual(plain["on_roads"], 0)
        self.assertEqual(routed["on_roads"], routed["legs"])
        self.assertTrue(routed["all_routed"])

    def test_one_failed_leg_does_not_blank_the_layer(self):
        legs = road_leg_records(self.faults, FallbackRouter(primary=TestFallback._Broken()))
        self.assertEqual(len(legs), routing_summary(legs)["legs"])
        self.assertGreater(len(legs), 0)

    def test_routed_labels_report_distance_and_duration(self):
        legs = road_leg_records(self.faults[:5], OSRMRouter(opener=_opener()))
        routed = [l for l in legs if l["on_roads"]]
        if routed:
            self.assertIn("on roads", routed[0]["label"])


class TestArtworkIsOriginalAndOptional(unittest.TestCase):
    def test_both_svgs_exist_and_are_valid(self):
        for name in ("landmark_band.svg", "landmark_watermark.svg"):
            path = ASSETS / name
            self.assertTrue(path.exists(), name)
            self.assertTrue(ET.fromstring(path.read_text()).tag.endswith("svg"), name)

    SVG_NS = "http://www.w3.org/2000/svg"

    def test_artwork_embeds_no_external_reference(self):
        """No fetched photograph, so no licensing question and no network need.

        The SVG namespace URI is the only permitted http(s) string; anything else
        would mean the artwork depends on something being reachable.
        """
        import re
        for name in ("landmark_band.svg", "landmark_watermark.svg"):
            text = (ASSETS / name).read_text()
            self.assertNotIn("<image", text, name)
            self.assertNotIn("xlink:href", text, name)
            urls = [u for u in re.findall(r"https?://[^\"'\s>]+", text)
                    if u != self.SVG_NS]
            self.assertFalse(urls, f"{name} references {urls}")

    def test_artwork_carries_an_accessible_label(self):
        for name in ("landmark_band.svg", "landmark_watermark.svg"):
            self.assertIn("aria-label", (ASSETS / name).read_text(), name)

    def test_data_uris_are_produced(self):
        self.assertTrue(artwork.band_data_uri().startswith("data:image/svg+xml;base64,"))
        self.assertTrue(artwork.watermark_data_uri().startswith("data:image/svg+xml"))

    def test_artwork_can_be_switched_off(self):
        self.assertTrue(artwork.enabled())
        css = theme.css(header_svg_data_uri="x", watermark_svg_data_uri="y",
                        show_artwork=False)
        self.assertNotIn("stApp::before", css)

    def test_regenerating_the_artwork_is_reproducible(self):
        import subprocess
        before = {n: (ASSETS / n).read_bytes()
                  for n in ("landmark_band.svg", "landmark_watermark.svg")}
        out = subprocess.run([sys.executable, "scripts/generate_landmark_band.py"],
                             cwd=ROOT, capture_output=True, text=True,
                             env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"})
        self.assertEqual(out.returncode, 0, out.stderr)
        for name, data in before.items():
            self.assertEqual((ASSETS / name).read_bytes(), data, name)


class TestReadability(unittest.TestCase):
    """Decoration is how a dashboard becomes unreadable. Measure, do not eyeball."""

    def test_every_text_pairing_clears_wcag_aa(self):
        failures = theme.failing_checks()
        detail = "\n  ".join(f"{c.label}: {c.ratio} < {c.required}" for c in failures)
        self.assertFalse(failures, f"contrast failures:\n  {detail}")

    def test_the_report_covers_the_composited_backgrounds_not_just_clean_surfaces(self):
        labels = {c.label for c in theme.contrast_report()}
        self.assertIn("body over watermark", labels)
        self.assertIn("heading over header artwork", labels)

    def test_known_contrast_maths_is_correct(self):
        self.assertEqual(theme.contrast_ratio("#000000", "#FFFFFF"), 21.0)
        self.assertEqual(theme.contrast_ratio("#FFFFFF", "#FFFFFF"), 1.0)

    def test_compositing_moves_the_background_towards_the_overlay(self):
        mixed = theme.composite("#000000", "#FFFFFF", 0.5)
        self.assertEqual(mixed, "#808080")

    def test_artwork_opacity_is_capped(self):
        self.assertLessEqual(theme.HEADER_ARTWORK_OPACITY, theme.MAX_ARTWORK_OPACITY)
        self.assertLessEqual(theme.WATERMARK_OPACITY, theme.MAX_ARTWORK_OPACITY)

    def test_raising_the_opacity_past_the_cap_would_break_contrast(self):
        """Shows the cap is doing work rather than being decorative."""
        heavy = theme.composite(theme.ARTWORK_INK, theme.SURFACE, 0.55)
        self.assertLess(theme.contrast_ratio(theme.INK_MUTED, heavy),
                        theme.WCAG_AA_BODY)

    def test_data_surfaces_are_forced_opaque(self):
        css = theme.css(header_svg_data_uri="x", watermark_svg_data_uri="y")
        for selector in ("stDataFrame", "stMetric", "stExpander"):
            self.assertIn(selector, css)
        self.assertIn("!important", css)

    def test_content_sits_above_the_watermark(self):
        css = theme.css(header_svg_data_uri="x", watermark_svg_data_uri="y")
        self.assertIn("z-index: 1", css)
        self.assertIn("pointer-events: none", css)
