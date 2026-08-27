"""Tests for the control-tower dashboard spec and dark theme.

    PYTHONPATH=src python3 -m unittest tests.test_dashboard -v
"""
from __future__ import annotations

import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpr_cpe_demo.dashboard import (  # noqa: E402
    BUCKET_COLOUR,
    DOMAIN_TO_BUCKET,
    THEME,
    build,
)
from lpr_cpe_demo.ui import theme_dark as td  # noqa: E402

TEMPLATE_AREAS = {"Jumeirah", "Business Bay", "DIFC", "Marina", "Palm"}


class TestFormatIsHonoured(unittest.TestCase):
    def setUp(self):
        self.dash = build(count=60, seed=20260817)

    def test_theme_matches_the_supplied_palette(self):
        self.assertEqual(THEME["background_gradient"],
                         "from-slate-950 via-slate-900 to-indigo-950")
        self.assertEqual(THEME["card"], "bg-white/8 border-white/10")
        for name in ("cyan", "blue", "violet", "amber", "red", "green"):
            self.assertIn(name, THEME["colors"])

    def test_the_supplied_block_structure_is_present(self):
        keys = {b.key for b in self.dash.blocks}
        for expected in ("kpis", "incident_root_cause_mix", "automation_funnel",
                         "hotspots", "closed_loop_confidence",
                         "service_health_by_layer", "playbook_backlog"):
            self.assertIn(expected, keys, expected)

    def test_hero_carries_title_subtitle_and_badges(self):
        self.assertTrue(self.dash.title)
        self.assertTrue(self.dash.subtitle)
        self.assertGreaterEqual(len(self.dash.badges), 3)

    def test_spec_serialises_to_json(self):
        json.dumps(self.dash.to_dict())


class TestProvenanceIsExplicit(unittest.TestCase):
    """The template mixed computed, assumed and invented figures silently."""

    def setUp(self):
        self.dash = build(count=60, seed=20260817)

    def test_every_block_declares_a_provenance(self):
        for block in self.dash.blocks:
            self.assertIn(block.provenance, {"computed", "assumed", "synthetic"},
                          block.key)

    def test_every_block_explains_itself(self):
        for block in self.dash.blocks:
            self.assertGreater(len(block.note), 40, block.key)

    def test_all_three_provenance_classes_are_represented(self):
        counts = self.dash.provenance_counts()
        for kind in ("computed", "assumed", "synthetic"):
            self.assertGreater(counts.get(kind, 0), 0, kind)

    def test_service_health_is_labelled_synthetic_not_computed(self):
        block = self.dash.block("service_health_by_layer")
        self.assertEqual(block.provenance, "synthetic")
        self.assertIn("SHAPE ONLY", block.note)

    def test_the_funnel_marks_which_single_stage_is_real(self):
        rows = self.dash.block("automation_funnel").data
        computed = [r for r in rows if r["source"] == "computed"]
        self.assertEqual(len(computed), 1)
        self.assertEqual(computed[0]["stage"], "Diagnose")

    def test_closed_loop_scores_name_the_control_behind_them(self):
        for guard in self.dash.block("closed_loop_confidence").data["guardrails"]:
            self.assertTrue(guard["basis"], guard["name"])

    def test_unimplemented_controls_score_low_rather_than_flattering(self):
        guards = {g["name"]: g for g
                  in self.dash.block("closed_loop_confidence").data["guardrails"]}
        self.assertLess(guards["Rollback safe"]["score_pct"], 60)
        self.assertIn("no rollback", guards["Rollback safe"]["basis"])


