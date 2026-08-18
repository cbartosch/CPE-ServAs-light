"""Tests for the sidebar model-status panel.

It exists because the Control Tower's agent-status block is one page of ten, and
someone on any other page saw numbers with no indication of whether a model
produced them.

    PYTHONPATH=src python3 -m unittest tests.test_sidebar -v
"""
from __future__ import annotations

import ast
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpr_cpe_demo.agents.status import RECORDER, AgentRun  # noqa: E402
from lpr_cpe_demo.ui.sidebar import (PANEL_BG, STATE_COLOUR, STATE_LABEL,  # noqa: E402
                                     contrast_report, failing_checks, html,
                                     panel_state, status_lines)

LIVE = {"ANTHROPIC_API_KEY": "sk-secret-abc123"}
BYPASSED = {"ANTHROPIC_API_KEY": "sk-secret-abc123", "MODEL_PROVIDER": "fake"}


class TestThreeStatesAreDistinguished(unittest.TestCase):
    """A key that is set but overridden is a different situation from no key, and
    the panel has to say which."""

    def test_no_key_is_absent(self):
        self.assertEqual(panel_state({}), "absent")

    def test_a_key_alone_is_active(self):
        self.assertEqual(panel_state(LIVE), "active")

    def test_a_key_with_a_fake_switch_is_bypassed_not_absent(self):
        self.assertEqual(panel_state(BYPASSED), "bypassed")

    def test_each_state_has_its_own_label_and_colour(self):
        self.assertEqual(len(set(STATE_LABEL.values())), 3)
        self.assertEqual(len(set(STATE_COLOUR.values())), 3)

    def test_the_labels_are_unambiguous_at_a_glance(self):
        self.assertEqual(STATE_LABEL["active"], "ACTIVE")
        self.assertEqual(STATE_LABEL["absent"], "NOT ACTIVE")
        self.assertEqual(STATE_LABEL["bypassed"], "BYPASSED")


class TestWhatThePanelSays(unittest.TestCase):
    def test_the_active_model_name_is_shown(self):
        self.assertEqual(status_lines(LIVE)["model"], "claude-sonnet-4-6")

    def test_an_overridden_model_name_is_shown_from_the_environment(self):
        lines = status_lines({"ANTHROPIC_API_KEY": "k",
                              "ANTHROPIC_MODEL": "claude-opus-5"})
        self.assertEqual(lines["model"], "claude-opus-5")

    def test_the_missing_variable_is_named_so_it_can_be_set(self):
        self.assertIn("ANTHROPIC_API_KEY", status_lines({})["detail"])

    def test_a_bypass_names_the_switch_responsible(self):
        detail = status_lines(BYPASSED)["detail"]
        self.assertIn("MODEL_PROVIDER", detail)
        self.assertIn("LLM_PROVIDER", detail)

    def test_the_consequence_is_stated_not_left_to_inference(self):
        self.assertIn("deterministic rules", status_lines({})["consequence"])
        self.assertIn("ASSUMED", status_lines({})["consequence"])

    def test_an_active_model_states_the_authority_arrangement(self):
        self.assertIn("Agents decide", status_lines(LIVE)["consequence"])

    def test_no_activity_reads_as_none_attempted_not_as_healthy(self):
        RECORDER.reset()
        self.assertIn("No decision attempted", status_lines({})["activity"])

    def test_activity_counts_appear_once_decisions_have_run(self):
        RECORDER.reset()
        try:
            RECORDER.record(AgentRun("rca", "anthropic", True))
            RECORDER.record(AgentRun("rca", "deterministic_fallback", False,
                                     "provider down"))
            activity = status_lines(LIVE)["activity"]
            self.assertIn("1 accepted", activity)
            self.assertIn("1 fell back", activity)
            self.assertIn("2 attempted", activity)
        finally:
            RECORDER.reset()


class TestTheKeyIsNeverRendered(unittest.TestCase):
    def test_the_secret_does_not_reach_the_markup(self):
        self.assertNotIn("sk-secret-abc123", html(LIVE))

    def test_the_secret_does_not_reach_the_text_lines(self):
        self.assertNotIn("sk-secret-abc123", str(status_lines(LIVE)))

    def test_only_the_variable_name_is_shown(self):
        self.assertIn("ANTHROPIC_API_KEY", html({}))


class TestReadableUnderBothThemes(unittest.TestCase):
    """The app injects a light theme globally and the Control Tower a dark one on
    top, so the sidebar background differs by page. The panel therefore sets its
    own background and is measured against that."""

    def test_the_panel_sets_its_own_background(self):
        self.assertIn(PANEL_BG, html({}))

    def test_every_tone_clears_wcag_against_the_panel_background(self):
        failures = failing_checks()
        detail = "\n  ".join(f"{c.label}: {c.ratio} < {c.required}"
                             for c in failures)
        self.assertFalse(failures, f"contrast failures:\n  {detail}")

    def test_all_three_indicator_colours_are_checked(self):
        labels = {c.label for c in contrast_report()}
        for state in STATE_COLOUR:
            self.assertIn(f"{state} indicator", labels)

    def test_the_markup_is_well_formed(self):
        import xml.etree.ElementTree as ET
        for env in ({}, LIVE, BYPASSED):
            ET.fromstring(html(env))       # raises on unbalanced markup


class TestWiredIntoEveryPage(unittest.TestCase):
    """A panel only the Control Tower shows would not solve the problem it was
    written for."""

    APP = ROOT / "src/lpr_cpe_demo/ui/app.py"

    def test_the_sidebar_renderer_is_called_from_the_app_shell(self):
        self.assertIn("model_sidebar.render()", self.APP.read_text())

    def test_it_is_called_inside_the_shared_sidebar_block(self):
        """Inside `with st.sidebar` in app.py, so it precedes page dispatch and
        appears regardless of which page renders."""
        text = self.APP.read_text()
        self.assertLess(text.index("model_sidebar.render()"), text.index("pages = {"))
        self.assertGreater(text.index("model_sidebar.render()"),
                           text.index("with st.sidebar:"))

    def test_the_module_does_not_import_streamlit_at_module_scope(self):
        """Kept local so the panel's logic is testable without Streamlit."""
        source = (ROOT / "src/lpr_cpe_demo/ui/sidebar.py").read_text()
        tree = ast.parse(source)
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names]
                self.assertNotIn("streamlit", names + [getattr(node, "module", "")])
