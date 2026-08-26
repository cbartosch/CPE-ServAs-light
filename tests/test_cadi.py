"""Compatibility checks for the deprecated one-D CADI spelling."""

from __future__ import annotations

from lpr_cpe_demo.cadi import (
    CADI_CAPABILITIES,
    CadiCapability,
    cadi_contract,
    cadi_contract_rows,
)
from lpr_cpe_demo.caddi import (
    DVSUM_CADDI_CAPABILITIES,
    CaddiCapability,
    caddi_contract,
    caddi_contract_rows,
)


def test_legacy_python_api_delegates_to_dvsum_caddi() -> None:
    assert CadiCapability is CaddiCapability
    assert CADI_CAPABILITIES is DVSUM_CADDI_CAPABILITIES
    assert cadi_contract() == caddi_contract()
    assert cadi_contract_rows() == caddi_contract_rows()


def test_legacy_contract_is_explicitly_marked_deprecated() -> None:
    compatibility = cadi_contract()["compatibility"]
    assert compatibility["deprecated_name"] == "CADI"
    assert compatibility["deprecated_module"] == "lpr_cpe_demo.cadi"
    assert compatibility["deprecated_route"] == "/api/integrations/cadi"
    assert compatibility["canonical_route"] == "/api/integrations/caddi"
