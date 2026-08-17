"""Static validation of Streamlit widget bounds.

Motivated by a real failure: `st.number_input("Seed", min_value=0,
max_value=10_000_000, value=20260817)` raised StreamlitValueAboveMaxError at
render time, because the date-shaped default exceeded the bound I had set two
lines earlier.

That class of mistake is invisible to `compileall` and only surfaces when a human
opens the page. AST inspection catches it in a second, with no Streamlit
installed.

    PYTHONPATH=src python3 -m unittest tests.test_ui_widgets -v
"""
from __future__ import annotations

import ast
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
UI = ROOT / "src/lpr_cpe_demo/ui"

BOUNDED_WIDGETS = {"number_input", "slider", "select_slider"}


def _literal(node: ast.AST | None) -> float | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) \
            and isinstance(node.operand, ast.Constant):
        return -float(node.operand.value)
    return None


class Widget:
    def __init__(self, path: pathlib.Path, node: ast.Call, name: str):
        self.path = path
        self.line = node.lineno
        self.name = name
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        self.min = _literal(kw.get("min_value"))
        self.max = _literal(kw.get("max_value"))
        self.value = _literal(kw.get("value"))
        self.step = _literal(kw.get("step"))
        # positional slider form: st.slider(label, min, max, default)
        if name == "slider" and self.min is None and len(node.args) >= 4:
            consts = [_literal(a) for a in node.args[1:4]]
            if all(c is not None for c in consts):
                self.min, self.max, self.value = consts  # type: ignore[assignment]
        self.label = (node.args[0].value
                      if node.args and isinstance(node.args[0], ast.Constant)
                      else "<dynamic>")

    def __repr__(self) -> str:
        return (f"{self.path.name}:{self.line} {self.name}({self.label!r} "
                f"min={self.min} max={self.max} value={self.value})")


