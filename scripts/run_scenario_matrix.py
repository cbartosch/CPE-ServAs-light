from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass, fields
from pathlib import Path

from lpr_cpe_demo.config import Settings
from lpr_cpe_demo.domain import ApprovalDecisionInput, ApprovalKind, ApprovalStatus
from lpr_cpe_demo.workflow.service import WorkflowService

TERMINAL_STATES = frozenset({"closed", "escalated", "quarantined"})


@dataclass(frozen=True, slots=True)
class ScenarioExpectation:
    status: str
    actions: tuple[str, ...]
    remote: int
    self_help: int
    field: int
    mr: int
    cycles: int
    verification_passed: bool | None
    same_incident: bool
    work_order_records: int
    distinct_work_order_ids: int
    work_order_outcomes: tuple[str, ...]
    mr_records: int
    distinct_mr_ids: int
    mr_outcomes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    scenario: str
    status: str
    actions: tuple[str, ...]
    remote: int
    self_help: int
    field: int
    mr: int
    cycles: int
    verification_passed: bool | None
    same_incident: bool
    work_order_records: int
    distinct_work_order_ids: int
    work_order_outcomes: tuple[str, ...]
    mr_records: int
    distinct_mr_ids: int
    mr_outcomes: tuple[str, ...]


EXPECTED_RESULTS: dict[str, ScenarioExpectation] = {
    "bounded_remote_failure": ScenarioExpectation(
        status="escalated",
        actions=("remote_reprovision", "remote_reboot"),
        remote=2,
        self_help=0,
        field=0,
        mr=0,
        cycles=2,
        verification_passed=False,
        same_incident=True,
        work_order_records=0,
        distinct_work_order_ids=0,
        work_order_outcomes=(),
        mr_records=0,
        distinct_mr_ids=0,
        mr_outcomes=(),
    ),
    "hfc_common_cause": ScenarioExpectation(
        status="closed",
        actions=("plant_action",),
        remote=0,
        self_help=0,
        field=0,
        mr=0,
        cycles=1,
        verification_passed=True,
        same_incident=True,
        work_order_records=0,
        distinct_work_order_ids=0,
        work_order_outcomes=(),
        mr_records=0,
        distinct_mr_ids=0,
        mr_outcomes=(),
    ),
    "hfc_failed_plant_action_rerca": ScenarioExpectation(
        status="closed",
        actions=("dirty_boots_mr", "dirty_boots_mr"),
        remote=0,
        self_help=0,
        field=0,
        mr=2,
        cycles=2,
        verification_passed=True,
        same_incident=True,
        work_order_records=0,
        distinct_work_order_ids=0,
        work_order_outcomes=(),
        mr_records=2,
        distinct_mr_ids=1,
        mr_outcomes=("failed", "succeeded"),
    ),
    "hfc_remote_fail_clean_success": ScenarioExpectation(
        status="closed",
        actions=("remote_reprovision", "clean_boots"),
        remote=1,
        self_help=0,
        field=1,
        mr=0,
        cycles=2,
        verification_passed=True,
        same_incident=True,
        work_order_records=1,
        distinct_work_order_ids=1,
        work_order_outcomes=("succeeded",),
        mr_records=0,
        distinct_mr_ids=0,
        mr_outcomes=(),
    ),
    "hfc_remote_success": ScenarioExpectation(
        status="closed",
        actions=("remote_reprovision",),
        remote=1,
        self_help=0,
        field=0,
        mr=0,
        cycles=1,
        verification_passed=True,
        same_incident=True,
        work_order_records=0,
        distinct_work_order_ids=0,
        work_order_outcomes=(),
        mr_records=0,
        distinct_mr_ids=0,
        mr_outcomes=(),
    ),
    "hfc_self_help_success": ScenarioExpectation(
        status="closed",
        actions=("self_help",),
        remote=0,
        self_help=1,
        field=0,
        mr=0,
        cycles=1,
        verification_passed=True,
        same_incident=True,
        work_order_records=0,
        distinct_work_order_ids=0,
        work_order_outcomes=(),
        mr_records=0,
        distinct_mr_ids=0,
        mr_outcomes=(),
    ),
    "pon_odp_handover": ScenarioExpectation(
        status="closed",
        actions=("clean_boots", "dirty_boots_mr"),
        remote=0,
        self_help=0,
        field=1,
        mr=1,
        cycles=2,
        verification_passed=True,
        same_incident=True,
        work_order_records=1,
        distinct_work_order_ids=1,
        work_order_outcomes=("failed",),
        mr_records=1,
        distinct_mr_ids=1,
        mr_outcomes=("succeeded",),
    ),
    "pon_reverse_handover": ScenarioExpectation(
        status="closed",
        actions=("dirty_boots_mr", "clean_boots"),
        remote=0,
        self_help=0,
        field=1,
        mr=1,
        cycles=2,
        verification_passed=True,
        same_incident=True,
        work_order_records=1,
        distinct_work_order_ids=1,
        work_order_outcomes=("succeeded",),
        mr_records=1,
        distinct_mr_ids=1,
        mr_outcomes=("succeeded",),
    ),
    "rca_disagreement_gate": ScenarioExpectation(
        status="closed",
        actions=("clean_boots",),
        remote=0,
        self_help=0,
        field=1,
        mr=0,
        cycles=1,
        verification_passed=True,
        same_incident=True,
        work_order_records=1,
        distinct_work_order_ids=1,
        work_order_outcomes=("succeeded",),
        mr_records=0,
        distinct_mr_ids=0,
        mr_outcomes=(),
    ),
}


