"""Persistent model-status panel for the sidebar.

Why the sidebar and not a page
------------------------------
The Control Tower already carries an agent-status block, but it is one page of ten.
Someone on the Incident Workbench or the Decision Center sees numbers with no
indication of whether a model produced them. The sidebar is the only surface every
page shares, so it is the only place a global fact belongs.

Why the panel carries its own colours
-------------------------------------
The app injects a light theme globally and the Control Tower injects a dark one on
top, so the sidebar background differs by page. The panel therefore sets its own
background rather than inheriting, and `contrast_report` below checks every text
tone against that fixed background instead of against whichever theme happens to
be active. A status indicator that becomes unreadable on one page is worse than
none, because it is only unreadable when someone is looking.

The API key is never rendered. Only the variable name, and whether it is set.
"""

from __future__ import annotations

from .. import __version__
from ..agents.status import RECORDER, SOURCE_MEANING, describe_provider
from .theme import ContrastCheck, contrast_ratio

# The panel's own surface, independent of the active theme.
PANEL_BG = "#111A2B"
PANEL_INK = "#F1F5F9"
PANEL_MUTED = "#A9B6C7"

STATE_COLOUR = {"active": "#34D399", "bypassed": "#FBBF24", "absent": "#FB7185"}
STATE_LABEL = {"active": "ACTIVE", "bypassed": "BYPASSED", "absent": "NOT ACTIVE"}

WCAG_AA_BODY = 4.5
WCAG_AA_LARGE = 3.0


def panel_state(env: dict[str, str] | None = None) -> str:
    """`active`, `bypassed` when a key exists but a switch overrides it, or `absent`."""
    description = describe_provider(env)
    if description.active:
        return "active"
    return "bypassed" if description.key_present else "absent"


def contrast_report() -> list[ContrastCheck]:
    """Every tone the panel renders, against the panel's own background."""
    checks = [
        ContrastCheck("panel ink", PANEL_INK, PANEL_BG,
                      contrast_ratio(PANEL_INK, PANEL_BG), WCAG_AA_BODY),
        ContrastCheck("panel muted", PANEL_MUTED, PANEL_BG,
                      contrast_ratio(PANEL_MUTED, PANEL_BG), WCAG_AA_BODY),
    ]
    checks += [ContrastCheck(f"{state} indicator", colour, PANEL_BG,
                             contrast_ratio(colour, PANEL_BG), WCAG_AA_BODY)
               for state, colour in STATE_COLOUR.items()]
    return checks


def failing_checks() -> list[ContrastCheck]:
    return [c for c in contrast_report() if not c.passes]


def status_lines(env: dict[str, str] | None = None) -> dict[str, str]:
    """The text the panel shows, separated from the markup so it is testable."""
    description = describe_provider(env)
    state = panel_state(env)
    snapshot = RECORDER.snapshot(env)

    if state == "active":
        detail = "Activated by ANTHROPIC_API_KEY"
    elif state == "bypassed":
        detail = ("A key is set, but MODEL_PROVIDER or LLM_PROVIDER is fake, so the "
                  "model is bypassed")
    else:
        detail = "ANTHROPIC_API_KEY is not set"

    consequence = ("Agents decide; the deterministic rules check them."
                   if state == "active" else
                   "Every decision is the deterministic rules. Agent-derived "
                   "figures elsewhere are ASSUMED, not model-produced.")

    if snapshot["attempted"]:
        activity = (f"{snapshot['accepted']} accepted, {snapshot['fell_back']} fell "
                    f"back of {snapshot['attempted']} attempted")
    else:
        activity = "No decision attempted yet"

    return {
        "state": state,
        "label": STATE_LABEL[state],
        "model": description.model or "none",
        "detail": detail,
        "consequence": consequence,
        "activity": activity,
        "release": __version__,
    }


def html(env: dict[str, str] | None = None) -> str:
    lines = status_lines(env)
    colour = STATE_COLOUR[lines["state"]]
    return f"""
<div style="background:{PANEL_BG};border:1px solid rgba(255,255,255,.14);
            border-radius:10px;padding:10px 12px;margin:2px 0 10px">
  <div style="display:flex;align-items:center;gap:7px">
    <span style="width:9px;height:9px;border-radius:50%;background:{colour};
                 display:inline-block;flex:0 0 auto"></span>
    <span style="color:{colour};font-size:.68rem;font-weight:700;
                 letter-spacing:.07em">LLM {lines['label']}</span>
  </div>
  <div style="color:{PANEL_INK};font-size:.85rem;font-weight:600;
              margin-top:5px;word-break:break-all">{lines['model']}</div>
  <div style="color:{PANEL_MUTED};font-size:.72rem;margin-top:4px;
              line-height:1.4">{lines['detail']}</div>
  <div style="color:{PANEL_MUTED};font-size:.7rem;margin-top:6px;
              line-height:1.4;border-top:1px solid rgba(255,255,255,.10);
              padding-top:6px">{lines['activity']}</div>
  <div style="color:{PANEL_MUTED};font-size:.7rem;margin-top:5px;
              line-height:1.4">{lines['consequence']}</div>
  <div style="color:{PANEL_MUTED};font-size:.64rem;margin-top:7px;
              letter-spacing:.04em">Application release {lines['release']}</div>
</div>"""


def render() -> None:
    """Draw the panel. Import of streamlit is local so this module stays testable."""
    import streamlit as st

    st.markdown(html(), unsafe_allow_html=True)
    if panel_state() != "active":
        with st.expander("How to activate a model"):
            st.markdown(
                "Set `ANTHROPIC_API_KEY` in `.env` and make sure neither "
                "`MODEL_PROVIDER` nor `LLM_PROVIDER` is `fake`, then restart the "
                "container.\n\nWith no model the system still runs end to end on "
                "the deterministic rules: nothing stalls, no second-best "
                "recommendation is produced, and policy requires a human for every "
                "action because a fallback decision is itself a gate condition.")
            st.caption(" · ".join(f"`{k}` {v}" for k, v in SOURCE_MEANING.items()))
