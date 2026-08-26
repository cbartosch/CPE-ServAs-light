"""Deprecated compatibility shim for the former CADI spelling.

Use :mod:`lpr_cpe_demo.caddi` and the canonical name DvSum CADDI.
"""

from __future__ import annotations

from .caddi import (  # noqa: F401
    CADDI_CANONICAL_NAME,
    CADDI_EXPANSION,
    CADDI_SOURCE_LAYER,
    caddi_contract,
    project_install_assurance_context,
)


def cadi_contract():  # type: ignore[no-untyped-def]
    """Deprecated alias for :func:`caddi_contract`."""

    return caddi_contract()
