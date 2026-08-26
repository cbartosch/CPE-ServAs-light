"""Compatibility aliases for the original single-D CADI project spelling.

New code should import :mod:`lpr_cpe_demo.dalli` and use ``DvSum DALLI``.
This module intentionally remains importable so existing Stage 1/2 code does
not break during the naming correction.
"""

from __future__ import annotations

from typing import Any

from . import dalli as _dalli

CADI_CAPABILITIES = _dalli.DVSUM_DALLI_CAPABILITIES
CADDI_REQUIRED_LINEAGE = _dalli.DALLI_REQUIRED_LINEAGE
CadiCapability = _dalli.DalliCapability
project_install_assurance_context = _dalli.project_install_assurance_context


def cadi_contract() -> dict[str, Any]:
    """Return the canonical DvSum DALLI contract under the legacy name."""

    return _dalli.dalli_contract()


def cadi_contract_rows() -> list[dict[str, str]]:
    """Return canonical DvSum DALLI rows under the legacy name."""

    return _dalli.dalli_contract_rows()


__all__ = [
    "CADDI_REQUIRED_LINEAGE",
    "CADI_CAPABILITIES",
    "CadiCapability",
    "cadi_contract",
    "cadi_contract_rows",
    "project_install_assurance_context",
]
