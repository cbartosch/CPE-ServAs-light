"""Executive presentation layer for the unified LPR Streamlit application."""

from __future__ import annotations


def css() -> str:
    """Return an additive C-level presentation layer without changing data semantics."""
    return """<style>
    :root {
        --lpr-navy: #10243e;
        --lpr-navy-2: #17395c;
        --lpr-teal: #0d7c7b;
        --lpr-teal-soft: #e9f7f5;
        --lpr-coral: #ef5b5b;
        --lpr-amber: #d99122;
        --lpr-ink: #172235;
        --lpr-muted: #66758a;
        --lpr-line: #e6ebf1;
        --lpr-paper: #ffffff;
        --lpr-canvas: #f6f8fb;
    }

    .stApp {
        background:
            radial-gradient(circle at 88% 2%, rgba(13,124,123,.07), transparent 28rem),
            linear-gradient(180deg, #fbfcfe 0%, var(--lpr-canvas) 100%) !important;
    }
    .block-container {
        max-width: 1440px;
        padding-top: 1.35rem !important;
        padding-bottom: 3rem !important;
    }

    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #10243e 0%, #153653 58%, #0d6d6f 140%) !important;
        border-right: 0 !important;
    }
    [data-testid="stSidebar"] * { color: rgba(255,255,255,.92); }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
    [data-testid="stSidebar"] small { color: rgba(255,255,255,.70) !important; }
    [data-testid="stSidebar"] [data-testid="stSidebarNav"] a {
        border-radius: 10px;
        margin: 2px 8px;
    }
    [data-testid="stSidebar"] [data-testid="stSidebarNav"] a:hover {
        background: rgba(255,255,255,.10);
    }

    h1, h2, h3 { letter-spacing: -.025em; }
    h1 { font-weight: 760 !important; }
    h2, h3 { font-weight: 690 !important; }
    p, label, .stCaption { line-height: 1.5; }

    [data-testid="stMetric"] {
        background: rgba(255,255,255,.96) !important;
        border: 1px solid var(--lpr-line) !important;
        border-radius: 16px !important;
        box-shadow: 0 8px 24px rgba(16,36,62,.06);
        padding: 1rem 1.1rem !important;
    }
    [data-testid="stMetricLabel"] { color: var(--lpr-muted) !important; }
    [data-testid="stMetricValue"] { color: var(--lpr-navy) !important; font-weight: 760; }

    [data-testid="stDataFrame"], .stDataFrame, [data-testid="stExpander"],
    [data-testid="stTable"] {
        background: rgba(255,255,255,.98) !important;
        border: 1px solid var(--lpr-line) !important;
        border-radius: 16px !important;
        box-shadow: 0 8px 24px rgba(16,36,62,.045);
        overflow: hidden;
    }

    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, var(--lpr-teal), #0b9892) !important;
        border: 0 !important;
        color: #fff !important;
        border-radius: 10px !important;
        box-shadow: 0 7px 18px rgba(13,124,123,.20);
        font-weight: 650 !important;
    }
    .stButton > button:not([kind="primary"]) {
        border-color: #d7dfe8 !important;
        border-radius: 10px !important;
    }

    [data-baseweb="tab-list"] {
        gap: .25rem;
        background: rgba(255,255,255,.72);
        border: 1px solid var(--lpr-line);
        border-radius: 14px;
        padding: .3rem;
        box-shadow: 0 4px 18px rgba(16,36,62,.035);
    }
    [data-baseweb="tab"] {
        border-radius: 10px;
        padding-left: .9rem !important;
        padding-right: .9rem !important;
    }
    [data-baseweb="tab"][aria-selected="true"] {
        background: #fff;
        box-shadow: 0 3px 12px rgba(16,36,62,.08);
    }

    .lpr-brand-lockup {
        padding: .45rem .25rem .85rem;
        margin-bottom: .2rem;
    }
    .lpr-brand-eyebrow {
        font-size: .69rem;
        font-weight: 760;
        letter-spacing: .14em;
        text-transform: uppercase;
        color: #78d7d0 !important;
    }
    .lpr-brand-title {
        margin-top: .2rem;
        font-size: 1.14rem;
        line-height: 1.22;
        font-weight: 760;
        color: white !important;
    }
    .lpr-brand-subtitle {
        margin-top: .3rem;
        color: rgba(255,255,255,.66) !important;
        font-size: .77rem;
    }

    .lpr-exec-hero {
        position: relative;
        overflow: hidden;
        padding: 1.65rem 1.8rem;
        margin: .25rem 0 1rem;
        border-radius: 22px;
        color: #fff;
        background:
            radial-gradient(circle at 88% 20%, rgba(90,220,206,.28), transparent 18rem),
            radial-gradient(circle at 65% 120%, rgba(239,91,91,.16), transparent 22rem),
            linear-gradient(120deg, #10243e 0%, #174362 58%, #0d7978 130%);
        box-shadow: 0 18px 42px rgba(16,36,62,.16);
    }
    .lpr-exec-kicker {
        font-size: .72rem;
        font-weight: 760;
        text-transform: uppercase;
        letter-spacing: .16em;
        color: #8ce5dc;
    }
    .lpr-exec-hero h1 {
        color: #fff !important;
        margin: .25rem 0 .35rem;
        font-size: clamp(1.8rem, 3vw, 2.7rem);
        line-height: 1.08;
        max-width: 820px;
    }
    .lpr-exec-hero p {
        margin: 0;
        max-width: 850px;
        font-size: 1rem;
        color: rgba(255,255,255,.78) !important;
    }
    .lpr-pill-row { display:flex; gap:.45rem; flex-wrap:wrap; margin-top:1rem; }
    .lpr-pill {
        display:inline-flex;
        align-items:center;
        gap:.35rem;
        border:1px solid rgba(255,255,255,.18);
        background:rgba(255,255,255,.10);
        color:#fff;
        border-radius:999px;
        padding:.38rem .68rem;
        font-size:.76rem;
        font-weight:650;
    }
    .lpr-dot {
        width:.48rem; height:.48rem; border-radius:50%;
        background:#68e0c8; display:inline-block;
    }

    .lpr-crosslink {
        display:grid;
        grid-template-columns:minmax(0,1fr) auto;
        align-items:center;
        gap:1rem;
        background:rgba(255,255,255,.96);
        border:1px solid var(--lpr-line);
        border-radius:16px;
        padding:.85rem 1rem;
        margin:0 0 1rem;
        box-shadow:0 8px 24px rgba(16,36,62,.05);
    }
    .lpr-crosslink-title {
        color:var(--lpr-navy);
        font-size:.92rem;
        font-weight:760;
    }
    .lpr-crosslink-copy {
        margin-top:.12rem;
        color:var(--lpr-muted);
        font-size:.78rem;
        line-height:1.45;
    }
    .lpr-crosslink-actions { display:flex; flex-wrap:wrap; gap:.45rem; }
    .lpr-crosslink-link {
        display:inline-flex;
        align-items:center;
        justify-content:center;
        min-height:2.3rem;
        padding:.42rem .72rem;
        border-radius:9px;
        border:1px solid #d7dfe8;
        background:#fff;
        color:var(--lpr-navy) !important;
        text-decoration:none !important;
        font-size:.77rem;
        font-weight:720;
        white-space:nowrap;
    }
    .lpr-crosslink-link:hover {
        border-color:var(--lpr-teal);
        background:var(--lpr-teal-soft);
    }
    .lpr-crosslink-link.legacy {
        border-color:#4b5563;
        background:#2f3338;
        color:#fff !important;
    }
    @media (max-width:800px) {
        .lpr-crosslink { grid-template-columns:1fr; }
    }

    .lpr-section-label {
        margin: 1.25rem 0 .25rem;
        color: var(--lpr-teal);
        font-size: .72rem;
        font-weight: 780;
        text-transform: uppercase;
        letter-spacing: .12em;
    }
    .lpr-section-title {
        color: var(--lpr-navy);
        font-size: 1.38rem;
        font-weight: 760;
        margin: 0 0 .25rem;
    }
    .lpr-section-copy { color: var(--lpr-muted); margin: 0 0 .75rem; }

    .lpr-story-grid {
        display:grid;
        grid-template-columns:repeat(3,minmax(0,1fr));
        gap:.75rem;
        margin:.7rem 0 1rem;
    }
    .lpr-story-card {
        background:rgba(255,255,255,.96);
        border:1px solid var(--lpr-line);
        border-radius:16px;
        padding:1rem 1.05rem;
        box-shadow:0 8px 24px rgba(16,36,62,.045);
    }
    .lpr-story-no {
        display:inline-flex;
        width:1.7rem;
        height:1.7rem;
        align-items:center;
        justify-content:center;
        border-radius:9px;
        background:var(--lpr-teal-soft);
        color:var(--lpr-teal);
        font-size:.75rem;
        font-weight:800;
        margin-bottom:.55rem;
    }
    .lpr-story-card strong { color:var(--lpr-navy); display:block; font-size:.94rem; }
    .lpr-story-card span {
        color:var(--lpr-muted); font-size:.82rem; line-height:1.45;
        display:block; margin-top:.2rem;
    }

    .lpr-insight {
        border-left: 4px solid var(--lpr-teal);
        background: linear-gradient(90deg, #eef9f7, rgba(255,255,255,.94));
        border-radius: 0 14px 14px 0;
        padding: .82rem 1rem;
        margin: .55rem 0 1rem;
        color: var(--lpr-ink);
    }
    .lpr-insight strong { color: var(--lpr-navy); }

    .lpr-run-chip {
        display:inline-flex;
        align-items:center;
        gap:.45rem;
        border:1px solid #dbe4eb;
        background:#fff;
        border-radius:999px;
        padding:.34rem .64rem;
        color:var(--lpr-muted);
        font-size:.74rem;
        margin-bottom:.55rem;
    }

    .lpr-empty {
        text-align:center;
        background:#fff;
        border:1px dashed #cfd9e3;
        border-radius:18px;
        padding:2rem 1rem;
        color:var(--lpr-muted);
        margin:.6rem 0 1rem;
    }
    .lpr-empty strong {
        display:block; color:var(--lpr-navy); font-size:1.05rem;
        margin-bottom:.3rem;
    }

    @media (max-width: 900px) {
        .lpr-story-grid { grid-template-columns:1fr; }
        .lpr-exec-hero { padding:1.3rem; border-radius:18px; }
    }
    </style>"""
