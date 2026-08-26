"""Deprecated compatibility shim for the corrected DvSum CADDI naming.

Use :mod:`lpr_cpe_demo.caddi` and ``/api/integrations/caddi`` in new code. The
old module and function names remain available so existing Stage 1 consumers and
bookmarks do not break during the nomenclature correction.
"""

from __future__ import annotations

from .caddi import (
    CADDI_REQUIRED_LINEAGE,
    CaddiCapability,
    DVSUM_CADDI_CAPABILITIES,
    caddi_contract,
    caddi_contract_rows,
)

CadiCapability = CaddiCapability
CADI_CAPABILITIES = DVSUM_CADDI_CAPABILITIES


def cadi_contract():
    """Return the canonical DvSum CADDI contract under the legacy function name."""

    return caddi_contract()


def cadi_contract_rows():
    """Return canonical DvSum CADDI rows under the legacy function name."""

    return caddi_contract_rows()


__all__ = [
    "CADDI_REQUIRED_LINEAGE",
    "CADI_CAPABILITIES",
    "CadiCapability",
    "cadi_contract",
    "cadi_contract_rows",
]