class TestDeparturesFromTheTemplate(unittest.TestCase):
    def setUp(self):
        self.dash = build(count=120, seed=20260817)

    def test_areas_are_puerto_rico_not_dubai(self):
        areas = {h["area"] for h in self.dash.block("hotspots").data}
        self.assertFalse(areas & TEMPLATE_AREAS, f"template areas leaked: {areas}")

    def test_every_hotspot_has_a_real_dispatch_hub_behind_it(self):
        for hot in self.dash.block("hotspots").data:
            self.assertTrue(hot["recommended_orchestration"])
            self.assertTrue(hot["id"])

    def test_truck_roll_avoidance_is_a_range_not_a_point(self):
        """The template asserted 128. Two rounds of analysis made it a range."""
        kpi = next(k for k in self.dash.block("kpis").data
                   if "avoidable" in k["label"])
        self.assertIn("\u2013", kpi["value"], "must be expressed as a range")
        self.assertIn("/ 1k", kpi["value"], "must state the denominator")
        self.assertIn("neither of which is measured", kpi["description"])

    def test_severity_follows_blast_radius(self):
        rows = self.dash.block("hotspots").data
        critical = [r for r in rows if r["severity"] == "Critical"]
        for row in critical:
            self.assertGreaterEqual(row["subscribers_impacted"], 100)

    def test_hotspots_are_ranked_by_households_affected(self):
        counts = [h["subscribers_impacted"] for h in self.dash.block("hotspots").data]
        self.assertEqual(counts, sorted(counts, reverse=True))


class TestComputedBlocksAreActuallyComputed(unittest.TestCase):
    def test_root_cause_mix_sums_to_a_hundred(self):
        data = build(count=60).block("incident_root_cause_mix").data
        self.assertAlmostEqual(sum(d["value"] for d in data), 100.0, delta=0.5)

    def test_root_cause_mix_covers_every_bucket(self):
        data = build(count=60).block("incident_root_cause_mix").data
        self.assertEqual({d["name"] for d in data}, set(BUCKET_COLOUR))

    def test_every_domain_maps_to_a_known_bucket(self):
        for bucket in DOMAIN_TO_BUCKET.values():
            self.assertIn(bucket, BUCKET_COLOUR, bucket)

    def test_the_same_seed_reproduces_the_dashboard(self):
        a, b = build(count=80, seed=7), build(count=80, seed=7)
        self.assertEqual(json.dumps(a.to_dict()), json.dumps(b.to_dict()))

    def test_a_different_seed_changes_the_hotspots(self):
        a = build(count=80, seed=7).block("hotspots").data
        b = build(count=80, seed=8).block("hotspots").data
        self.assertNotEqual([h["id"] for h in a], [h["id"] for h in b])

    def test_kpi_counts_agree_with_the_incident_set(self):
        dash = build(count=90, seed=11)
        kpi = next(k for k in dash.block("kpis").data
                   if k["label"] == "Incidents in scope")
        self.assertEqual(kpi["value"], "90")

    def test_island_archetype_shows_the_highest_wasted_visit_cost(self):
        rows = build(count=900, seed=13).block("cost_by_archetype").data
        by_arch = {r["archetype"]: r for r in rows}
        island = by_arch.get("remote island")
        metro = by_arch.get("metro")
        if island and metro and island["dispatched"] and metro["dispatched"]:
            self.assertGreater(island["mean_wasted_visit"],
                               metro["mean_wasted_visit"])

    def test_wasted_visit_is_none_rather_than_zero_when_nothing_dispatched(self):
        """Zero would read as free; None reads as no observation."""
        for row in build(count=900, seed=13).block("cost_by_archetype").data:
            if row["dispatched"] == 0:
                self.assertIsNone(row["mean_wasted_visit"], row["archetype"])
            else:
                self.assertGreater(row["mean_wasted_visit"], 0)


