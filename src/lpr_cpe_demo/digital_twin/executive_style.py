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
        display:block !important;
        width:100% !important;
        min-width:0 !important;
        box-sizing:border-box;
        background:rgba(255,255,255,.96);
        border:1px solid var(--lpr-line);
        border-radius:16px;
        padding:.95rem 1rem;
        margin:0 0 1rem;
        box-shadow:0 8px 24px rgba(16,36,62,.05);
    }
    .lpr-crosslink-summary {
        display:block !important;
        width:100% !important;
        min-width:0 !important;
        max-width:76ch;
        box-sizing:border-box;
    }
    .lpr-crosslink-title {
        display:block;
        color:var(--lpr-navy);
        font-size:.92rem;
        font-weight:760;
        line-height:1.3;
        overflow-wrap:normal;
        word-break:normal;
    }
    .lpr-crosslink-copy {
        display:block;
        margin-top:.12rem;
        max-width:72ch;
        color:var(--lpr-muted);
        font-size:.78rem;
        line-height:1.45;
        overflow-wrap:break-word;
        word-break:normal;
    }
    .lpr-crosslink-actions {
        display:grid !important;
        grid-template-columns:repeat(auto-fit,minmax(min(100%,9rem),1fr)) !important;
        gap:.45rem;
        width:100% !important;
        min-width:0 !important;
        margin-top:.8rem;
        box-sizing:border-box;
    }
    .lpr-crosslink-link {
        display:inline-flex;
        width:100% !important;
        min-width:0;
        box-sizing:border-box;
        align-items:center;
        justify-content:center;
        min-height:2.45rem;
        padding:.46rem .68rem;
        border-radius:9px;
        border:1px solid #d7dfe8;
        background:#fff;
        color:var(--lpr-navy) !important;
        text-align:center;
        text-decoration:none !important;
        font-size:.77rem;
        font-weight:720;
        line-height:1.2;
        white-space:normal !important;
        overflow-wrap:break-word;
        word-break:normal;
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
    @media (max-width:680px) {
        .lpr-crosslink-actions {
            grid-template-columns:repeat(2,minmax(0,1fr)) !important;
        }
    }
    @media (max-width:460px) {
        .lpr-crosslink-actions {
            grid-template-columns:1fr !important;
        }
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

    /* Stage 4 uniform surface contract. Every analytical panel uses the same
       medium-grey background, border, radius and text hierarchy. */
    :root {
        --lpr-panel: #4B5057;
        --lpr-panel-raised: #555A61;
        --lpr-panel-border: #737981;
        --lpr-panel-text: #F5F7FA;
        --lpr-panel-muted: #D7DCE2;
        --lpr-panel-radius: 14px;
        --lpr-panel-gap: .75rem;
    }

    .stApp,
    [data-testid="stAppViewContainer"],
    [data-testid="stMain"] {
        background: #383C41 !important;
        color: var(--lpr-panel-text) !important;
    }
    [data-testid="stSidebar"] {
        background: #42464B !important;
        border-right: 1px solid var(--lpr-panel-border) !important;
    }
    .stApp h1, .stApp h2, .stApp h3,
    .stApp p, .stApp li, .stApp label, .stApp span {
        color: var(--lpr-panel-text);
    }
    .stCaption, [data-testid="stCaptionContainer"],
    [data-testid="stMetricLabel"] {
        color: var(--lpr-panel-muted) !important;
    }

    [data-testid="stMetric"],
    [data-testid="stDataFrame"], .stDataFrame,
    [data-testid="stExpander"], [data-testid="stTable"],
    [data-testid="stForm"], [data-testid="stVerticalBlockBorderWrapper"],
    [data-baseweb="tab-list"], .lpr-header, .lpr-exec-hero,
    .lpr-crosslink, .lpr-story-card, .lpr-insight,
    .lpr-run-chip, .lpr-empty {
        background: var(--lpr-panel) !important;
        border: 1px solid var(--lpr-panel-border) !important;
        border-radius: var(--lpr-panel-radius) !important;
        box-shadow: none !important;
        color: var(--lpr-panel-text) !important;
    }
    [data-testid="stMetric"] {
        min-height: 7.25rem;
        padding: 1rem 1.05rem !important;
    }
    [data-testid="stMetricValue"],
    .lpr-section-title, .lpr-story-card strong,
    .lpr-crosslink-title, .lpr-empty strong,
    .lpr-insight strong {
        color: var(--lpr-panel-text) !important;
    }
    .lpr-section-copy, .lpr-story-card span,
    .lpr-crosslink-copy, .lpr-run-chip {
        color: var(--lpr-panel-muted) !important;
    }
    .lpr-section-label, .lpr-exec-kicker,
    .lpr-brand-eyebrow {
        color: #7FE1D8 !important;
    }
    .lpr-exec-hero {
        padding: 1.35rem 1.45rem;
        margin: .25rem 0 1rem;
    }
    .lpr-exec-hero p {
        color: var(--lpr-panel-muted) !important;
    }
    .lpr-story-grid {
        gap: var(--lpr-panel-gap);
    }
    .lpr-story-card, .lpr-crosslink,
    .lpr-insight, .lpr-empty {
        padding: 1rem 1.05rem;
    }
    .lpr-insight {
        border-left: 4px solid #7FE1D8 !important;
    }
    [data-baseweb="tab"] {
        color: var(--lpr-panel-muted) !important;
    }
    [data-baseweb="tab"][aria-selected="true"] {
        background: var(--lpr-panel-raised) !important;
        color: var(--lpr-panel-text) !important;
        box-shadow: none !important;
    }
    .lpr-crosslink-link,
    .stButton > button:not([kind="primary"]) {
        background: var(--lpr-panel-raised) !important;
        border-color: var(--lpr-panel-border) !important;
        color: var(--lpr-panel-text) !important;
    }
    .lpr-crosslink-link:hover {
        border-color: #7FE1D8 !important;
        background: #5E646C !important;
    }
    header[data-testid="stHeader"],
    [data-testid="stHeader"],
    [data-testid="stToolbar"],
    [data-testid="stDecoration"] {
        background-color: #383C41 !important;
        background-image: none !important;
        border-bottom: 1px solid var(--lpr-panel-border) !important;
    }
    [data-testid="stToolbar"] {
        box-shadow: none !important;
    }
    [data-testid="stHeader"] *,
    [data-testid="stToolbar"] *,
    [data-testid="stToolbar"] button {
        color: var(--lpr-panel-text) !important;
    }
    [data-testid="stHeader"] svg,
    [data-testid="stToolbar"] svg {
        fill: currentColor !important;
    }
    [data-testid="stToolbar"] button:hover {
        background: var(--lpr-panel-raised) !important;
    }
    [data-baseweb="input"] > div,
    [data-baseweb="select"] > div,
    [data-baseweb="textarea"] > div,
    .stTextInput input, .stNumberInput input,
    .stTextArea textarea {
        background: #3F444A !important;
        border-color: var(--lpr-panel-border) !important;
        color: var(--lpr-panel-text) !important;
    }
    </style>"""
