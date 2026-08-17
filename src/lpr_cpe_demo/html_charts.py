"""Inline SVG chart builders for the standalone control-tower report.

Why hand-built SVG rather than a charting library
-------------------------------------------------
The report must open with **zero external requests**. A CDN script tag is the
normal way to get charts, and it is exactly what fails on a network that blocks
outbound traffic — the same class of failure that has cost this project the most
time. Every chart is therefore computed here and embedded as markup, so the file
works from a USB stick.

Everything returns a string of SVG and is standard-library only, which also makes
the geometry testable: an arc that does not close, a bar that overflows its axis or
a label placed outside the viewBox is caught by a test rather than by squinting.
"""

from __future__ import annotations

import html
import math
from typing import Iterable, Sequence

# Palette from the supplied dashboard format, contrast-verified in ui/theme_dark.
INK = "#F1F5F9"
MUTED = "#94A3B8"
GRID = "rgba(148,163,184,0.16)"
AXIS = "rgba(148,163,184,0.34)"
ACCENTS = {"cyan": "#22D3EE", "blue": "#60A5FA", "violet": "#A78BFA",
           "amber": "#FBBF24", "red": "#FB7185", "green": "#34D399"}
SERIES = ("#22D3EE", "#FBBF24", "#34D399", "#A78BFA", "#FB7185", "#60A5FA")


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _open(width: int, height: int, label: str) -> str:
    return (f'<svg viewBox="0 0 {width} {height}" width="100%" '
            f'preserveAspectRatio="xMidYMid meet" role="img" '
            f'aria-label="{esc(label)}" class="chart">')


def donut(slices: Sequence[dict], *, width: int = 420, height: int = 260,
          label: str = "Distribution") -> str:
    """Donut with a legend. Arcs are computed, not drawn by a library.

    A single slice of 100% is a full circle, which an arc path cannot express, so
    that case is emitted as a ring instead.
    """
    total = sum(max(float(s["value"]), 0.0) for s in slices) or 1.0
    cx, cy, outer, inner = 128, height / 2, 96, 56
    parts = [_open(width, height, label)]

    if len(slices) == 1:
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{(outer + inner) / 2:.1f}" '
                     f'fill="none" stroke="{esc(slices[0].get("color", SERIES[0]))}" '
                     f'stroke-width="{outer - inner}"/>')
    else:
        angle = -math.pi / 2
        for index, item in enumerate(slices):
            fraction = max(float(item["value"]), 0.0) / total
            if fraction <= 0:
                continue
            sweep = fraction * 2 * math.pi
            end = angle + sweep
            large = 1 if sweep > math.pi else 0
            x1, y1 = cx + outer * math.cos(angle), cy + outer * math.sin(angle)
            x2, y2 = cx + outer * math.cos(end), cy + outer * math.sin(end)
            x3, y3 = cx + inner * math.cos(end), cy + inner * math.sin(end)
            x4, y4 = cx + inner * math.cos(angle), cy + inner * math.sin(angle)
            colour = item.get("color", SERIES[index % len(SERIES)])
            parts.append(
                f'<path d="M{x1:.1f},{y1:.1f} A{outer},{outer} 0 {large} 1 '
                f'{x2:.1f},{y2:.1f} L{x3:.1f},{y3:.1f} '
                f'A{inner},{inner} 0 {large} 0 {x4:.1f},{y4:.1f} Z" '
                f'fill="{esc(colour)}" stroke="#0F172A" stroke-width="1.5"/>')
            angle = end

    legend_x, legend_y = 244, cy - (len(slices) * 22) / 2 + 11
    for index, item in enumerate(slices):
        colour = item.get("color", SERIES[index % len(SERIES)])
        y = legend_y + index * 22
        parts.append(f'<rect x="{legend_x}" y="{y - 8}" width="11" height="11" '
                     f'rx="2.5" fill="{esc(colour)}"/>')
        parts.append(f'<text x="{legend_x + 19}" y="{y + 1}" fill="{INK}" '
                     f'font-size="12">{esc(item["name"])}</text>')
        parts.append(f'<text x="{width - 14}" y="{y + 1}" fill="{MUTED}" '
                     f'font-size="12" text-anchor="end">'
                     f'{float(item["value"]):.1f}%</text>')
    parts.append("</svg>")
    return "".join(parts)


