"""Dark control-tower theme, matching the supplied dashboard format.

The legacy Control Tower keeps its glass-card and neon-accent vocabulary, but
uses an explicitly neutral dark-grey page background so the global light
executive theme cannot bleed through. Cards and plots retain their measured
slate surfaces for contrast stability.

Contrast was measured before adopting it, using the same arithmetic as the light
theme. Every accent clears WCAG AA for body text against the glass card:

    cyan 7.95   amber 8.60   green 7.47   blue 5.65   red 5.34   violet 5.28

The one rule the palette needs: `slate-500` reaches only 3.02 against the card,
so it is large-text-only and is not used for body copy. `MUTED` is `slate-400` at
5.60 instead.
"""

from __future__ import annotations

from .theme import ContrastCheck, composite, contrast_ratio

# Neutral page background for the legacy dashboard. These values are kept
# separate from the slate chart/card palette so the proven contrast pairings do
# not change when the page background is made dark grey.
LEGACY_GREY_950 = "#171717"
LEGACY_GREY_900 = "#232323"
LEGACY_GREY_800 = "#303030"

SLATE_950 = "#020617"
SLATE_900 = "#0F172A"
INDIGO_950 = "#1E1B4B"  # retained for compatibility with existing chart code

INK = "#F1F5F9"          # slate-100
MUTED = "#94A3B8"        # slate-400. Do NOT drop to slate-500 for body copy.
LARGE_ONLY = "#64748B"   # slate-500, 3.02 on the card: headings and rules only

ACCENTS = {"cyan": "#22D3EE", "blue": "#60A5FA", "violet": "#A78BFA",
           "amber": "#FBBF24", "red": "#FB7185", "green": "#34D399"}

CARD_OPACITY = 0.08
CARD = composite("#FFFFFF", SLATE_900, CARD_OPACITY)   # #222A3B

PROVENANCE_ACCENT = {"computed": ACCENTS["green"],
                     "assumed": ACCENTS["amber"],
                     "synthetic": ACCENTS["red"]}
PROVENANCE_LABEL = {"computed": "computed from the model",
                    "assumed": "stated assumption",
                    "synthetic": "shape only, no data source"}

WCAG_AA_BODY = 4.5
WCAG_AA_LARGE = 3.0


def contrast_report() -> list[ContrastCheck]:
    checks = [
        ContrastCheck("ink on card", INK, CARD, contrast_ratio(INK, CARD),
                      WCAG_AA_BODY),
        ContrastCheck("ink on gradient", INK, SLATE_950,
                      contrast_ratio(INK, SLATE_950), WCAG_AA_BODY),
        ContrastCheck("muted on card", MUTED, CARD, contrast_ratio(MUTED, CARD),
                      WCAG_AA_BODY),
        ContrastCheck("large-only tone on card", LARGE_ONLY, CARD,
                      contrast_ratio(LARGE_ONLY, CARD), WCAG_AA_LARGE),
    ]
    checks += [ContrastCheck(f"{name} on card", value, CARD,
                             contrast_ratio(value, CARD), WCAG_AA_BODY)
               for name, value in ACCENTS.items()]
    checks += [ContrastCheck(f"{name} on plot", value, SLATE_900,
                             contrast_ratio(value, SLATE_900), WCAG_AA_LARGE)
               for name, value in ACCENTS.items()]
    return checks


def failing_checks() -> list[ContrastCheck]:
    return [c for c in contrast_report() if not c.passes]


def plotly_layout(height: int = 260) -> dict:
    """Transparent plot so the gradient shows through, with legible axes."""
    return {
        "height": height,
        "margin": {"l": 44, "r": 16, "t": 12, "b": 34},
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {"color": INK, "size": 12},
        "xaxis": {"gridcolor": "rgba(148,163,184,0.16)", "zeroline": False,
                  "linecolor": "rgba(148,163,184,0.3)"},
        "yaxis": {"gridcolor": "rgba(148,163,184,0.16)", "zeroline": False,
                  "linecolor": "rgba(148,163,184,0.3)"},
        "legend": {"orientation": "h", "y": -0.22, "font": {"color": MUTED}},
        "hoverlabel": {"bgcolor": SLATE_900, "font": {"color": INK}},
    }