class TestDarkThemeReadability(unittest.TestCase):
    """Neon on dark is easy to get wrong. Measure it."""

    def test_every_pairing_clears_wcag(self):
        failures = td.failing_checks()
        detail = "\n  ".join(f"{c.label}: {c.ratio} < {c.required}" for c in failures)
        self.assertFalse(failures, f"contrast failures:\n  {detail}")

    def test_glass_card_composite_is_what_gets_measured(self):
        self.assertEqual(td.CARD, "#222A3B")

    def test_every_accent_is_body_legible_on_the_card(self):
        for name, value in td.ACCENTS.items():
            self.assertGreaterEqual(td.contrast_ratio(value, td.CARD),
                                    td.WCAG_AA_BODY, name)

    def test_the_large_only_tone_is_not_offered_as_body_copy(self):
        """slate-500 reaches 3.02 on the card, so MUTED must be lighter."""
        self.assertLess(td.contrast_ratio(td.LARGE_ONLY, td.CARD), td.WCAG_AA_BODY)
        self.assertGreaterEqual(td.contrast_ratio(td.MUTED, td.CARD),
                                td.WCAG_AA_BODY)

    def test_chart_colours_are_visible_against_the_plot(self):
        for name, value in td.ACCENTS.items():
            self.assertGreaterEqual(td.contrast_ratio(value, td.SLATE_900),
                                    td.WCAG_AA_LARGE, name)

    def test_tables_are_forced_opaque_over_the_gradient(self):
        css = td.css()
        self.assertIn("stDataFrame", css)
        self.assertIn("rgba(15,23,42,0.92) !important", css)

    def test_provenance_chips_use_distinct_accents(self):
        chips = set(td.PROVENANCE_ACCENT.values())
        self.assertEqual(len(chips), 3)

    def test_legacy_page_background_is_neutral_dark_grey(self):
        for tone in (td.LEGACY_GREY_950, td.LEGACY_GREY_900, td.LEGACY_GREY_800):
            channels = [int(tone[index:index + 2], 16) for index in (1, 3, 5)]
            self.assertEqual(len(set(channels)), 1, tone)
            self.assertLess(channels[0], 64, tone)

    def test_dark_grey_background_overrides_the_global_light_theme(self):
        css = td.css()
        self.assertIn('[data-testid="stAppViewContainer"]', css)
        self.assertIn('[data-testid="stMain"]', css)
        self.assertIn(td.LEGACY_GREY_950, css)
        self.assertIn(td.LEGACY_GREY_900, css)
        self.assertIn(td.LEGACY_GREY_800, css)
        self.assertIn('100%) !important', css)
        self.assertIn('background-attachment: fixed !important', css)

    def test_legacy_control_tower_links_to_predictive_and_care(self):
        html = td.executive_crosslink()
        self.assertIn('href="digital-twin?view=predictive"', html)
        self.assertIn('href="digital-twin?view=customer-care"', html)
        self.assertIn('href="digital-twin?view=dalli"', html)
        self.assertIn('href="digital-twin?view=external-evidence"', html)
        self.assertEqual(html.count('target="_self"'), 5)

    def test_all_analytical_panels_use_the_uniform_medium_grey_surface(self):
        from lpr_cpe_demo.digital_twin import executive_style

        executive_css = executive_style.css()
        legacy_css = td.css()
        self.assertEqual(td.PANEL_GREY, "#4B5057")
        self.assertIn("--lpr-panel: #4B5057", executive_css)
        self.assertIn("--lpr-panel-radius: 14px", executive_css)
        self.assertIn(f"background: {td.PANEL_GREY} !important", legacy_css)
        self.assertGreaterEqual(
            td.contrast_ratio("#F5F7FA", td.PANEL_GREY),
            td.WCAG_AA_BODY,
        )
        self.assertGreaterEqual(
            td.contrast_ratio("#D7DCE2", td.PANEL_GREY),
            td.WCAG_AA_BODY,
        )

    def test_plotly_layout_is_transparent_so_the_gradient_shows(self):
        layout = td.plotly_layout()
        self.assertEqual(layout["paper_bgcolor"], "rgba(0,0,0,0)")
        self.assertEqual(layout["plot_bgcolor"], "rgba(0,0,0,0)")
        self.assertEqual(layout["font"]["color"], td.INK)


class TestEveryCaveatIsMachineDetectable(unittest.TestCase):
    """A caveat a scanner cannot find is a caveat a reviewer can lose.

    Two blocks previously said "stated positions" and "illustrative", which are
    honest but invisible to a keyword check. A test that cannot enforce the rule
    is not enforcing it.
    """

    KEYWORDS = ("assumed", "synthetic", "shape only", "illustrative",
                "not measurements", "not lpr")

    def test_no_non_computed_block_hides_its_status(self):
        offenders = []
        for block in build(count=30).blocks:
            if block.provenance == "computed":
                continue
            if not any(k in block.note.lower() for k in self.KEYWORDS):
                offenders.append(f"{block.key} ({block.provenance})")
        self.assertFalse(offenders,
                         f"non-computed blocks with no detectable caveat: {offenders}")

    def test_the_synthetic_block_shouts_it(self):
        note = build(count=30).block("service_health_by_layer").note
        self.assertIn("SHAPE ONLY", note)
