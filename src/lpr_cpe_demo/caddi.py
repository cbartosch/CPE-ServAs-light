"""Compatibility aliases for the former DvSum CADDI project spelling.

New code should import :mod:`lpr_cpe_demo.dalli` and use the display name
``DvSum DALLI``. The aliases remain to keep existing bookmarks, API clients,
and Stage 1/2 integrations working while the panels adopt the corrected label.
"""

from __future__ import annotations

from typing import Any

from . import dalli as _dalli

CADDI_CANONICAL_NAME = _dalli.DALLI_CANONICAL_NAME
CADDI_EXPANSION: str | None = None
CADDI_SOURCE_LAYER = _dalli.DALLI_SOURCE_LAYER
CADDI_REQUIRED_LINEAGE = _dalli.DALLI_REQUIRED_LINEAGE
DALLI_PUBLIC_COMPATIBILITY_NAME = _dalli.DALLI_PUBLIC_COMPATIBILITY_NAME
DVSUM_CADDI_CAPABILITIES = _dalli.DVSUM_DALLI_CAPABILITIES
CaddiCapability = _dalli.DalliCapability
project_install_assurance_context = _dalli.project_install_assurance_context


def caddi_contract() -> dict[str, Any]:
    """Return the canonical DvSum DALLI contract under the former function name."""

    return _dalli.dalli_contract()


def caddi_contract_rows() -> list[dict[str, str]]:
    """Return canonical DvSum DALLI rows under the former function name."""

    return _dalli.dalli_contract_rows()


def cadi_contract() -> dict[str, Any]:
    """Deprecated single-D alias retained for older imports."""

    return _dalli.dalli_contract()


def cadi_contract_rows() -> list[dict[str, str]]:
    """Deprecated single-D table alias retained for older imports."""

    return _dalli.dalli_contract_rows()


__all__ = [
    "CADDI_CANONICAL_NAME",
    "CADDI_EXPANSION",
    "CADDI_REQUIRED_LINEAGE",
    "CADDI_SOURCE_LAYER",
    "DALLI_PUBLIC_COMPATIBILITY_NAME",
    "DVSUM_CADDI_CAPABILITIES",
    "CaddiCapability",
    "caddi_contract",
    "caddi_contract_rows",
    "cadi_contract",
    "cadi_contract_rows",
    "project_install_assurance_context",
]