def css() -> str:
    return f"""<style>
    .stApp,
    [data-testid="stAppViewContainer"],
    [data-testid="stMain"] {{
        background: linear-gradient(160deg, {LEGACY_GREY_950} 0%,
                                    {LEGACY_GREY_900} 58%,
                                    {LEGACY_GREY_800} 100%) !important;
        background-attachment: fixed !important;
    }}
    .block-container {{ padding-top: 1rem; max-width: 1500px; }}
    .stApp, .stApp p, .stApp li, .stApp span, .stApp label {{ color: {INK}; }}
    .stApp h1, .stApp h2, .stApp h3 {{ color: {INK}; letter-spacing: -0.015em; }}

    .ct-hero {{
        border: 1px solid rgba(255,255,255,0.10);
        background: rgba(255,255,255,{CARD_OPACITY});
        border-radius: 16px; padding: 1.15rem 1.35rem; margin-bottom: 0.9rem;
        backdrop-filter: blur(6px);
    }}
    .ct-hero h1 {{ margin: 0; font-size: 1.5rem; }}
    .ct-hero p {{ margin: 0.4rem 0 0; color: {MUTED}; font-size: 0.9rem;
                  max-width: 96ch; }}
    .ct-badges {{ margin-top: 0.75rem; display: flex; flex-wrap: wrap; gap: 0.4rem; }}
    .ct-badge {{
        font-size: 0.74rem; padding: 0.22rem 0.6rem; border-radius: 999px;
        border: 1px solid rgba(255,255,255,0.18); color: {INK};
        background: rgba(255,255,255,0.06);
    }}
    .ct-badge.caveat {{ border-color: {ACCENTS['amber']}; color: {ACCENTS['amber']}; }}

    .ct-crosslink {{
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: 1rem;
        align-items: center;
        border: 1px solid rgba(255,255,255,0.12);
        background: rgba(255,255,255,0.065);
        border-radius: 14px;
        padding: 0.85rem 1rem;
        margin: 0 0 0.9rem;
        backdrop-filter: blur(6px);
    }}
    .ct-crosslink-title {{
        color: {INK};
        font-weight: 700;
        font-size: 0.94rem;
        margin-bottom: 0.15rem;
    }}
    .ct-crosslink-copy {{
        color: {MUTED};
        font-size: 0.79rem;
        line-height: 1.45;
    }}
    .ct-crosslink-actions {{ display: flex; flex-wrap: wrap; gap: 0.45rem; }}
    .ct-crosslink-link {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 2.35rem;
        padding: 0.42rem 0.75rem;
        border-radius: 9px;
        border: 1px solid rgba(255,255,255,0.18);
        background: rgba(255,255,255,0.075);
        color: {INK} !important;
        text-decoration: none !important;
        font-size: 0.78rem;
        font-weight: 700;
        white-space: nowrap;
    }}
    .ct-crosslink-link:hover {{
        border-color: {ACCENTS['cyan']};
        background: rgba(34,211,238,0.12);
    }}
    .ct-crosslink-link.primary {{
        border-color: {ACCENTS['cyan']};
        background: {ACCENTS['cyan']};
        color: {SLATE_950} !important;
    }}
    @media (max-width: 800px) {{
        .ct-crosslink {{ grid-template-columns: 1fr; }}
    }}

    .ct-card {{
        border: 1px solid rgba(255,255,255,0.10);
        background: rgba(255,255,255,{CARD_OPACITY});
        border-radius: 14px; padding: 0.9rem 1.05rem; margin-bottom: 0.75rem;
        backdrop-filter: blur(6px);
    }}
    .ct-card h3 {{ margin: 0 0 0.1rem; font-size: 1rem; }}
    .ct-note {{ color: {MUTED}; font-size: 0.79rem; margin: 0.35rem 0 0;
                line-height: 1.45; }}

    .ct-prov {{
        display: inline-block; font-size: 0.68rem; letter-spacing: 0.04em;
        text-transform: uppercase; padding: 0.14rem 0.5rem; border-radius: 5px;
        border: 1px solid currentColor; margin-bottom: 0.45rem;
    }}
    .ct-prov.computed {{ color: {ACCENTS['green']}; }}
    .ct-prov.assumed {{ color: {ACCENTS['amber']}; }}
    .ct-prov.synthetic {{ color: {ACCENTS['red']}; }}

    .ct-kpi-value {{ font-size: 1.7rem; font-weight: 600; color: {ACCENTS['cyan']};
                     line-height: 1.1; }}
    .ct-kpi-label {{ font-size: 0.76rem; color: {MUTED};
                     text-transform: uppercase; letter-spacing: 0.05em; }}
    .ct-kpi-desc {{ font-size: 0.76rem; color: {MUTED}; margin-top: 0.3rem;
                    line-height: 1.4; }}

    /* Tables must not go transparent over the gradient. */
    [data-testid="stDataFrame"], .stDataFrame {{
        background: rgba(15,23,42,0.92) !important;
        border: 1px solid rgba(255,255,255,0.10); border-radius: 10px;
    }}
    [data-testid="stExpander"] {{
        background: rgba(255,255,255,{CARD_OPACITY}); border-radius: 10px;
        border: 1px solid rgba(255,255,255,0.10);
    }}
    </style>"""


def executive_crosslink() -> str:
    """Return links into active-run evidence and the DvSum CADDI/Genesys contract."""
    return (
        '<div class="ct-crosslink">'
        '<div><div class="ct-crosslink-title">Continue into active-run evidence</div>'
        '<div class="ct-crosslink-copy">The legacy scorecard remains a modeled '
        'benchmark. Open the connected workflow to inspect predictive modem risk, '
        'Customer Care correlation, DvSum CADDI/Genesys analytics and governed resolution '
        'for the active run.</div></div>'
        '<div class="ct-crosslink-actions">'
        '<a class="ct-crosslink-link primary" target="_self" '
        'href="digital-twin?view=predictive">Predictive health →</a>'
        '<a class="ct-crosslink-link" target="_self" '
        'href="digital-twin?view=customer-care">Customer Care →</a>'
        '<a class="ct-crosslink-link" target="_self" '
        'href="digital-twin?view=caddi">DvSum CADDI / Genesys →</a>'
        '</div></div>'
    )


def card_open(title: str, provenance: str, note: str = "") -> str:
    label = PROVENANCE_LABEL.get(provenance, provenance)
    note_html = f'<p class="ct-note">{note}</p>' if note else ""
    return (f'<div class="ct-card">'
            f'<span class="ct-prov {provenance}">{label}</span>'
            f'<h3>{title}</h3>{note_html}</div>')


def hero(title: str, subtitle: str, badges: list[dict]) -> str:
    chips = "".join(
        f'<span class="ct-badge {"caveat" if b.get("type") == "caveat" else ""}">'
        f'{b["label"]}</span>' for b in badges)
    return (f'<div class="ct-hero"><h1>{title}</h1><p>{subtitle}</p>'
            f'<div class="ct-badges">{chips}</div></div>')


def kpi(label: str, value: str, description: str) -> str:
    return (f'<div class="ct-card"><div class="ct-kpi-label">{label}</div>'
            f'<div class="ct-kpi-value">{value}</div>'
            f'<div class="ct-kpi-desc">{description}</div></div>')
