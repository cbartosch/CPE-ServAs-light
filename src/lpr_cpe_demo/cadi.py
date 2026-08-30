"""Deprecated import compatibility for historical ``lpr_cpe_demo.cadi`` clients.

The product and all user-facing surfaces are canonically named **DvSum CADDI**.
New code must import :mod:`lpr_cpe_demo.caddi`.
"""

from __future__ import annotations

from typing import Any

from . import caddi as _caddi

CADI_CAPABILITIES = _caddi.DVSUM_CADDI_CAPABILITIES
CADDI_REQUIRED_LINEAGE = _caddi.CADDI_REQUIRED_LINEAGE
CadiCapability = _caddi.CaddiCapability
project_install_assurance_context = _caddi.project_install_assurance_context


def cadi_contract() -> dict[str, Any]:
    """Return the canonical DvSum CADDI contract for legacy import callers."""

    return _caddi.caddi_contract()


def cadi_contract_rows() -> list[dict[str, str]]:
    """Return canonical DvSum CADDI rows for legacy import callers."""

    return _caddi.caddi_contract_rows()


__all__ = [
    "CADDI_REQUIRED_LINEAGE",
    "CADI_CAPABILITIES",
    "CadiCapability",
    "cadi_contract",
    "cadi_contract_rows",
    "project_install_assurance_context",
]
