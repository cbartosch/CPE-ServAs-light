#!/usr/bin/env python3
"""Verify the working tree against MANIFEST.sha256.

    python3 scripts/verify_manifest.py
    python3 scripts/verify_manifest.py --show-untracked

Standard library only, so it runs on Windows, macOS and Linux with no install and
inside a bare python image. UTF-8 text is hashed in a canonical LF form so Git's
Windows CRLF checkout conversion does not produce a false integrity failure.
Binary files are always verified byte-for-byte.

Why this exists
---------------
A single mangled source file produces an import error deep in a traceback that
looks like a code bug. Comparing the tree against the manifest turns that into a
one-line answer naming the file. Add it to your loop before rebuilding an image.

Exit codes
    0  every manifested file present and matching
    1  one or more files mismatched or missing
    2  the manifest itself is missing or unreadable
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "MANIFEST.sha256"
LINE = re.compile(r"^([0-9a-fA-F]{64})\s+\*?(.+)$")

# Not manifested by design: generated, ignored, or environment specific.
SKIP_DIRS = {".git", "__pycache__", "vendor", ".venv", ".pytest_cache"}
SKIP_FILES = {"MANIFEST.sha256", "BUNDLE_MANIFEST.sha256", "FILE_MANIFEST.txt",
              ".env", ".coverage"}


def _canonical_manifest_bytes(path: pathlib.Path) -> tuple[bytes, bool]:
    """Return bytes in the cross-platform form used by ``MANIFEST.sha256``.

    Git commonly checks text out with CRLF on Windows when ``core.autocrlf`` is
    enabled. That is a presentation-layer change, not content corruption. Files
    that are valid UTF-8 text and contain no NUL byte are therefore normalized to
    LF before hashing. Non-UTF-8 or NUL-containing files remain byte-exact.
    """
    raw = path.read_bytes()
    if b"\x00" in raw:
        return raw, False
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw, False
    canonical = text.replace("\r\n", "\n").encode("utf-8")
    return canonical, canonical != raw


def sha256(path: pathlib.Path) -> str:
    canonical, _ = _canonical_manifest_bytes(path)
    return hashlib.sha256(canonical).hexdigest()


def raw_sha256(path: pathlib.Path) -> str:
    """Hash the checkout bytes for diagnostics; not used for pass/fail."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--show-untracked", action="store_true",
                        help="also list files present but absent from the manifest")
    args = parser.parse_args()

    if not MANIFEST.exists():
        print(f"ERROR: {MANIFEST.name} not found in {ROOT}", file=sys.stderr)
        return 2

    expected: dict[str, str] = {}
    for raw in MANIFEST.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        match = LINE.match(raw)
        if match:
            expected[match.group(2).replace("\\", "/")] = match.group(1).lower()

    if not expected:
        print(f"ERROR: {MANIFEST.name} contains no usable entries", file=sys.stderr)
        return 2

    mismatched: list[str] = []
    missing: list[str] = []
    ok = 0

    for rel, digest in sorted(expected.items()):
        path = ROOT / rel
        if not path.is_file():
            missing.append(rel)
            continue
        if sha256(path) != digest:
            mismatched.append(rel)
        else:
            ok += 1

    untracked: list[str] = []
    if args.show_untracked:
        for path in sorted(ROOT.rglob("*")):
            if not path.is_file():
                continue
            if set(path.relative_to(ROOT).parts) & SKIP_DIRS:
                continue
            rel = str(path.relative_to(ROOT)).replace("\\", "/")
            if rel in SKIP_FILES or rel in expected:
                continue
            untracked.append(rel)

    print(f"manifest entries : {len(expected)}")
    print(f"verified         : {ok}")
    print(f"MISMATCHED       : {len(mismatched)}")
    print(f"MISSING          : {len(missing)}")
    if args.show_untracked:
        print(f"untracked        : {len(untracked)}")

    for rel in mismatched:
        path = ROOT / rel
        canonical, normalized = _canonical_manifest_bytes(path)
        actual = hashlib.sha256(canonical).hexdigest()
        print(f"\nMISMATCH  {rel}")
        print(f"  expected  {expected[rel]}")
        print(f"  canonical {actual}")
        if normalized:
            print(f"  checkout  {raw_sha256(path)} (line endings normalized for verification)")
    for rel in missing:
        print(f"\nMISSING   {rel}")
    for rel in untracked:
        print(f"\nUNTRACKED {rel}")

    if mismatched or missing:
        print("\nThe tree does not match the manifest. If this is a git checkout, "
              "restore the listed files:")
        for rel in (mismatched + missing)[:6]:
            print(f"  git restore -- {rel}")
        print("\nThen rebuild without cache:")
        print("  docker compose build --no-cache")
        return 1

    print("\nThe working tree matches the manifest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
