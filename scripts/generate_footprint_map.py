#!/usr/bin/env python3
"""Generate the schematic footprint map from `geography.py`.

    PYTHONPATH=src python3 scripts/generate_footprint_map.py

The map is generated rather than hand-drawn so it cannot drift from the site and
base data the dispatch model uses. Regenerate after editing SITES or
DISPATCH_BASES.

The coastline is a deliberately simplified polygon. This is a schematic for
operational orientation, not a survey product, and the output says so.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpr_cpe_demo.geography import (DISPATCH_BASES, SITE_BY_ID,  # noqa: E402
                                    core_sites, ferry_terminals,
                                    sites_in_cpe_footprint)

OUT = ROOT / "src/lpr_cpe_demo/ui/assets/footprint_map.svg"

W, H = 1180, 590
PAD_X, PAD_TOP, PAD_BOTTOM = 40, 74, 158

# Simplified coastlines, (lon, lat). Clockwise from the north-west.
MAINLAND = [
    (-67.31, 18.52), (-66.90, 18.50), (-66.55, 18.49), (-66.28, 18.47),
    (-66.10, 18.47), (-65.90, 18.45), (-65.70, 18.40), (-65.58, 18.32),
    (-65.60, 18.20), (-65.68, 18.08), (-65.82, 17.99), (-66.00, 17.95),
    (-66.20, 17.94), (-66.45, 17.96), (-66.70, 17.97), (-66.90, 17.95),
    (-67.15, 17.96), (-67.30, 18.02), (-67.34, 18.14), (-67.30, 18.26),
    (-67.26, 18.38), (-67.31, 18.47),
]
VIEQUES = [(-65.58, 18.11), (-65.48, 18.15), (-65.36, 18.16), (-65.28, 18.13),
           (-65.34, 18.08), (-65.47, 18.07)]
CULEBRA = [(-65.35, 18.31), (-65.29, 18.33), (-65.23, 18.32), (-65.25, 18.28),
           (-65.32, 18.28)]

ARCHETYPE_STYLE = {
    "metro":         ("#0C5457", "Metro / MDU"),
    "coastal":       ("#18A8AF", "Coastal city / suburb"),
    "mountain":      ("#8F7D62", "Central mountain / rural"),
    "remote_island": ("#8A7C6A", "Remote / island"),
}

LON_MIN, LON_MAX = -67.40, -65.15
LAT_MIN, LAT_MAX = 17.88, 18.58


def project(lon: float, lat: float) -> tuple[float, float]:
    x = PAD_X + (lon - LON_MIN) / (LON_MAX - LON_MIN) * (W - 2 * PAD_X)
    y = PAD_TOP + (LAT_MAX - lat) / (LAT_MAX - LAT_MIN) * (H - PAD_TOP - PAD_BOTTOM)
    return round(x, 1), round(y, 1)


def poly(points: list[tuple[float, float]]) -> str:
    return " ".join(f"{x},{y}" for x, y in (project(lon, lat) for lon, lat in points))


def build() -> str:
    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'width="100%" role="img" aria-label="Schematic map of the Liberty Puerto Rico '
        f'fixed CPE footprint with assumed dispatch bases">',
        '<style>'
        '.t{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;fill:#333}'
        '.h{font-size:19px;font-weight:600}.s{font-size:12px;fill:#666}'
        '.lbl{font-size:11px}.blbl{font-size:11px;font-weight:600}'
        '.cap{font-size:10.5px;fill:#777}.lg{font-size:11px}'
        '</style>',
        f'<rect width="{W}" height="{H}" fill="#FCFBFA"/>',
        f'<text class="t h" x="{PAD_X}" y="34">Liberty Puerto Rico fixed CPE footprint</text>',
        f'<text class="t s" x="{PAD_X}" y="54">78 municipios including Vieques and Culebra. '
        f'Hub locations are ASSUMED, from a practitioner assessment, and must be '
        f'replaced with actual facility data.</text>',
    ]

    for shape in (MAINLAND, VIEQUES, CULEBRA):
        parts.append(f'<polygon points="{poly(shape)}" fill="#EDEBE7" '
                     f'stroke="#C9C4BC" stroke-width="1"/>')

    # Ferry links, the constraint that makes island work expensive.
    fx, fy = project(SITE_BY_ID["PR-FAJ"].lon, SITE_BY_ID["PR-FAJ"].lat)
    for sid in ("PR-VQS", "PR-CUL"):
        s = SITE_BY_ID[sid]
        sx, sy = project(s.lon, s.lat)
        parts.append(f'<line x1="{fx}" y1="{fy}" x2="{sx}" y2="{sy}" stroke="#8F7D62" '
                     f'stroke-width="1.4" stroke-dasharray="5 4"/>')
    parts.append(f'<text class="t cap" x="{fx + 26}" y="{fy + 34}">ferry legs</text>')

    # Sites
    for site in sites_in_cpe_footprint():
        colour, _ = ARCHETYPE_STYLE[site.archetype]
        x, y = project(site.lon, site.lat)
        parts.append(f'<circle cx="{x}" cy="{y}" r="4.6" fill="{colour}" '
                     f'stroke="#FCFBFA" stroke-width="1.2"/>')
        anchor = "end" if site.lon < -66.9 else "start"
        dx = -8 if anchor == "end" else 8
        parts.append(f'<text class="t lbl" x="{x + dx}" y="{y + 3.5}" '
                     f'text-anchor="{anchor}">{site.municipio}</text>')

    # Core site: headend and NOC, deliberately not a dispatch hub
    for site in core_sites():
        x, y = project(site.lon, site.lat)
        parts.append(f'<circle cx="{x}" cy="{y}" r="9" fill="none" stroke="#0C5457" '
                     f'stroke-width="2" stroke-dasharray="3 2.5"/>')
        parts.append(f'<text class="t blbl" x="{x}" y="{y - 14}" '
                     f'text-anchor="middle">CORE</text>')

    # Ferry terminal: island work is driven here first
    for site in ferry_terminals():
        x, y = project(site.lon, site.lat)
        parts.append(f'<polygon points="{x},{y - 8} {x + 8},{y} {x},{y + 8} {x - 8},{y}" '
                     f'fill="#FCFBFA" stroke="#8F7D62" stroke-width="2.2"/>')
        parts.append(f'<text class="t blbl" x="{x}" y="{y - 14}" '
                     f'text-anchor="middle">FERRY</text>')

    # Dispatch hubs, on top. Filled centre marks a very-high-likelihood hub.
    for base in DISPATCH_BASES:
        x, y = project(base.lon, base.lat)
        parts.append(f'<rect x="{x - 6.5}" y="{y - 6.5}" width="13" height="13" rx="2.5" '
                     f'fill="#FCFBFA" stroke="#0C5457" stroke-width="2.2"/>')
        if base.likelihood == "very_high":
            parts.append(f'<rect x="{x - 2.6}" y="{y - 2.6}" width="5.2" height="5.2" '
                         f'fill="#0C5457"/>')
        parts.append(f'<text class="t blbl" x="{x}" y="{y - 14}" '
                     f'text-anchor="middle">{base.base_id.replace("BASE-", "")}</text>')

    # Legend
    ly = H - PAD_BOTTOM + 46
    parts.append(f'<text class="t s" x="{PAD_X}" y="{ly - 16}">Archetype</text>')
    for i, (key, (colour, label)) in enumerate(ARCHETYPE_STYLE.items()):
        lx = PAD_X + i * 232
        parts.append(f'<circle cx="{lx + 6}" cy="{ly - 4}" r="4.6" fill="{colour}"/>')
        parts.append(f'<text class="t lg" x="{lx + 18}" y="{ly}">{label}</text>')

    ly2 = ly + 26
    parts.append(f'<rect x="{PAD_X}" y="{ly2 - 9}" width="12" height="12" rx="2.5" '
                 f'fill="#FCFBFA" stroke="#0C5457" stroke-width="2.2"/>')
    parts.append(f'<rect x="{PAD_X + 3.6}" y="{ly2 - 5.4}" width="4.8" height="4.8" '
                 f'fill="#0C5457"/>')
    parts.append(f'<text class="t lg" x="{PAD_X + 20}" y="{ly2}">Hub, very high</text>')

    parts.append(f'<rect x="{PAD_X + 150}" y="{ly2 - 9}" width="12" height="12" rx="2.5" '
                 f'fill="#FCFBFA" stroke="#0C5457" stroke-width="2.2"/>')
    parts.append(f'<text class="t lg" x="{PAD_X + 170}" y="{ly2}">Hub, high</text>')

    parts.append(f'<circle cx="{PAD_X + 286}" cy="{ly2 - 4}" r="7" fill="none" '
                 f'stroke="#0C5457" stroke-width="2" stroke-dasharray="3 2.5"/>')
    parts.append(f'<text class="t lg" x="{PAD_X + 300}" y="{ly2}">Core site, headend and NOC, '
                 f'not a dispatch hub</text>')

    ly3 = ly2 + 22
    cx = PAD_X + 6
    parts.append(f'<polygon points="{cx},{ly3 - 11} {cx + 7},{ly3 - 4} {cx},{ly3 + 3} '
                 f'{cx - 7},{ly3 - 4}" fill="#FCFBFA" stroke="#8F7D62" stroke-width="2.2"/>')
    parts.append(f'<text class="t lg" x="{PAD_X + 20}" y="{ly3}">Ferry terminal: island work '
                 f'is driven here from a mainland hub, then ferried</text>')

    parts.append(f'<text class="t cap" x="{PAD_X}" y="{H - 26}">'
                 f'Schematic. Coastline simplified and municipio positions approximate: '
                 f'adequate for orientation and relative travel time, not for survey use.</text>')
    parts.append(f'<text class="t cap" x="{PAD_X}" y="{H - 12}">'
                 f'U.S. Virgin Islands sites are modelled but excluded from the CPE '
                 f'footprint: LPR serves USVI for mobile, while USVI fixed sits with a '
                 f'separate entity.</text>')
    parts.append('</svg>')
    return "\n".join(parts)


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build() + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} "
          f"({len(sites_in_cpe_footprint())} sites, {len(DISPATCH_BASES)} bases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