def stacked_bars(rows: Sequence[dict], *, width: int = 460, height: int = 250,
                 label: str = "Stacked bars") -> str:
    """Horizontal autonomous-versus-human bars. `None` renders as 'no observation'."""
    left, right, top = 92, 58, 14
    plot = width - left - right
    band = (height - top - 10) / max(len(rows), 1)
    parts = [_open(width, height, label)]
    for index, row in enumerate(rows):
        y = top + index * band + band * 0.18
        h = band * 0.5
        parts.append(f'<text x="{left - 10}" y="{y + h * 0.72:.1f}" fill="{INK}" '
                     f'font-size="12" text-anchor="end">{esc(row["stage"])}</text>')
        auto = row.get("autonomous_pct")
        if auto is None:
            parts.append(f'<rect x="{left}" y="{y:.1f}" width="{plot}" '
                         f'height="{h:.1f}" rx="3" fill="rgba(148,163,184,0.13)"/>')
            parts.append(f'<text x="{left + 10}" y="{y + h * 0.72:.1f}" '
                         f'fill="{MUTED}" font-size="11">no observation</text>')
            continue
        auto_w = plot * float(auto) / 100.0
        parts.append(f'<rect x="{left}" y="{y:.1f}" width="{auto_w:.1f}" '
                     f'height="{h:.1f}" rx="3" fill="{ACCENTS["cyan"]}"/>')
        parts.append(f'<rect x="{left + auto_w:.1f}" y="{y:.1f}" '
                     f'width="{plot - auto_w:.1f}" height="{h:.1f}" rx="3" '
                     f'fill="{ACCENTS["amber"]}"/>')
        parts.append(f'<text x="{width - right + 8}" y="{y + h * 0.72:.1f}" '
                     f'fill="{MUTED}" font-size="12">{int(auto)}%</text>')
    parts.append("</svg>")
    return "".join(parts)


