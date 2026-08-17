from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from lpr_cpe_demo.config import Settings
from lpr_cpe_demo.controls import (
    authoritative_sla_deadline,
    derive_action_key,
    derive_approval_id,
    sla_authority_label,
)
from lpr_cpe_demo.domain import IncidentState, Technology


ROOT = Path(__file__).resolve().parents[1]


def test_action_key_is_stable_across_calls_and_process_restart() -> None:
    expected = derive_action_key(
        incident_id="INC-1007",
        action_type="dirty_boots_mr",
        attempt_index=1,
        delimiter_id="ODP-UTU-04-02",
    )
    code = (
        "from lpr_cpe_demo.controls import derive_action_key;"
        "print(derive_action_key(incident_id='INC-1007',"
        "action_type='dirty_boots_mr',attempt_index=1,"
        "delimiter_id='ODP-UTU-04-02'))"
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.stdout.strip() == expected


def test_action_key_changes_for_attempt_or_delimiter() -> None:
    first = derive_action_key(
        incident_id="INC-1", action_type="clean_boots", attempt_index=0, delimiter_id="TAP-1"
    )
    assert first != derive_action_key(
        incident_id="INC-1", action_type="clean_boots", attempt_index=1, delimiter_id="TAP-1"
    )
    assert first != derive_action_key(
        incident_id="INC-1", action_type="clean_boots", attempt_index=0, delimiter_id="TAP-2"
    )


def test_action_key_rejects_negative_attempt() -> None:
    with pytest.raises(ValueError):
        derive_action_key(incident_id="INC-1", action_type="remote", attempt_index=-1)


def test_approval_id_is_replay_stable() -> None:
    values = {
        "incident_id": "INC-1",
        "approval_kind": "dispatch",
        "action_type": "clean_boots",
        "attempt_index": 0,
        "delimiter_id": "TAP-1",
    }
    assert derive_approval_id(**values) == derive_approval_id(**values)


def test_parent_sla_is_authoritative_without_resetting_child_clock() -> None:
    own = datetime(2026, 8, 17, 13, 0, tzinfo=UTC)
    parent = own + timedelta(hours=3)
    assert authoritative_sla_deadline(
        own_deadline=own,
        sla_mode="inherits_parent",
        parent_deadline=parent,
    ) == parent
    assert sla_authority_label(
        sla_mode="inherits_parent", parent_incident_id="INC-PARENT"
    ) == "parent INC-PARENT"


def test_inherited_sla_requires_parent_deadline() -> None:
    with pytest.raises(ValueError):
        authoritative_sla_deadline(
            own_deadline=datetime.now(UTC),
            sla_mode="inherits_parent",
            parent_deadline=None,
        )


def test_incident_exposes_effective_sla_and_authority() -> None:
    own = datetime(2026, 8, 17, 13, 0, tzinfo=UTC)
    parent = own + timedelta(hours=2)
    state = IncidentState(
        incident_id="INC-1",
        scenario_name="test",
        title="test",
        technology=Technology.HFC,
        sla_deadline=own,
        parent_incident_id="INC-PARENT",
        parent_sla_deadline=parent,
        sla_mode="inherits_parent",
    )
    assert state.sla_deadline == own
    assert state.effective_sla_deadline == parent
    assert state.sla_authority == "parent INC-PARENT"


def test_mcp_profile_mismatch_fails_closed() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            mcp_profile="custom_stateless_2026",
            mcp_protocol_version="2025-11-25",
            mcp_strict_version=True,
        )


def test_timeline_event_is_replay_safe() -> None:
    from lpr_cpe_demo.domain import Stage

    state = IncidentState(
        incident_id="INC-REPLAY",
        scenario_name="test",
        title="test",
        technology=Technology.HFC,
        stage=Stage.EVIDENCE,
        total_steps=4,
    )
    for _ in range(2):
        state.append_event(
            event_type="evidence_assembled",
            title="Evidence assembled",
            detail="Three evidence items were assembled.",
        )
    assert len(state.timeline) == 1


def test_action_and_linked_records_are_replay_safe() -> None:
    from lpr_cpe_demo.domain import ActionResult, ActionType

    state = IncidentState(
        incident_id="INC-REPLAY",
        scenario_name="test",
        title="test",
        technology=Technology.PON,
    )
    action = ActionResult(
        action_type=ActionType.DIRTY_BOOTS_MR,
        action_id="act-1",
        outcome="simulated",
        summary="MR created",
        idempotency_key="idem-1",
        work_order_id="WO-1",
        mr_id="MR-1",
    )
    state.add_action_result(action)
    state.add_action_result(action.model_copy(update={"replayed": True}))
    state.add_work_order({"work_order_id": "WO-1", "status": "created"})
    state.add_work_order({"work_order_id": "WO-1", "status": "created"})
    state.add_work_order({"work_order_id": "WO-1", "status": "completed"})
    state.add_mr_record({"mr_id": "MR-1", "status": "created"})
    state.add_mr_record({"mr_id": "MR-1", "status": "created"})
    state.add_mr_record({"mr_id": "MR-1", "status": "closed"})

    assert len(state.action_history) == 1
    assert [item["status"] for item in state.work_orders] == ["created", "completed"]
    assert [item["status"] for item in state.mr_records] == ["created", "closed"]
