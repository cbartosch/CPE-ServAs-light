"""Loads the generated landmark artwork as data URIs.

Data URIs rather than served files because Streamlit does not expose an arbitrary
static path reliably across versions, and a CSS `url()` needs something the
browser can fetch. Both SVGs are a few kilobytes, so inlining costs nothing.

`enabled()` honours `UI_ARTWORK=off`, so a reviewer who finds the background
distracting can turn it off without a code change.
"""

from __future__ import annotations

import base64
import functools
import os
import pathlib

ASSETS = pathlib.Path(__file__).resolve().parent / "assets"
BAND = ASSETS / "landmark_band.svg"
WATERMARK = ASSETS / "landmark_watermark.svg"


def enabled() -> bool:
    return os.getenv("UI_ARTWORK", "on").strip().lower() not in {"off", "0", "false"}


@functools.lru_cache(maxsize=4)
def _data_uri(path: str) -> str:
    p = pathlib.Path(path)
    if not p.exists():
        return ""
    encoded = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def band_data_uri() -> str:
    return _data_uri(str(BAND))


def watermark_data_uri() -> str:
    return _data_uri(str(WATERMARK))
