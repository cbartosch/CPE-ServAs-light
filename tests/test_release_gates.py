from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import fields, replace
from pathlib import Path

from lpr_cpe_demo.config import Settings
from lpr_cpe_demo.domain import ApprovalKind, ApprovalRequest
from lpr_cpe_demo.mcp_server.security import verify_approval_for
from lpr_cpe_demo.workflow.engine import build_approval_token
from scripts.run_scenario_matrix import (
    EXPECTED_RESULTS,
    ScenarioResult,
    validate_results,
)

ROOT = Path(__file__).resolve().parents[1]


def _result_from_expectation(name: str) -> ScenarioResult:
    expected = EXPECTED_RESULTS[name]
    values = {
        field.name: getattr(expected, field.name)
        for field in fields(expected)
    }
    return ScenarioResult(scenario=name, **values)


def test_application_approval_token_binds_idempotency_key(settings: Settings) -> None:
    approval = ApprovalRequest(
        approval_id="APR-TOKEN-SCOPE",
        incident_id="INC-TOKEN-SCOPE",
        action_type="remote_reprovision",
        kind=ApprovalKind.REMOTE_ACTION,
        requested_role="noc_analyst",
        proposal={},
        idempotency_key="idem-token-scope",
    )

    token = build_approval_token(approval=approval, settings=settings)
    claims = verify_approval_for(
        token,
        settings.mcp_approval_signing_secret,
        incident_id=approval.incident_id,
        action_type=approval.action_type,
        idempotency_key=approval.idempotency_key,
    )

    assert claims["approval_id"] == approval.approval_id
    assert claims["idempotency_key"] == approval.idempotency_key


def test_scenario_matrix_validator_rejects_wrong_terminal_outcome() -> None:
    results = [_result_from_expectation(name) for name in EXPECTED_RESULTS]
    target_index = next(
        index
        for index, result in enumerate(results)
        if result.scenario == "hfc_remote_success"
    )
    results[target_index] = replace(
        results[target_index],
        status="escalated",
        actions=(),
        remote=0,
    )

    errors = validate_results(results)

    assert any("hfc_remote_success.status" in error for error in errors)
    assert any("hfc_remote_success.actions" in error for error in errors)
    assert any("hfc_remote_success.remote" in error for error in errors)


def test_scenario_matrix_script_proves_all_expected_outcomes() -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    completed = subprocess.run(
        [sys.executable, "scripts/run_scenario_matrix.py"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "Scenario matrix: PASS" in completed.stdout
    assert "hfc_remote_success: closed" in completed.stdout
    assert "bounded_remote_failure: escalated" in completed.stdout
    assert "actions=[]" not in completed.stdout