def collect() -> list[Widget]:
    widgets = []
    for path in sorted(UI.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", None)
                if name in BOUNDED_WIDGETS:
                    widgets.append(Widget(path, node, name))
    return widgets


class TestWidgetBounds(unittest.TestCase):
    def setUp(self):
        self.widgets = collect()

    def test_at_least_one_bounded_widget_is_found(self):
        """Guards the collector itself: a silent zero would pass everything."""
        self.assertTrue(self.widgets, "no bounded widgets found; collector is broken")

    def test_min_is_not_above_max(self):
        for w in self.widgets:
            if None not in (w.min, w.max):
                self.assertLessEqual(w.min, w.max, repr(w))

    def test_default_value_is_not_below_min(self):
        for w in self.widgets:
            if None not in (w.min, w.value):
                self.assertGreaterEqual(w.value, w.min, repr(w))

    def test_default_value_is_not_above_max(self):
        """The exact failure this file exists for."""
        for w in self.widgets:
            if None not in (w.max, w.value):
                self.assertLessEqual(w.value, w.max, repr(w))

    def test_step_fits_inside_the_range(self):
        for w in self.widgets:
            if None not in (w.min, w.max, w.step):
                self.assertLessEqual(w.step, w.max - w.min, repr(w))

    def test_seed_accepts_a_date_shaped_default(self):
        """20260817 is a natural seed to type. The bound must allow it."""
        seeds = [w for w in self.widgets if str(w.label).lower() == "seed"]
        self.assertTrue(seeds, "the simulator should expose a seed input")
        for w in seeds:
            self.assertIsNotNone(w.max)
            self.assertGreaterEqual(w.max, 20_260_817, repr(w))

    def test_seed_bound_is_within_what_random_accepts(self):
        for w in (x for x in self.widgets if str(x.label).lower() == "seed"):
            import random
            random.Random(int(w.max))          # must not raise
            self.assertLessEqual(w.max, 2 ** 63 - 1, repr(w))


class TestPageStructure(unittest.TestCase):
    def test_every_page_exposes_render(self):
        for path in sorted((UI / "pages").glob("*.py")):
            if path.name == "__init__.py":
                continue
            tree = ast.parse(path.read_text())
            names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
            self.assertIn("render", names, f"{path.name} has no render()")

    def test_every_page_module_is_registered_in_the_app(self):
        app = (UI / "app.py").read_text()
        for path in sorted((UI / "pages").glob("*.py")):
            if path.name == "__init__.py":
                continue
            self.assertIn(path.stem, app, f"{path.stem} is not registered in app.py")


class TestNoUnsupportedPydeckApi(unittest.TestCase):
    """`pdk.Deck.from_json` does not exist in the installed pydeck.

    Using it produced `type object 'Deck' has no attribute 'from_json'` at render
    time and silently dropped the page to the offline schematic.
    """

    def test_from_json_is_not_called_anywhere(self):
        for path in sorted(UI.rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Attribute) and node.attr == "from_json":
                    self.fail(f"{path.name}:{node.lineno} calls from_json, "
                              f"which the installed pydeck does not provide")


class TestDollarSignsAreEscapedForMarkdown(unittest.TestCase):
    """Streamlit renders markdown, and markdown reads `$...$` as inline LaTeX.

    Two bare dollar signs in one string silently swallow the currency symbols and
    typeset the text between them as maths. That is what turned the benchmark
    citation into "Headline range 150 to 300".
    """

    MARKDOWN_CALLS = {"write", "markdown", "info", "warning", "error", "success",
                      "caption", "subheader", "title"}

    def _string_parts(self, node: ast.AST) -> list[str]:
        parts = []
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                parts.append(sub.value)
        return parts

    def test_no_bare_dollar_in_markdown_arguments(self):
        offenders = []
        for path in sorted(UI.rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text())):
                if not isinstance(node, ast.Call):
                    continue
                if getattr(node.func, "attr", None) not in self.MARKDOWN_CALLS:
                    continue
                for text in self._string_parts(node):
                    idx = 0
                    while (idx := text.find("$", idx)) != -1:
                        if idx == 0 or text[idx - 1] != "\\":
                            offenders.append(f"{path.name}:{node.lineno} {text[:60]!r}")
                            break
                        idx += 1
        self.assertFalse(offenders,
                         "bare $ in a markdown context is parsed as LaTeX; use "
                         "ui.fmt.usd(). Offenders:\n  " + "\n  ".join(offenders))

    def test_usd_helper_escapes_and_plain_helper_does_not(self):
        from lpr_cpe_demo.ui.fmt import usd, usd_plain
        self.assertEqual(usd(1234), "\\$1,234")
        self.assertEqual(usd(19.67, decimals=2), "\\$19.67")
        self.assertEqual(usd_plain(1234), "$1,234")


class _StubLayer:
    """Records what a layer was asked to be, so construction can be verified."""

    def __init__(self, kind, **kwargs):
        self.kind = kind
        self.kwargs = kwargs


class _StubViewState:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _StubDeck:
    def __init__(self, layers=None, initial_view_state=None, map_provider="mapbox",
                 map_style="dark", tooltip=None):
        self.layers = layers or []
        self.initial_view_state = initial_view_state
        self.map_provider = map_provider
        self.map_style = map_style
        self.tooltip = tooltip


class _StubPydeck:
    Layer = _StubLayer
    ViewState = _StubViewState
    Deck = _StubDeck


