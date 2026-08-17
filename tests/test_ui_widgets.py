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
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
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
