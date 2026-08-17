#!/usr/bin/env python3
"""Generate the Puerto Rico landmark artwork used behind the GUI header.

    PYTHONPATH=src python3 scripts/generate_landmark_band.py

ORIGINAL LINE WORK. Nothing is fetched and no photograph is embedded, so there is
no licensing question and no network dependency. The motifs are abstracted from
recognisable Puerto Rico subjects: a garita (the sentry boxes on the San Juan
fortifications), a crenellated wall, the Cordillera Central ridgeline, a coastal
lighthouse, and palm forms.

Two outputs:
  landmark_band.svg       wide strip for the page header
  landmark_watermark.svg  square-ish corner mark

Both are single-tone at full opacity in the file; opacity is applied in CSS, so
`ui/theme.py` controls readability in one place and the contrast tests measure the
composite that text actually sits on.
"""

from __future__ import annotations

import base64
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpr_cpe_demo.ui.theme import ARTWORK_INK  # noqa: E402

ASSETS = ROOT / "src/lpr_cpe_demo/ui/assets"
BAND = ASSETS / "landmark_band.svg"
WATERMARK = ASSETS / "landmark_watermark.svg"


def _garita(x: float, y: float, scale: float) -> str:
    """A sentry box: domed cap, tapered body, corbel, slit window."""
    s = scale
    return f"""
  <g transform="translate({x},{y}) scale({s})">
    <path d="M0,-46 C-13,-46 -21,-38 -21,-29 L21,-29 C21,-38 13,-46 0,-46 Z"/>
    <rect x="-23" y="-30" width="46" height="5" rx="2"/>
    <path d="M-19,-24 L19,-24 L15,26 L-15,26 Z"/>
    <rect x="-4" y="-16" width="8" height="20" rx="4" fill="#FFFFFF"
          fill-opacity="0.55"/>
    <path d="M-15,26 C-9,34 9,34 15,26 L18,34 L-18,34 Z"/>
  </g>"""


def _wall(x: float, y: float, width: float, height: float,
          merlons: int = 9) -> str:
    """Crenellated wall: alternating merlons over a solid course."""
    step = width / merlons
    teeth = "".join(
        f'<rect x="{x + i * step:.1f}" y="{y - height * 0.42:.1f}" '
        f'width="{step * 0.52:.1f}" height="{height * 0.42:.1f}" rx="1.5"/>'
        for i in range(merlons))
    return f"""
  <g>
    {teeth}
    <rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{height:.1f}" rx="2"/>
    <rect x="{x:.1f}" y="{y - 3:.1f}" width="{width:.1f}" height="3" rx="1.5"/>
  </g>"""


def _ridgeline(x: float, y: float, width: float, height: float) -> str:
    """Cordillera Central: three overlapping ridges, back ones lower contrast."""
    def ridge(offset: float, h: float, opacity: float) -> str:
        w = width
        pts = [(x, y), (x + w * 0.14, y - h * 0.55), (x + w * 0.27, y - h * 0.28),
               (x + w * 0.42, y - h), (x + w * 0.58, y - h * 0.42),
               (x + w * 0.72, y - h * 0.78), (x + w * 0.87, y - h * 0.32),
               (x + w, y)]
        d = " ".join(f"{px:.1f},{py + offset:.1f}" for px, py in pts)
        return f'<polygon points="{d}" fill-opacity="{opacity}"/>'
    return ridge(0, height, 0.9) + ridge(6, height * 0.72, 0.55) + \
        ridge(12, height * 0.5, 0.32)


def _lighthouse(x: float, y: float, scale: float) -> str:
    s = scale
    return f"""
  <g transform="translate({x},{y}) scale({s})">
    <path d="M-11,30 L-7,-18 L7,-18 L11,30 Z"/>
    <rect x="-9" y="-24" width="18" height="6" rx="2"/>
    <path d="M-6,-24 L-6,-33 L6,-33 L6,-24 Z"/>
    <path d="M-7,-33 C-7,-40 7,-40 7,-33 Z"/>
    <rect x="-13" y="30" width="26" height="5" rx="2"/>
    <path d="M8,-29 L26,-35 L26,-23 Z" fill-opacity="0.35"/>
  </g>"""


def _palm(x: float, y: float, scale: float, lean: float = 0.0) -> str:
    s = scale
    fronds = "".join(
        f'<path d="M0,-38 C{dx * 0.5:.0f},{-46 + abs(dx) * 0.06:.0f} '
        f'{dx * 0.85:.0f},{-44 + abs(dx) * 0.12:.0f} {dx:.0f},{dy:.0f} '
        f'C{dx * 0.8:.0f},{dy - 7:.0f} {dx * 0.45:.0f},{-44:.0f} 0,-41 Z"/>'
        for dx, dy in ((-26, -28), (-18, -14), (26, -28), (18, -14), (0, -50)))
    return f"""
  <g transform="translate({x},{y}) scale({s}) rotate({lean})">
    <path d="M-3,26 C-5,4 -4,-20 -1,-38 L3,-38 C1,-20 2,4 3,26 Z"/>
    {fronds}
  </g>"""


def band() -> str:
    w, h = 900, 240
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}"
     width="{w}" height="{h}" role="img"
     aria-label="Abstract Puerto Rico motif: garita, fortification wall, Cordillera ridgeline, lighthouse and palms">
  <g fill="{ARTWORK_INK}" stroke="none">
    {_ridgeline(40, 196, 520, 96)}
    {_wall(300, 168, 300, 28, 11)}
    {_garita(300, 150, 1.15)}
    {_lighthouse(700, 160, 1.25)}
    {_palm(620, 200, 1.0, -6)}
    {_palm(790, 204, 0.82, 7)}
    <path d="M0,214 C140,206 300,222 460,214 C620,206 760,222 900,212 L900,240 L0,240 Z"
          fill-opacity="0.5"/>
    <path d="M0,226 C160,220 320,232 480,226 C640,220 780,232 900,224 L900,240 L0,240 Z"
          fill-opacity="0.35"/>
  </g>
</svg>
"""


def watermark() -> str:
    w, h = 420, 420
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}"
     width="{w}" height="{h}" role="img"
     aria-label="Abstract Puerto Rico corner motif: garita over a fortification wall">
  <g fill="{ARTWORK_INK}" stroke="none">
    {_ridgeline(20, 330, 380, 90)}
    {_wall(150, 300, 250, 30, 9)}
    {_garita(196, 282, 1.7)}
    {_palm(360, 340, 1.1, 8)}
    <path d="M0,354 C110,346 240,362 360,354 C400,351 420,354 420,354 L420,420 L0,420 Z"
          fill-opacity="0.45"/>
  </g>
</svg>
"""


def data_uri(svg_text: str) -> str:
    encoded = base64.b64encode(svg_text.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def main() -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)
    BAND.write_text(band(), encoding="utf-8")
    WATERMARK.write_text(watermark(), encoding="utf-8")
    print(f"wrote {BAND.relative_to(ROOT)} ({len(BAND.read_bytes())} bytes)")
    print(f"wrote {WATERMARK.relative_to(ROOT)} ({len(WATERMARK.read_bytes())} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
