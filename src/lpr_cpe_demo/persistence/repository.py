from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, Text, create_engine, delete, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from lpr_cpe_demo.config import Settings, get_settings
from lpr_cpe_demo.domain import (
    ApprovalRequest,
    ApprovalStatus,
    CaseStatus,
    IncidentState,
    Stage,
)


class Base(DeclarativeBase):
    pass


class IncidentRow(Base):
    __tablename__ = "incident_summary"

    incident_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    scenario_name: Mapped[str] = mapped_column(String(120), index=True)
    title: Mapped[str] = mapped_column(String(255))
    technology: Mapped[str] = mapped_column(String(16), index=True)
    priority: Mapped[str] = mapped_column(String(8), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    stage: Mapped[str] = mapped_column(String(64), index=True)
    current_owner: Mapped[str] = mapped_column(String(80), index=True)
    parent_incident_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    sla_mode: Mapped[str] = mapped_column(String(32), default="own")
    parent_sla_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sla_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    pending_approval_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    rca_domain_deterministic: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rca_domain_llm: Mapped[str | None] = mapped_column(String(64), nullable=True)
    domain_agreement: Mapped[str] = mapped_column(String(32), default="unknown")
    selected_action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    state_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ApprovalRow(Base):
    __tablename__ = "approval"

    approval_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    incident_id: Mapped[str] = mapped_column(String(80), index=True)
    action_type: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    requested_role: Mapped[str] = mapped_column(String(64))
    proposal_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    selected_option: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IdempotencyRow(Base):
    __tablename__ = "idempotency_record"

    idempotency_key: Mapped[str] = mapped_column(String(120), primary_key=True)
    incident_id: Mapped[str] = mapped_column(String(80), index=True)
    action_type: Mapped[str] = mapped_column(String(64))
    approval_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Repository:
    def __init__(self, settings: Settings | None = None, database_url: str | None = None) -> None:
        self.settings = settings or get_settings()
        self.database_url = database_url or self.settings.database_url
        connect_args: dict[str, Any] = {}
        if self.database_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        self.engine = create_engine(self.database_url, future=True, connect_args=connect_args)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False, class_=Session)

    def setup(self) -> None:
        Base.metadata.create_all(self.engine)

    def save_incident(self, state: IncidentState) -> IncidentState:
        state.updated_at = datetime.now(UTC)
        payload = state.model_dump(mode="json")
        with self.session_factory.begin() as session:
            row = session.get(IncidentRow, state.incident_id)
            values = {
                "scenario_name": state.scenario_name,
                "title": state.title,
                "technology": state.technology.value,
                "priority": state.priority,
                "status": state.status.value,
                "stage": state.stage.value,
                "current_owner": state.current_owner,
                "parent_incident_id": state.parent_incident_id,
                "sla_mode": state.sla_mode,
                "parent_sla_deadline": state.parent_sla_deadline,
                "sla_deadline": state.sla_deadline,
                "pending_approval_id": state.pending_approval_id,
                "rca_domain_deterministic": (
                    state.rca_domain_deterministic.value if state.rca_domain_deterministic else None
                ),
                "rca_domain_llm": state.rca_domain_llm.value if state.rca_domain_llm else None,
                "domain_agreement": state.domain_agreement,
                "selected_action": (
                    state.selected_action.action_type.value if state.selected_action else None
                ),
                "state_json": payload,
                "created_at": state.created_at,
                "updated_at": state.updated_at,
            }
            if row is None:
                row = IncidentRow(incident_id=state.incident_id, **values)
                session.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
        return state

    def get_incident(self, incident_id: str) -> IncidentState | None:
        with self.session_factory() as session:
            row = session.get(IncidentRow, incident_id)
            if row is None:
                return None
            return IncidentState.model_validate(row.state_json)

    def list_incidents(self, limit: int = 200) -> list[IncidentState]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(IncidentRow).order_by(IncidentRow.updated_at.desc()).limit(limit)
            ).all()
            return [IncidentState.model_validate(row.state_json) for row in rows]

    def save_approval(self, approval: ApprovalRequest) -> ApprovalRequest:
        with self.session_factory.begin() as session:
            row = session.get(ApprovalRow, approval.approval_id)
            values = {
                "incident_id": approval.incident_id,
                "action_type": approval.action_type,
                "kind": approval.kind.value,
                "status": approval.status.value,
                "requested_role": approval.requested_role,
                "proposal_json": approval.proposal,
                "idempotency_key": approval.idempotency_key,
                "created_at": approval.created_at,
                "expires_at": approval.expires_at,
                "decided_by": approval.decided_by,
                "decision_reason": approval.decision_reason,
                "selected_option": approval.selected_option,
                "decided_at": approval.decided_at,
                "consumed_at": approval.consumed_at,
            }
            if row is None:
                row = ApprovalRow(approval_id=approval.approval_id, **values)
                session.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
        return approval

    def get_approval(self, approval_id: str) -> ApprovalRequest | None:
        with self.session_factory() as session:
            row = session.get(ApprovalRow, approval_id)
            if row is None:
                return None
            return self._approval_from_row(row)

    def list_approvals(
        self,
        status: ApprovalStatus | None = None,
        incident_id: str | None = None,
    ) -> list[ApprovalRequest]:
        statement = select(ApprovalRow)
        if status is not None:
            statement = statement.where(ApprovalRow.status == status.value)
        if incident_id is not None:
            statement = statement.where(ApprovalRow.incident_id == incident_id)
        statement = statement.order_by(ApprovalRow.created_at.desc())
        with self.session_factory() as session:
            rows = session.scalars(statement).all()
            return [self._approval_from_row(row) for row in rows]

    def save_idempotent_result(
        self,
        *,
        idempotency_key: str,
        incident_id: str,
        action_type: str,
        approval_id: str | None,
        result: dict[str, Any],
    ) -> None:
        with self.session_factory.begin() as session:
            if session.get(IdempotencyRow, idempotency_key) is None:
                session.add(
                    IdempotencyRow(
                        idempotency_key=idempotency_key,
                        incident_id=incident_id,
                        action_type=action_type,
                        approval_id=approval_id,
                        result_json=result,
                        created_at=datetime.now(UTC),
                    )
                )

    def get_idempotent_result(self, idempotency_key: str) -> dict[str, Any] | None:
        with self.session_factory() as session:
            row = session.get(IdempotencyRow, idempotency_key)
            return dict(row.result_json) if row is not None else None

    def reset(self) -> None:
        with self.session_factory.begin() as session:
            session.execute(delete(IdempotencyRow))
            session.execute(delete(ApprovalRow))
            session.execute(delete(IncidentRow))

    def close(self) -> None:
        self.engine.dispose()

    def summary(self) -> dict[str, Any]:
        incidents = self.list_incidents()
        return {
            "open": sum(item.status == CaseStatus.OPEN for item in incidents),
            "waiting": sum(item.status == CaseStatus.WAITING for item in incidents),
            "closed": sum(item.status == CaseStatus.CLOSED for item in incidents),
            "escalated": sum(item.status == CaseStatus.ESCALATED for item in incidents),
            "pending_approvals": len(self.list_approvals(ApprovalStatus.PENDING)),
            "by_stage": {
                stage.value: sum(item.stage == stage for item in incidents) for stage in Stage
            },
            "by_technology": {
                "HFC": sum(item.technology.value == "HFC" for item in incidents),
                "PON": sum(item.technology.value == "PON" for item in incidents),
            },
        }

    @staticmethod
    def _approval_from_row(row: ApprovalRow) -> ApprovalRequest:
        return ApprovalRequest(
            approval_id=row.approval_id,
            incident_id=row.incident_id,
            action_type=row.action_type,
            kind=row.kind,
            status=row.status,
            requested_role=row.requested_role,
            proposal=dict(row.proposal_json),
            idempotency_key=row.idempotency_key,
            created_at=row.created_at,
            expires_at=row.expires_at,
            decided_by=row.decided_by,
            decision_reason=row.decision_reason,
            selected_option=row.selected_option,
            decided_at=row.decided_at,
            consumed_at=row.consumed_at,
        )
