from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from lpr_cpe_demo.config import Settings
from lpr_cpe_demo.mcp_server.security import create_approval_token
from lpr_cpe_demo.mcp_server.store import EffectStore
from lpr_cpe_demo.mcp_server.tools import ToolRegistry, ToolRejection
from lpr_cpe_demo.workflow.scenarios import ScenarioCatalog


def _token(
    settings: Settings,
    *,
    approval_id: str,
    incident_id: str,
    action_type: str,
    idempotency_key: str,
) -> str:
    return create_approval_token(
        {
            "approval_id": approval_id,
            "incident_id": incident_id,
            "action_type": action_type,
            "idempotency_key": idempotency_key,
            "status": "approved",
            "exp": (datetime.now(UTC) + timedelta(minutes=10)).timestamp(),
        },
        settings.mcp_approval_signing_secret,
    )


def test_replaying_same_idempotency_key_returns_same_effect(settings: Settings, tmp_path) -> None:
    store = EffectStore(str(tmp_path / "mcp.db"))
    registry = ToolRegistry(settings=settings, catalog=ScenarioCatalog(settings=settings), store=store)
    arguments = {
        "incident_id": "INC-IDEMPOTENT",
        "scenario_name": "hfc_remote_success",
        "action_type": "remote_reprovision",
        "attempt": 1,
        "idempotency_key": "idem-001",
        "approval_token": _token(
            settings,
            approval_id="APR-001",
            incident_id="INC-IDEMPOTENT",
            action_type="remote_reprovision",
            idempotency_key="idem-001",
        ),
    }

    first = registry.call("simulate_remote_action", arguments)
    second = registry.call("simulate_remote_action", arguments)

    assert first["action_id"] == second["action_id"]
    assert first["replayed"] is False
    assert second["replayed"] is True


def test_consumed_approval_cannot_authorize_a_different_effect(settings: Settings, tmp_path) -> None:
    store = EffectStore(str(tmp_path / "mcp.db"))
    registry = ToolRegistry(settings=settings, catalog=ScenarioCatalog(settings=settings), store=store)
    token = _token(
        settings,
        approval_id="APR-USED",
        incident_id="INC-USED",
        action_type="remote_reprovision",
        idempotency_key="idem-first",
    )
    base = {
        "incident_id": "INC-USED",
        "scenario_name": "hfc_remote_success",
        "action_type": "remote_reprovision",
        "attempt": 1,
        "approval_token": token,
    }
    registry.call("simulate_remote_action", {**base, "idempotency_key": "idem-first"})

    second_token = _token(
        settings,
        approval_id="APR-USED",
        incident_id="INC-USED",
        action_type="remote_reprovision",
        idempotency_key="idem-second",
    )
    with pytest.raises(ToolRejection) as exc:
        registry.call(
            "simulate_remote_action",
            {
                **base,
                "idempotency_key": "idem-second",
                "approval_token": second_token,
            },
        )

    assert exc.value.code == "APPROVAL_ALREADY_CONSUMED"


def test_wrong_action_type_is_rejected_before_effect(settings: Settings, tmp_path) -> None:
    registry = ToolRegistry(
        settings=settings,
        catalog=ScenarioCatalog(settings=settings),
        store=EffectStore(str(tmp_path / "mcp.db")),
    )
    arguments = {
        "incident_id": "INC-WRONG",
        "scenario_name": "hfc_remote_success",
        "action_type": "plant_action",
        "attempt": 1,
        "idempotency_key": "idem-wrong",
        "approval_token": _token(
            settings,
            approval_id="APR-WRONG",
            incident_id="INC-WRONG",
            action_type="plant_action",
            idempotency_key="idem-wrong",
        ),
    }

    with pytest.raises(ToolRejection) as exc:
        registry.call("simulate_remote_action", arguments)

    assert exc.value.code == "TOOL_ACTION_MISMATCH"