def _distinct_record_ids(records: list[dict[str, object]], key: str) -> int:
    return len({str(record[key]) for record in records if record.get(key)})


def _outcomes(records: list[dict[str, object]]) -> tuple[str, ...]:
    return tuple(str(record.get("outcome", "")) for record in records)


def run_case(service: WorkflowService, scenario_name: str) -> ScenarioResult:
    state = service.start_scenario(scenario_name)
    initial_incident_id = state.incident_id
    for _ in range(40):
        if state.status.value in TERMINAL_STATES:
            break
        approvals = service.list_approvals(
            status=ApprovalStatus.PENDING,
            incident_id=state.incident_id,
        )
        if approvals:
            approval = approvals[0]
            state = service.decide_approval(
                approval.approval_id,
                ApprovalDecisionInput(
                    decision="approve",
                    actor="scenario.matrix",
                    role=approval.requested_role,
                    reason="Approved by deterministic bundle scenario matrix.",
                    selected_domain=(
                        state.rca_domain_deterministic
                        if approval.kind == ApprovalKind.RCA_REVIEW
                        else None
                    ),
                ),
            )
        else:
            state = service.run_incident(state.incident_id)
    else:
        raise RuntimeError(f"{scenario_name} did not reach a terminal state")

    work_orders = [dict(item) for item in state.work_orders]
    mr_records = [dict(item) for item in state.mr_records]
    return ScenarioResult(
        scenario=scenario_name,
        status=state.status.value,
        actions=tuple(item.action_type.value for item in state.action_history),
        remote=state.remote_attempts,
        self_help=state.self_help_attempts,
        field=state.field_visits,
        mr=state.mr_attempts,
        cycles=state.diagnostic_cycles,
        verification_passed=state.verification_passed,
        same_incident=state.incident_id == initial_incident_id,
        work_order_records=len(work_orders),
        distinct_work_order_ids=_distinct_record_ids(work_orders, "work_order_id"),
        work_order_outcomes=_outcomes(work_orders),
        mr_records=len(mr_records),
        distinct_mr_ids=_distinct_record_ids(mr_records, "mr_id"),
        mr_outcomes=_outcomes(mr_records),
    )


def validate_results(results: list[ScenarioResult]) -> list[str]:
    errors: list[str] = []
    by_scenario: dict[str, ScenarioResult] = {}
    for result in results:
        if result.scenario in by_scenario:
            errors.append(f"duplicate scenario result: {result.scenario}")
        by_scenario[result.scenario] = result

    expected_names = set(EXPECTED_RESULTS)
    actual_names = set(by_scenario)
    for name in sorted(expected_names - actual_names):
        errors.append(f"missing scenario result: {name}")
    for name in sorted(actual_names - expected_names):
        errors.append(f"unexpected scenario result: {name}")

    for name in sorted(expected_names & actual_names):
        result = by_scenario[name]
        expected = EXPECTED_RESULTS[name]
        for field in fields(ScenarioExpectation):
            actual_value = getattr(result, field.name)
            expected_value = getattr(expected, field.name)
            if actual_value != expected_value:
                errors.append(
                    f"{name}.{field.name}: expected {expected_value!r}, "
                    f"got {actual_value!r}"
                )

    if results and all(not result.actions for result in results):
        errors.append("all scenarios completed with an empty action history")
    return errors


def _format_result(result: ScenarioResult) -> str:
    return (
        f"- {result.scenario}: {result.status} | actions={list(result.actions)} | "
        f"remote={result.remote} self_help={result.self_help} field={result.field} "
        f"mr={result.mr} cycles={result.cycles} | "
        f"work_orders={result.work_order_records}/"
        f"{result.distinct_work_order_ids} unique | "
        f"mr_records={result.mr_records}/{result.distinct_mr_ids} unique"
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="lpr-cpe-matrix-") as temp_dir:
        root = Path(temp_dir)
        settings = Settings(
            _env_file=None,
            app_environment="test",
            database_url=f"sqlite+pysqlite:///{root / 'matrix.db'}",
            langgraph_postgres_dsn="",
            mcp_use_network=False,
            mcp_effect_db=str(root / "effects.db"),
            use_langgraph=False,
            workflow_engine="portable",
            model_provider="fake",
            mcp_approval_signing_secret="scenario-matrix-secret",
        )
        service = WorkflowService(settings=settings)
        try:
            results = [run_case(service, item["name"]) for item in service.list_scenarios()]
        finally:
            service.close()

    for result in results:
        print(_format_result(result))
    errors = validate_results(results)
    if errors:
        print("Scenario matrix: FAIL", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("Scenario matrix: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
