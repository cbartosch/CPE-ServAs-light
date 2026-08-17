"""Formatting helpers for Streamlit markdown.

`usd` exists because of a real rendering bug. Streamlit renders markdown, and
markdown treats `$...$` as inline LaTeX. A string containing two dollar signs,
such as "costs $354 versus $19.67", is parsed as a maths span: the dollar signs
disappear and the text between them is typeset in a maths font. That is exactly
what happened to the benchmark citation, which rendered as "Headline range 150 to
300" with the currency symbols silently eaten.

Escaping as `\\$` prevents it. `st.metric` does not render markdown, so a bare
dollar sign is safe there and `usd` is unnecessary; it is required for
`st.write`, `st.markdown`, `st.info`, `st.warning`, `st.error`, `st.success` and
`st.caption`.
"""

from __future__ import annotations


def usd(amount: float, *, decimals: int = 0) -> str:
    """Currency for a markdown context, with the dollar sign escaped."""
    return f"\\${amount:,.{decimals}f}"


def usd_plain(amount: float, *, decimals: int = 0) -> str:
    """Currency for a non-markdown context such as st.metric."""
    return f"${amount:,.{decimals}f}"
