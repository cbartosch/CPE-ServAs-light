from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, Literal, TypedDict

from lpr_cpe_demo.config import Settings
from lpr_cpe_demo.domain import CaseStatus, IncidentState, Stage
from lpr_cpe_demo.workflow.engine import PortableWorkflowEngine


class GraphEnvelope(TypedDict):
    incident: dict[str, Any]


class LangGraphWorkflowEngine:
    """Durable LangGraph wrapper with dedicated human-interrupt nodes.

    The portable engine owns each deterministic process step. LangGraph owns thread persistence,
    conditional transitions and pause/resume. The approval interrupt node performs no external side
    effect before ``interrupt()``; execution occurs in a later portable step.
    """

    def __init__(self, portable: PortableWorkflowEngine, settings: Settings) -> None:
        self.portable = portable
        self.settings = settings
        self._checkpointer_context: AbstractContextManager[Any] | None = None
        self._checkpointer = self._build_checkpointer()
        self._graph = self._compile()

    def _build_checkpointer(self) -> Any:
        if self.settings.langgraph_postgres_dsn:
            from langgraph.checkpoint.postgres import PostgresSaver

            context = PostgresSaver.from_conn_string(self.settings.langgraph_postgres_dsn)
            saver = context.__enter__()
            saver.setup()
            self._checkpointer_context = context
            return saver
        from langgraph.checkpoint.memory import InMemorySaver

        return InMemorySaver()

    def _compile(self) -> Any:
        from langgraph.graph import END, START, StateGraph
        from langgraph.types import interrupt

        builder = StateGraph(GraphEnvelope)

        def step(envelope: GraphEnvelope) -> GraphEnvelope:
            state = IncidentState.model_validate(envelope["incident"])
            state = self.portable.run_one(state)
            return {"incident": state.model_dump(mode="json")}

        def approval_interrupt(envelope: GraphEnvelope) -> GraphEnvelope:
            state = IncidentState.model_validate(envelope["incident"])
            approval = self.portable.repository.get_approval(str(state.pending_approval_id))
            if approval is None:
                raise RuntimeError("Pending approval was not found in the approval store")
            # Pure payload construction before the exactly-one interrupt call.
            payload = {
                "approval_id": approval.approval_id,
                "incident_id": approval.incident_id,
                "kind": approval.kind.value,
                "action_type": approval.action_type,
                "required_role": approval.requested_role,
                "proposal": approval.proposal,
                "idempotency_key": approval.idempotency_key,
                "expires_at": approval.expires_at.isoformat(),
            }
            decision = interrupt(payload)
            # This code runs only after resume. No action is executed in this node.
            state.approval_result = dict(decision)
            state.status = CaseStatus.OPEN
            self.portable.repository.save_incident(state)
            return {"incident": state.model_dump(mode="json")}

        def route(envelope: GraphEnvelope) -> Literal["step", "approval", "stop"]:
            state = IncidentState.model_validate(envelope["incident"])
            if state.stage in {
                Stage.CLOSED,
                Stage.ESCALATED,
                Stage.QUARANTINED,
                Stage.POST_ACTION_QUARANTINE,
            }:
                return "stop"
            if state.stage == Stage.WAITING_APPROVAL and not state.approval_result:
                return "approval"
            return "step"

        builder.add_node("step", step)
        builder.add_node("approval", approval_interrupt)
        builder.add_conditional_edges(START, route, {"step": "step", "approval": "approval", "stop": END})
        builder.add_conditional_edges("step", route, {"step": "step", "approval": "approval", "stop": END})
        builder.add_edge("approval", "step")
        return builder.compile(checkpointer=self._checkpointer)

    @staticmethod
    def _config(incident_id: str) -> dict[str, Any]:
        return {
            "configurable": {"thread_id": incident_id},
            "recursion_limit": 100,
        }

    def run_until_pause(self, state: IncidentState) -> IncidentState:
        config = self._config(state.incident_id)
        self._graph.invoke({"incident": state.model_dump(mode="json")}, config=config)
        return self.get_state(state.incident_id)

    def resume(self, incident_id: str, decision: dict[str, Any]) -> IncidentState:
        from langgraph.types import Command

        config = self._config(incident_id)
        self._graph.invoke(Command(resume=decision), config=config)
        return self.get_state(incident_id)

    def get_state(self, incident_id: str) -> IncidentState:
        snapshot = self._graph.get_state(self._config(incident_id))
        values = snapshot.values
        return IncidentState.model_validate(values["incident"])

    def run_one(self, state: IncidentState) -> IncidentState:
        # One-step control is intentionally kept on the portable engine for deterministic tests.
        return self.portable.run_one(state)

    def close(self) -> None:
        if self._checkpointer_context is not None:
            self._checkpointer_context.__exit__(None, None, None)
            self._checkpointer_context = None
