"""Integrity guards.

These catch the class of problem that presents as a confusing import error deep in
a traceback: a mangled source file, or metadata that has drifted out of step.

    PYTHONPATH=src python3 -m unittest tests.test_bundle_integrity -v
"""

from __future__ import annotations

import ast
import pathlib
import re
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

PKG = ROOT / "src/lpr_cpe_demo"


class TestPackageInitFiles(unittest.TestCase):
    """A subpackage's __init__ content landing in the parent is a real failure mode.

    It presents as `ModuleNotFoundError: No module named 'lpr_cpe_demo.client'`
    raised from `lpr_cpe_demo/__init__.py`, which looks like a code bug and is not.
    """

    def test_top_level_init_declares_only_metadata(self):
        tree = ast.parse((PKG / "__init__.py").read_text(encoding="utf-8"))
        imports = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(imports, [],
                         "the top-level __init__ must not import submodules; a relative "
                         "import here is the signature of a misplaced subpackage __init__")

    def test_no_init_imports_a_sibling_that_does_not_exist(self):
        for init in PKG.rglob("__init__.py"):
            tree = ast.parse(init.read_text(encoding="utf-8"))
            for node in tree.body:
                if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
                    target = init.parent / f"{node.module}.py"
                    package = init.parent / node.module / "__init__.py"
                    self.assertTrue(target.exists() or package.exists(),
                                    f"{init.relative_to(ROOT)} imports .{node.module} "
                                    f"which does not exist beside it")

    def test_mcp_client_init_is_where_the_client_import_belongs(self):
        self.assertIn("from .client import",
                      (PKG / "mcp_client/__init__.py").read_text(encoding="utf-8"))

    def test_every_package_directory_has_an_init(self):
        for path in PKG.rglob("*"):
            if not path.is_dir() or path.name in {"__pycache__", "assets", "kb", "fixtures"}:
                continue
            self.assertTrue((path / "__init__.py").exists(),
                            f"{path.relative_to(ROOT)} has no __init__.py")


class TestVersionConsistency(unittest.TestCase):
    @staticmethod
    def _pyproject_version() -> str:
        match = re.search(r'^version = "([^"]+)"',
                          (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M)
        assert match, "no version in pyproject.toml"
        return match.group(1)

    def test_package_version_matches_pyproject(self):
        import lpr_cpe_demo
        self.assertEqual(lpr_cpe_demo.__version__, self._pyproject_version())

    def test_changelog_leads_with_the_current_version(self):
        for line in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                self.assertTrue(line.split()[1].startswith(self._pyproject_version()),
                                f"newest CHANGELOG entry is {line!r}")
                return
        self.fail("no version heading found in CHANGELOG.md")


class TestExplicitTextEncoding(unittest.TestCase):
    """Repository text reads must not depend on the host locale."""

    def test_path_read_text_calls_specify_an_encoding(self):
        offenders: list[str] = []
        for root_name in ("src", "scripts", "tests"):
            for path in (ROOT / root_name).rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    if not isinstance(node.func, ast.Attribute):
                        continue
                    if node.func.attr != "read_text":
                        continue
                    has_encoding = bool(node.args) or any(
                        keyword.arg == "encoding" for keyword in node.keywords
                    )
                    if not has_encoding:
                        offenders.append(
                            f"{path.relative_to(ROOT)}:{node.lineno}"
                        )
        self.assertEqual(
            offenders,
            [],
            "Path.read_text() must specify encoding=\"utf-8\"; "
            f"locale-dependent calls: {offenders}",
        )


class TestManifestVerifier(unittest.TestCase):
    def test_verifier_reports_a_clean_tree(self):
        out = subprocess.run([sys.executable, "scripts/verify_manifest.py"],
                             cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("matches the manifest", out.stdout)

    def test_verifier_detects_a_tampered_file(self):
        """Proves the guard works by breaking a file and putting it back."""
        target = PKG / "__init__.py"
        original = target.read_bytes()
        try:
            target.write_text("from .client import Nope\n")
            out = subprocess.run([sys.executable, "scripts/verify_manifest.py"],
                                 cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(out.returncode, 1)
            self.assertIn("MISMATCH", out.stdout)
            self.assertIn("src/lpr_cpe_demo/__init__.py", out.stdout)
            self.assertIn("git restore", out.stdout)
        finally:
            target.write_bytes(original)

    def test_verifier_detects_a_missing_file(self):
        target = PKG / "controls.py"
        original = target.read_bytes()
        try:
            target.unlink()
            out = subprocess.run([sys.executable, "scripts/verify_manifest.py"],
                                 cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(out.returncode, 1)
            self.assertIn("MISSING", out.stdout)
        finally:
            target.write_bytes(original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