class TestDeckConstruction(unittest.TestCase):
    """Exercises the real construction path with a stub pydeck.

    This is as close as we get to rendering without Streamlit installed: it
    proves the layer types, accessor names and Deck arguments are what we intend,
    which is what the from_json bug bypassed entirely.
    """

    def setUp(self):
        from lpr_cpe_demo.fault_generator import generate_faults
        from lpr_cpe_demo.ui import deck as deckbuild
        self.pdk = _StubPydeck()
        self.build = deckbuild
        self.faults = generate_faults(40, seed=61)

    def test_basemap_is_an_openstreetmap_tile_layer_and_comes_first(self):
        d = self.build.deck(self.pdk, self.build.fault_layers(self.pdk, self.faults))
        self.assertEqual(d.layers[0].kind, "TileLayer")
        self.assertIn("tile.openstreetmap.org", d.layers[0].kwargs["data"])

    def test_no_second_basemap_is_requested(self):
        """map_provider and map_style must be None or deck.gl adds its own."""
        d = self.build.deck(self.pdk, [])
        self.assertIsNone(d.map_provider)
        self.assertIsNone(d.map_style)

    def test_hub_layers_are_ring_core_and_label(self):
        kinds = [l.kind for l in self.build.hub_layers(self.pdk)]
        self.assertEqual(kinds, ["ScatterplotLayer", "ScatterplotLayer", "TextLayer"])

    def test_hub_ring_is_stroked_and_filled_so_it_reads_as_a_depot(self):
        ring = self.build.hub_layers(self.pdk)[0]
        self.assertTrue(ring.kwargs["stroked"])
        self.assertTrue(ring.kwargs["filled"])
        self.assertGreaterEqual(ring.kwargs["line_width_min_pixels"], 2)

    def test_hub_label_layer_carries_the_hub_code(self):
        label = self.build.hub_layers(self.pdk)[2]
        self.assertEqual(label.kwargs["get_text"], "label")
        self.assertTrue(any(r["label"] for r in label.kwargs["data"]))

    def test_road_and_ferry_legs_are_separate_layer_types(self):
        from lpr_cpe_demo.fault_generator import generate_faults
        faults = generate_faults(400, seed=62)          # enough to catch an island job
        kinds = [l.kind for l in self.build.fault_layers(self.pdk, faults)]
        self.assertIn("PathLayer", kinds)
        self.assertIn("ArcLayer", kinds)

    def test_routes_can_be_suppressed(self):
        layers = self.build.fault_layers(self.pdk, self.faults, show_routes=False)
        labels = [l.kwargs.get("get_path") for l in layers if l.kind == "PathLayer"]
        self.assertEqual(len(labels), 1, "only the premise link should remain")

    def test_route_layers_appear_only_when_routes_are_requested(self):
        """Replaces the dict-spec coverage removed in the v1.12.1 audit."""
        with_routes = {l.kind for l in
                       self.build.fault_layers(self.pdk, self.faults, show_routes=True)}
        without = {l.kind for l in
                   self.build.fault_layers(self.pdk, self.faults, show_routes=False)}
        self.assertIn("PathLayer", with_routes)
        self.assertLessEqual(len(without), len(with_routes) + 1)

    def test_all_marker_layers_are_present_in_the_fault_view(self):
        kinds = [l.kind for l in self.build.fault_layers(self.pdk, self.faults)]
        self.assertEqual(kinds.count("TextLayer"), 1, "hub labels")
        self.assertGreaterEqual(kinds.count("ScatterplotLayer"), 3)

    def test_fault_pins_draw_above_the_hubs(self):
        layers = self.build.fault_layers(self.pdk, self.faults)
        kinds = [l.kind for l in layers]
        self.assertEqual(kinds[-1], "ScatterplotLayer")
        self.assertEqual(layers[-1].kwargs["get_radius"], "radius")

    def test_every_accessor_names_a_field_present_in_the_data(self):
        """A misnamed accessor renders nothing and raises no error."""
        for layer in self.build.fault_layers(self.pdk, self.faults):
            data = layer.kwargs.get("data")
            if not isinstance(data, list) or not data:
                continue
            for key, value in layer.kwargs.items():
                if not key.startswith("get_") or not isinstance(value, str):
                    continue
                if value.startswith("'"):        # a quoted deck.gl literal
                    continue
                self.assertIn(value, data[0],
                              f"{layer.kind}.{key} = {value!r} is not a data field")

    def test_footprint_layers_include_sites_markers_and_hubs(self):
        kinds = [l.kind for l in self.build.footprint_layers(self.pdk)]
        self.assertGreaterEqual(kinds.count("ScatterplotLayer"), 4)
        self.assertIn("TextLayer", kinds)

    def test_a_failing_layer_is_skipped_rather_than_killing_the_map(self):
        class Broken(_StubPydeck):
            class Layer:                                   # noqa: D106
                def __init__(self, kind, **kwargs):
                    if kind == "TextLayer":
                        raise TypeError("unsupported kwarg")
                    self.kind, self.kwargs = kind, kwargs
        kinds = [l.kind for l in self.build.hub_layers(Broken())]
        self.assertEqual(kinds, ["ScatterplotLayer", "ScatterplotLayer"])
