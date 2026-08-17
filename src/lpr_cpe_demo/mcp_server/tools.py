from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable

from lpr_cpe_demo.config import Settings, get_settings
from lpr_cpe_demo.domain import stable_id
from lpr_cpe_demo.mcp_server.security import ApprovalTokenError, verify_approval_token
from lpr_cpe_demo.mcp_server.store import EffectStore
from lpr_cpe_demo.workflow.scenarios import ScenarioCatalog


class ToolRejection(ValueError):
    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail or code


class ToolRegistry:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        catalog: ScenarioCatalog | None = None,
        store: EffectStore | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.catalog = catalog or ScenarioCatalog(settings=self.settings)
        self.store = store or EffectStore(self.settings.mcp_effect_db)
        self._tools: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "get_nxt_snapshot": self.get_nxt_snapshot,
            "get_topology": self.get_topology,
            "get_prior_incidents": self.get_prior_incidents,
            "run_read_only_test": self.run_read_only_test,
            "simulate_remote_action": self.simulate_remote_action,
            "simulate_self_help": self.simulate_self_help,
            "create_clean_boots_work_order": self.create_clean_boots_work_order,
            "create_or_update_mr": self.create_or_update_mr,
            "simulate_plant_action": self.simulate_plant_action,
            "simulate_joint_dispatch": self.simulate_joint_dispatch,
        }

    def list_tools(self) -> list[dict[str, Any]]:
        read_only = {
            "get_nxt_snapshot",
            "get_topology",
            "get_prior_incidents",
            "run_read_only_test",
        }
        descriptions = {
            "get_nxt_snapshot": "Return the simulated CommScope NXT snapshot and evidence for a demo scenario.",
            "get_topology": "Return customer-service-CPE-delimiter-plant topology for a demo scenario.",
            "get_prior_incidents": "Return simulated related incident and repair history.",
            "run_read_only_test": "Run a simulated read-only CPE or service diagnostic.",
            "simulate_remote_action": "Execute an approved simulated remote CPE action.",
            "simulate_self_help": "Record an approved simulated customer self-help session.",
            "create_clean_boots_work_order": "Create one approved and idempotent Clean Boots work order.",
            "create_or_update_mr": "Create or update one approved jTrack MR at the HFC tap or PON ODP.",
            "simulate_plant_action": "Execute an approved simulated Dirty Boots or plant repair.",
            "simulate_joint_dispatch": "Create one coordinated Clean/Dirty Boots dispatch.",
        }
        result = []
        for name in sorted(self._tools):
            result.append(
                {
                    "name": name,
                    "description": descriptions[name],
                    "inputSchema": {"type": "object", "additionalProperties": True},
                    "annotations": {
                        "readOnlyHint": name in read_only,
                        "destructiveHint": False,
                        "idempotentHint": True,
                    },
                }
            )
        return result

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolRejection("TOOL_NOT_FOUND", f"Unknown tool: {name}")
        return tool(arguments)

    def get_nxt_snapshot(self, arguments: dict[str, Any]) -> dict[str, Any]:
        scenario = self.catalog.get(str(arguments["scenario_name"]))
        cycles = list(scenario.get("evidence_by_cycle") or [scenario.get("evidence", [])])
        cycle = int(arguments.get("cycle", 0))
        evidence = cycles[min(max(cycle, 0), len(cycles) - 1)] if cycles else []
        return {
            "scenario": scenario["name"],
            "technology": scenario["technology"],
            "evidence": evidence,
            "alarm_state": "active",
            "observed_at": datetime.now(UTC).isoformat(),
            "source": "CommScope ServAssure NXT (simulated)",
        }

    def get_topology(self, arguments: dict[str, Any]) -> dict[str, Any]:
        scenario = self.catalog.get(str(arguments["scenario_name"]))
        return {"topology": scenario.get("topology", {}), "source": "LPR topology fixture"}

    def get_prior_incidents(self, arguments: dict[str, Any]) -> dict[str, Any]:
        scenario = self.catalog.get(str(arguments["scenario_name"]))
        return {
            "related_incidents": [],
            "existing_mr": None,
            "common_cause": bool(scenario.get("common_cause")),
            "parent_incident_id": scenario.get("parent_incident_id"),
        }

    def run_read_only_test(self, arguments: dict[str, Any]) -> dict[str, Any]:
        scenario = self.catalog.get(str(arguments["scenario_name"]))
        test_type = str(arguments.get("test_type", "service_path"))
        return {
            "test_id": stable_id(scenario["name"], test_type, prefix="test"),
            "test_type": test_type,
            "outcome": "abnormal" if scenario["name"] != "hfc_remote_success" else "profile_mismatch",
            "observed_at": datetime.now(UTC).isoformat(),
            "read_only": True,
        }

    def _approved_effect(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        effect: Callable[[dict[str, Any]], dict[str, Any]],
        expected_action_types: set[str],
    ) -> dict[str, Any]:
        incident_id = str(arguments.get("incident_id", ""))
        action_type = str(arguments.get("action_type", ""))
        approval_token = str(arguments.get("approval_token", ""))
        idempotency_key = str(arguments.get("idempotency_key", ""))
        if not incident_id or not action_type or not approval_token or not idempotency_key:
            raise ToolRejection("MISSING_EXECUTION_CONTROL")
        if action_type not in expected_action_types:
            raise ToolRejection("TOOL_ACTION_MISMATCH")

        prior = self.store.get(idempotency_key)
        if prior is not None:
            replay = dict(prior)
            replay["replayed"] = True
            return replay

        try:
            claims = verify_approval_token(
                approval_token,
                self.settings.mcp_approval_signing_secret,
            )
        except ApprovalTokenError as exc:
            raise ToolRejection(str(exc)) from exc

        if claims.get("incident_id") != incident_id:
            raise ToolRejection("APPROVAL_INCIDENT_MISMATCH")
        if claims.get("action_type") != action_type:
            raise ToolRejection("APPROVAL_ACTION_MISMATCH")
        if claims.get("status") != "approved":
            raise ToolRejection("APPROVAL_NOT_GRANTED")

        approval_id = str(claims.get("approval_id"))
        consumed = self.store.get_consumed_approval(approval_id)
        if consumed is not None and consumed != idempotency_key:
            raise ToolRejection("APPROVAL_ALREADY_CONSUMED")

        result = effect(arguments)
        result.update(
            {
                "incident_id": incident_id,
                "action_type": action_type,
                "approval_id": approval_id,
                "idempotency_key": idempotency_key,
                "replayed": False,
                "simulated": True,
                "executed_at": datetime.now(UTC).isoformat(),
            }
        )
        self.store.commit_effect(
            idempotency_key=idempotency_key,
            incident_id=incident_id,
            tool_name=tool_name,
            approval_id=approval_id,
            result=result,
        )
        return result

    def _scenario_outcome(self, arguments: dict[str, Any]) -> str:
        # Execution acknowledgement and service restoration are deliberately separate. The action tool
        # reports that the simulated operation ran; the workflow's verification stage decides whether it
        # restored service using verification_by_action.
        scenario = self.catalog.get(str(arguments["scenario_name"]))
        action_type = str(arguments["action_type"])
        attempt = int(arguments.get("attempt", 1))
        outcomes = scenario.get("execution_outcomes", {}).get(action_type, ["succeeded"])
        index = min(max(attempt - 1, 0), len(outcomes) - 1)
        return str(outcomes[index])

    def simulate_remote_action(self, arguments: dict[str, Any]) -> dict[str, Any]:
        def effect(args: dict[str, Any]) -> dict[str, Any]:
            outcome = self._scenario_outcome(args)
            return {
                "action_id": stable_id(args["incident_id"], args["action_type"], args.get("attempt", 1), prefix="act"),
                "outcome": outcome,
                "summary": f"Simulated remote action {args['action_type']} {outcome}.",
                "evidence": [
                    {
                        "kind": "remote_action_result",
                        "source": "CPE management simulator",
                        "summary": f"Remote action outcome: {outcome}",
                    }
                ],
            }

        return self._approved_effect(
            tool_name="simulate_remote_action",
            arguments=arguments,
            effect=effect,
            expected_action_types={"remote_reboot", "remote_reprovision"},
        )

    def simulate_self_help(self, arguments: dict[str, Any]) -> dict[str, Any]:
        def effect(args: dict[str, Any]) -> dict[str, Any]:
            outcome = self._scenario_outcome(args)
            return {
                "action_id": stable_id(args["incident_id"], "self_help", args.get("attempt", 1), prefix="act"),
                "outcome": outcome,
                "summary": f"Simulated bilingual self-help session {outcome}.",
            }

        return self._approved_effect(
            tool_name="simulate_self_help",
            arguments=arguments,
            effect=effect,
            expected_action_types={"self_help"},
        )

    def create_clean_boots_work_order(self, arguments: dict[str, Any]) -> dict[str, Any]:
        def effect(args: dict[str, Any]) -> dict[str, Any]:
            outcome = self._scenario_outcome(args)
            scenario = self.catalog.get(str(args["scenario_name"]))
            work_order_id = stable_id(args["incident_id"], "clean", args.get("attempt", 1), prefix="wo")
            result: dict[str, Any] = {
                "action_id": work_order_id,
                "work_order_id": work_order_id,
                "crew_type": "clean",
                "outcome": outcome,
                "summary": f"Clean Boots work order {outcome}.",
                "field_findings": {
                    "tests_completed": ["CPE", "power", "premise_wiring", "drop", "delimiter"],
                    "parts_used": ["drop connector"] if outcome == "succeeded" else [],
                    "photos": ["simulated://photo/1", "simulated://photo/2"],
                },
            }
            if scenario.get("handover"):
                result["field_findings"].update(scenario["handover"])
            return result

        return self._approved_effect(
            tool_name="create_clean_boots_work_order",
            arguments=arguments,
            effect=effect,
            expected_action_types={"clean_boots"},
        )

    def create_or_update_mr(self, arguments: dict[str, Any]) -> dict[str, Any]:
        def effect(args: dict[str, Any]) -> dict[str, Any]:
            outcome = self._scenario_outcome(args)
            mr_id = stable_id(args["incident_id"], "mr", args.get("delimiter", "unknown"), prefix="mr")
            return {
                "action_id": mr_id,
                "mr_id": mr_id,
                "outcome": outcome,
                "owner": args.get("owner", "Plant/OSP"),
                "delimiter": args.get("delimiter"),
                "summary": f"jTrack MR {mr_id} created/updated; plant action {outcome}.",
            }

        return self._approved_effect(
            tool_name="create_or_update_mr",
            arguments=arguments,
            effect=effect,
            expected_action_types={"dirty_boots_mr"},
        )

    def simulate_plant_action(self, arguments: dict[str, Any]) -> dict[str, Any]:
        def effect(args: dict[str, Any]) -> dict[str, Any]:
            outcome = self._scenario_outcome(args)
            return {
                "action_id": stable_id(args["incident_id"], "plant", args.get("attempt", 1), prefix="act"),
                "outcome": outcome,
                "summary": f"Simulated network/plant action {outcome}.",
            }

        return self._approved_effect(
            tool_name="simulate_plant_action",
            arguments=arguments,
            effect=effect,
            expected_action_types={"plant_action"},
        )

    def simulate_joint_dispatch(self, arguments: dict[str, Any]) -> dict[str, Any]:
        def effect(args: dict[str, Any]) -> dict[str, Any]:
            outcome = self._scenario_outcome(args)
            work_order_id = stable_id(args["incident_id"], "joint", args.get("attempt", 1), prefix="wo")
            return {
                "action_id": work_order_id,
                "work_order_id": work_order_id,
                "crew_type": "joint",
                "outcome": outcome,
                "summary": f"Joint Clean/Dirty Boots dispatch {outcome}.",
            }

        return self._approved_effect(
            tool_name="simulate_joint_dispatch",
            arguments=arguments,
            effect=effect,
            expected_action_types={"joint_dispatch"},
        )
