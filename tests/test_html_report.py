"""Tests for the standalone drill-down HTML control tower.

The file must open from a USB stick with no network. A CDN script tag is the normal
way to get charts and is exactly what fails on a restricted network, so
self-containment is asserted rather than assumed.

    PYTHONPATH=src python3 -m unittest tests.test_html_report -v
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpr_cpe_demo.html_charts import (bar_row, donut, grouped_bars,  # noqa: E402
                                      lines, stacked_bars, table)

HTML = ROOT / "docs" / "control_tower.html"
SVG_NS = "http://www.w3.org/2000/svg"


def _payload(text: str) -> dict:
    match = re.search(r'<script id="ct-data" type="application/json">(.*?)</script>',
                      text, re.S)
    assert match, "embedded payload not found"
    return json.loads(match.group(1))


class TestCharts(unittest.TestCase):
    def test_every_chart_is_valid_svg(self):
        charts = {
            "donut": donut([{"name": f"S{i}", "value": 20} for i in range(5)]),
            "donut_single": donut([{"name": "only", "value": 100}]),
            "stacked": stacked_bars([{"stage": "A", "autonomous_pct": 70,
                                      "human_pct": 30}]),
            "grouped": grouped_bars(["a", "b"],
                                    [{"name": "x", "values": [1, 2]}]),
            "lines": lines(["a", "b"], [{"name": "y", "values": [1, 2]}], y_max=2),
            "meter": bar_row(4, maximum=10),
        }
        for name, svg in charts.items():
            self.assertTrue(ET.fromstring(svg).tag.endswith("svg"), name)

    def test_a_single_full_slice_renders_as_a_ring_not_a_broken_arc(self):
        """An arc path cannot express 360 degrees."""
        svg = donut([{"name": "all", "value": 100}])
        self.assertIn("<circle", svg)

    def test_a_zero_slice_is_skipped_rather_than_drawn(self):
        svg = donut([{"name": "none", "value": 0}, {"name": "all", "value": 100}])
        self.assertEqual(svg.count("<path"), 1)

    def test_none_values_render_as_no_observation(self):
        svg = stacked_bars([{"stage": "Detect", "autonomous_pct": None,
                            "human_pct": None}])
        self.assertIn("no observation", svg)

    def test_grouped_bars_skip_none_without_shifting_the_axis(self):
        svg = grouped_bars(["a"], [{"name": "x", "values": [None]}])
        self.assertTrue(ET.fromstring(svg).tag.endswith("svg"))

    def test_nothing_is_drawn_outside_the_viewbox(self):
        for svg in (donut([{"name": f"Long label {i}", "value": 16.6}
                           for i in range(6)]),
                    stacked_bars([{"stage": f"S{i}", "autonomous_pct": 50,
                                   "human_pct": 50} for i in range(6)]),
                    grouped_bars(["a", "b", "c", "d"],
                                 [{"name": "x", "values": [1, 2, 3, 4]}])):
            box = [float(v) for v in
                   re.search(r'viewBox="([^"]+)"', svg).group(1).split()]
            for match in re.finditer(
                    r'<(?:rect|text|circle)[^>]*?(?:x|cx)="(-?[\d.]+)"'
                    r'[^>]*?(?:y|cy)="(-?[\d.]+)"', svg):
                x, y = float(match.group(1)), float(match.group(2))
                self.assertTrue(-2 <= x <= box[2] + 2, f"x {x}")
                self.assertTrue(-2 <= y <= box[3] + 2, f"y {y}")

    def test_labels_are_escaped(self):
        self.assertNotIn("<script>",
                         donut([{"name": "<script>alert(1)</script>", "value": 100}]))

    def test_table_cells_are_escaped_but_inline_svg_passes_through(self):
        self.assertNotIn("<img", table(["a"], [["<img onerror=x>"]]))
        self.assertIn("<svg", table(["a"], [[bar_row(1, maximum=2)]]))


class TestGeneratedPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = subprocess.run(
            [sys.executable, "scripts/generate_control_tower_html.py",
             "--count", "40", "--seed", "4242", "--out", "/tmp/ct_test.html"],
            cwd=ROOT, capture_output=True, text=True,
            env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"})
        assert out.returncode == 0, out.stderr
        cls.text = pathlib.Path("/tmp/ct_test.html").read_text(encoding="utf-8")
        cls.data = _payload(cls.text)

    def test_it_generates_and_declares_a_doctype(self):
        self.assertTrue(self.text.startswith("<!DOCTYPE html>"))

    def test_nothing_loads_from_a_network(self):
        """The whole point: it must work from a USB stick."""
        refs = re.findall(
            r'<(?:script|link|img|iframe|source)\b[^>]*?(?:src|href)\s*=\s*'
            r'["\']([^"\']+)', self.text)
        external = [u for u in refs if u.startswith(("http://", "https://", "//"))]
        self.assertFalse(external, f"external resources: {external}")
        self.assertNotIn("@import", self.text)
        self.assertNotIn("fonts.googleapis", self.text)
        self.assertNotIn("@font-face", self.text)

    def test_the_payload_is_valid_json(self):
        self.assertIn("panels", self.data)
        self.assertIn("incidents", self.data)

    def test_every_panel_carries_a_provenance_chip(self):
        for panel in self.data["panels"]:
            self.assertIn(panel["provenance"],
                          {"computed", "assumed", "synthetic"}, panel["key"])
            self.assertTrue(panel["note"], panel["key"])

    def test_provenance_survives_the_drill_into_an_incident(self):
        """A number that loses its caveat on the way down is worse than none."""
        for body in self.data["incidents"].values():
            self.assertIn("prov computed", body["body"])
            self.assertIn("assumed", body["body"].lower())

    def test_the_synthetic_panel_still_shouts_at_drill_level(self):
        panel = next(p for p in self.data["panels"]
                     if p["key"] == "service_health_by_layer")
        self.assertEqual(panel["provenance"], "synthetic")
        self.assertIn("SHAPE ONLY", panel["note"])

    def test_every_hotspot_row_drills_to_a_real_incident(self):
        hotspots = next(p for p in self.data["panels"] if p["key"] == "hotspots")
        targets = re.findall(r'data-incident="([^"]*)"', hotspots["table"])
        self.assertTrue(targets, "no drill targets on the hotspot table")
        for target in targets:
            self.assertTrue(target, "a hotspot row has an empty drill target")
            self.assertIn(target, self.data["incidents"],
                          f"{target} drills nowhere")

    def test_panels_that_have_a_contract_expose_its_requirements(self):
        with_reqs = [p for p in self.data["panels"] if p["requirements"]]
        self.assertGreaterEqual(len(with_reqs), 5)
        self.assertIn("source system", with_reqs[0]["requirements"])

    def test_the_contract_level_lists_every_field(self):
        from lpr_cpe_demo.telemetry import contract_summary
        expected = contract_summary()["fields"]
        rows = self.data["contract"].count("<tr") - 1   # minus the header row
        self.assertEqual(rows, expected)

    def test_the_footer_records_the_seed_so_the_file_reproduces(self):
        self.assertIn("4242", self.data["foot"])
        self.assertIn("No external requests", self.data["foot"])

    def test_the_same_seed_reproduces_the_page_byte_for_byte_apart_from_the_clock(self):
        second = subprocess.run(
            [sys.executable, "scripts/generate_control_tower_html.py",
             "--count", "40", "--seed", "4242", "--out", "/tmp/ct_test2.html"],
            cwd=ROOT, capture_output=True, text=True,
            env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"})
        self.assertEqual(second.returncode, 0, second.stderr)
        other = pathlib.Path("/tmp/ct_test2.html").read_text(encoding="utf-8")
        strip = lambda t: re.sub(r"Generated [^ ]+ [^ ]+ UTC", "", t)
        self.assertEqual(strip(self.text), strip(other))

    def test_hash_routing_covers_all_three_drill_levels(self):
        for route in ("panel", "incident"):
            self.assertIn(route, self.text)
        self.assertIn("hashchange", self.text)
        self.assertIn("__contract__", self.text)

    def test_drill_rows_are_keyboard_reachable(self):
        hotspots = next(p for p in self.data["panels"] if p["key"] == "hotspots")
        self.assertIn('tabindex="0"', hotspots["table"])
        self.assertIn('role="link"', hotspots["table"])
        self.assertIn("keydown", self.text)

    def test_the_committed_page_is_current(self):
        """Fails if the model changed and the page was not regenerated."""
        self.assertTrue(HTML.exists(), "docs/control_tower.html is missing")
        out = subprocess.run(
            [sys.executable, "scripts/generate_control_tower_html.py",
             "--out", "/tmp/ct_current.html"],
            cwd=ROOT, capture_output=True, text=True,
            env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"})
        self.assertEqual(out.returncode, 0, out.stderr)
        strip = lambda t: re.sub(r"Generated [^ ]+ [^ ]+ UTC", "", t)
        self.assertEqual(strip(HTML.read_text(encoding="utf-8")),
                         strip(pathlib.Path("/tmp/ct_current.html").read_text(encoding="utf-8")),
                         "regenerate with scripts/generate_control_tower_html.py")