def grouped_bars(categories: Sequence[str], series: Sequence[dict], *,
                 width: int = 520, height: int = 270, unit: str = "",
                 label: str = "Grouped bars") -> str:
    """Vertical grouped bars with a value axis. Values of None are skipped."""
    left, right, top, bottom = 58, 12, 18, 52
    plot_w, plot_h = width - left - right, height - top - bottom
    values = [v for s in series for v in s["values"] if v is not None]
    peak = max(values) if values else 1.0
    peak = peak * 1.12 or 1.0

    parts = [_open(width, height, label)]
    for tick in range(5):
        value = peak * tick / 4
        y = top + plot_h - plot_h * tick / 4
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" '
                     f'y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{left - 8}" y="{y + 4:.1f}" fill="{MUTED}" '
                     f'font-size="11" text-anchor="end">{value:,.0f}</text>')

    group_w = plot_w / max(len(categories), 1)
    bar_w = group_w * 0.72 / max(len(series), 1)
    for c_index, category in enumerate(categories):
        base = left + c_index * group_w + group_w * 0.14
        for s_index, s in enumerate(series):
            value = s["values"][c_index] if c_index < len(s["values"]) else None
            if value is None:
                continue
            h = plot_h * float(value) / peak
            x = base + s_index * bar_w
            parts.append(f'<rect x="{x:.1f}" y="{top + plot_h - h:.1f}" '
                         f'width="{bar_w * 0.86:.1f}" height="{h:.1f}" rx="2.5" '
                         f'fill="{esc(s.get("color", SERIES[s_index]))}"/>')
        parts.append(f'<text x="{base + group_w * 0.36:.1f}" '
                     f'y="{top + plot_h + 17}" fill="{INK}" font-size="11" '
                     f'text-anchor="middle">{esc(category)}</text>')

    for s_index, s in enumerate(series):
        x = left + s_index * 168
        y = height - 12
        parts.append(f'<rect x="{x}" y="{y - 9}" width="11" height="11" rx="2.5" '
                     f'fill="{esc(s.get("color", SERIES[s_index]))}"/>')
        parts.append(f'<text x="{x + 18}" y="{y}" fill="{MUTED}" font-size="11">'
                     f'{esc(s["name"])}{esc(unit)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def lines(x_labels: Sequence[str], series: Sequence[dict], *, width: int = 520,
          height: int = 250, y_min: float = 0.0, y_max: float = 100.0,
          label: str = "Lines") -> str:
    left, right, top, bottom = 46, 12, 16, 46
    plot_w, plot_h = width - left - right, height - top - bottom
    span = (y_max - y_min) or 1.0
    parts = [_open(width, height, label)]
    for tick in range(5):
        value = y_min + span * tick / 4
        y = top + plot_h - plot_h * tick / 4
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" '
                     f'y2="{y:.1f}" stroke="{GRID}"/>')
        parts.append(f'<text x="{left - 7}" y="{y + 4:.1f}" fill="{MUTED}" '
                     f'font-size="11" text-anchor="end">{value:.0f}</text>')
    step = plot_w / max(len(x_labels) - 1, 1)
    for index, text in enumerate(x_labels):
        parts.append(f'<text x="{left + index * step:.1f}" '
                     f'y="{top + plot_h + 16}" fill="{MUTED}" font-size="10.5" '
                     f'text-anchor="middle">{esc(text)}</text>')
    for s_index, s in enumerate(series):
        points = []
        for index, value in enumerate(s["values"]):
            x = left + index * step
            y = top + plot_h - plot_h * (float(value) - y_min) / span
            points.append(f"{x:.1f},{y:.1f}")
        colour = s.get("color", SERIES[s_index % len(SERIES)])
        parts.append(f'<polyline points="{" ".join(points)}" fill="none" '
                     f'stroke="{esc(colour)}" stroke-width="2" '
                     f'stroke-linejoin="round"/>')
        x = left + s_index * 92
        parts.append(f'<rect x="{x}" y="{height - 21}" width="11" height="11" '
                     f'rx="2.5" fill="{esc(colour)}"/>')
        parts.append(f'<text x="{x + 18}" y="{height - 12}" fill="{MUTED}" '
                     f'font-size="11">{esc(s["name"])}</text>')
    parts.append("</svg>")
    return "".join(parts)


def bar_row(value: float, *, maximum: float, colour: str = ACCENTS["cyan"],
            width: int = 150, height: int = 8) -> str:
    """Inline meter used inside table cells."""
    filled = max(0.0, min(1.0, value / maximum if maximum else 0.0)) * width
    return (f'<svg viewBox="0 0 {width} {height}" width="{width}" '
            f'height="{height}" role="img" aria-label="{value:g} of {maximum:g}">'
            f'<rect width="{width}" height="{height}" rx="4" '
            f'fill="rgba(148,163,184,0.18)"/>'
            f'<rect width="{filled:.1f}" height="{height}" rx="4" '
            f'fill="{esc(colour)}"/></svg>')


def table(headers: Iterable[str], rows: Iterable[Sequence[object]], *,
          drill_attr: str = "", drill_values: Sequence[str] = ()) -> str:
    """A table whose rows can carry a drill target."""
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body_rows = []
    for index, row in enumerate(rows):
        target = ""
        if drill_attr and index < len(drill_values):
            target = (f' class="drill" tabindex="0" role="link" '
                      f'data-{drill_attr}="{esc(drill_values[index])}"')
        cells = "".join(f"<td>{cell if isinstance(cell, str) and cell.startswith('<svg') else esc(cell)}</td>"
                        for cell in row)
        body_rows.append(f"<tr{target}>{cells}</tr>")
    return (f'<table><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body_rows)}</tbody></table>')
