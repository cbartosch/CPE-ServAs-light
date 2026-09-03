from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    inspect,
    insert,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from lpr_cpe_demo.assurance import (
    AssuranceEpisode,
    AssuranceEpisodeEvent,
    AssuranceOrigin,
    EpisodeStatus,
    InstallHandoffClaim,
    InstallHandoffConflictError,
    InstallHandoffState,
)
from lpr_cpe_demo.config import Settings, get_settings
from lpr_cpe_demo.domain import (
    ApprovalRequest,
    ApprovalStatus,
    CaseStatus,
    IncidentState,
    Stage,
)
from lpr_cpe_demo.quarantine import (
    PostActionQuarantine,
    QuarantineHealth,
    QuarantineObservation,
    QuarantineObservationConflictError,
    QuarantineStatus,
    QuarantineTransition,
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


class AssuranceEpisodeRow(Base):
    __tablename__ = "assurance_episode"

    episode_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    source_key: Mapped[str] = mapped_column(String(300), unique=True, index=True)
    origin: Mapped[str] = mapped_column(String(32), index=True)
    incident_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    install_run_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    install_watch_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    install_episode_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    service_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    device_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    technology: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    workflow_stage: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(255))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AssuranceEpisodeEventRow(Base):
    __tablename__ = "assurance_episode_event"

    event_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    episode_id: Mapped[str] = mapped_column(String(80), index=True)
    incident_id: Mapped[str] = mapped_column(String(80), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    actor: Mapped[str] = mapped_column(String(120))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class InstallHandoffClaimRow(Base):
    __tablename__ = "assurance_install_handoff"

    source_key: Mapped[str] = mapped_column(String(300), primary_key=True)
    episode_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    incident_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(32), index=True)
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class QuarantineRow(Base):
    __tablename__ = "assurance_quarantine"

    quarantine_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    episode_id: Mapped[str] = mapped_column(String(80), index=True)
    incident_id: Mapped[str] = mapped_column(String(80), index=True)
    action_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    action_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    pre_action_health_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    immediate_post_action_health_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    minimum_release_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    next_check_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    required_healthy_checks: Mapped[int] = mapped_column(Integer)
    healthy_checks: Mapped[int] = mapped_column(Integer)
    extension_count: Mapped[int] = mapped_column(Integer)
    max_extensions: Mapped[int] = mapped_column(Integer)
    check_interval_seconds: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class QuarantineObservationRow(Base):
    __tablename__ = "assurance_quarantine_observation"
    __table_args__ = (
        UniqueConstraint(
            "quarantine_id",
            "idempotency_key",
            name="uq_quarantine_observation_scope",
        ),
    )

    observation_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    quarantine_id: Mapped[str] = mapped_column(String(100), index=True)
    incident_id: Mapped[str] = mapped_column(String(80), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    health: Mapped[str] = mapped_column(String(32), index=True)
    source: Mapped[str] = mapped_column(String(120))
    actor: Mapped[str] = mapped_column(String(120))
    idempotency_key: Mapped[str] = mapped_column(String(160), index=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    transition: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


@dataclass(frozen=True)
class QuarantineMutation:
    quarantine: PostActionQuarantine
    observation: QuarantineObservation
    incident: IncidentState
    episode: AssuranceEpisode
    lineage_event: AssuranceEpisodeEvent


@dataclass(frozen=True)
class QuarantineApplyResult:
    created: bool
    quarantine: PostActionQuarantine
    observation: QuarantineObservation
    incident: IncidentState
    episode: AssuranceEpisode


QuarantineMutationBuilder = Callable[
    [
        PostActionQuarantine,
        IncidentState,
        AssuranceEpisode,
        QuarantineObservation | None,
    ],
    QuarantineMutation,
]


class Repository:
    def __init__(self, settings: Settings | None = None, database_url: str | None = None) -> None:
        self.settings = settings or get_settings()
        self.database_url = database_url or self.settings.database_url
        self._sqlite_quarantine_lock = RLock()
        connect_args: dict[str, Any] = {}
        if self.database_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
            connect_args["timeout"] = 30.0
        self.engine = create_engine(self.database_url, future=True, connect_args=connect_args)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False, class_=Session)

    def setup(self) -> None:
        Base.metadata.create_all(self.engine)
        self._migrate_quarantine_schema()

    @staticmethod
    def _legacy_observation_fingerprint(row: dict[str, Any]) -> str:
        observed_at = row.get("observed_at")
        if isinstance(observed_at, datetime):
            if observed_at.tzinfo is None:
                observed_at = observed_at.replace(tzinfo=UTC)
            observed_value: str | None = observed_at.astimezone(UTC).isoformat()
        else:
            observed_value = str(observed_at) if observed_at is not None else None
        metrics = row.get("metrics_json") or {}
        if isinstance(metrics, str):
            try:
                metrics = json.loads(metrics)
            except json.JSONDecodeError:
                metrics = {"legacy_raw": metrics}
        payload = {
            "actor": row.get("actor") or "legacy",
            "health": row.get("health") or QuarantineHealth.UNKNOWN.value,
            "idempotency_key": row.get("idempotency_key") or "",
            "metrics": metrics,
            "observed_at": observed_value,
            "quarantine_id": row.get("quarantine_id") or "",
            "source": row.get("source") or "legacy",
        }
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def _migrate_quarantine_schema(self) -> None:
        """Apply the additive/rebuild migration needed by the RC3 P2 contract."""

        dialect = self.engine.dialect.name
        if dialect == "sqlite":
            self._migrate_sqlite_quarantine_schema()
        elif dialect == "postgresql":
            self._migrate_postgres_quarantine_schema()

    def _migrate_sqlite_quarantine_schema(self) -> None:
        inspector = inspect(self.engine)
        tables = set(inspector.get_table_names())
        if "assurance_quarantine" not in tables:
            return
        quarantine_columns = {
            column["name"] for column in inspector.get_columns("assurance_quarantine")
        }
        with self.engine.begin() as connection:
            if "version" not in quarantine_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE assurance_quarantine "
                    "ADD COLUMN version INTEGER NOT NULL DEFAULT 0"
                )
            if "lease_token" not in quarantine_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE assurance_quarantine "
                    "ADD COLUMN lease_token VARCHAR(64)"
                )

        inspector = inspect(self.engine)
        observation_columns = {
            column["name"]
            for column in inspector.get_columns("assurance_quarantine_observation")
        }
        unique_constraints = inspector.get_unique_constraints(
            "assurance_quarantine_observation"
        )
        has_scoped_unique = any(
            constraint.get("column_names") == ["quarantine_id", "idempotency_key"]
            for constraint in unique_constraints
        )
        has_global_unique = any(
            constraint.get("column_names") == ["idempotency_key"]
            for constraint in unique_constraints
        )
        required_columns = {"received_at", "request_fingerprint", "lease_token"}
        if (
            required_columns.issubset(observation_columns)
            and has_scoped_unique
            and not has_global_unique
        ):
            return

        with self.engine.begin() as connection:
            rows = connection.execute(
                text(
                    "SELECT observation_id, quarantine_id, incident_id, observed_at, "
                    "health, source, actor, idempotency_key, metrics_json, transition, "
                    "created_at FROM assurance_quarantine_observation"
                )
            ).mappings().all()
            connection.exec_driver_sql(
                "DROP TABLE IF EXISTS assurance_quarantine_observation_rc3"
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE assurance_quarantine_observation_rc3 (
                    observation_id VARCHAR(100) NOT NULL PRIMARY KEY,
                    quarantine_id VARCHAR(100) NOT NULL,
                    incident_id VARCHAR(80) NOT NULL,
                    observed_at DATETIME NOT NULL,
                    received_at DATETIME NOT NULL,
                    health VARCHAR(32) NOT NULL,
                    source VARCHAR(120) NOT NULL,
                    actor VARCHAR(120) NOT NULL,
                    idempotency_key VARCHAR(160) NOT NULL,
                    request_fingerprint VARCHAR(64) NOT NULL,
                    lease_token VARCHAR(64),
                    metrics_json JSON NOT NULL,
                    transition VARCHAR(32) NOT NULL,
                    created_at DATETIME NOT NULL,
                    CONSTRAINT uq_quarantine_observation_scope
                        UNIQUE (quarantine_id, idempotency_key)
                )
                """
            )
            insert_statement = text(
                """
                INSERT INTO assurance_quarantine_observation_rc3 (
                    observation_id, quarantine_id, incident_id, observed_at,
                    received_at, health, source, actor, idempotency_key,
                    request_fingerprint, lease_token, metrics_json, transition,
                    created_at
                ) VALUES (
                    :observation_id, :quarantine_id, :incident_id, :observed_at,
                    :received_at, :health, :source, :actor, :idempotency_key,
                    :request_fingerprint, NULL, :metrics_json, :transition,
                    :created_at
                )
                """
            )
            for raw in rows:
                row = dict(raw)
                row["received_at"] = row.get("created_at") or row["observed_at"]
                row["request_fingerprint"] = self._legacy_observation_fingerprint(row)
                connection.execute(insert_statement, row)
            connection.exec_driver_sql("DROP TABLE assurance_quarantine_observation")
            connection.exec_driver_sql(
                "ALTER TABLE assurance_quarantine_observation_rc3 "
                "RENAME TO assurance_quarantine_observation"
            )
            for column in (
                "quarantine_id",
                "incident_id",
                "observed_at",
                "received_at",
                "health",
                "idempotency_key",
                "transition",
            ):
                connection.exec_driver_sql(
                    "CREATE INDEX IF NOT EXISTS "
                    f"ix_assurance_quarantine_observation_{column} "
                    "ON assurance_quarantine_observation "
                    f"({column})"
                )

    def _migrate_postgres_quarantine_schema(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE assurance_quarantine "
                    "ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 0"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE assurance_quarantine "
                    "ADD COLUMN IF NOT EXISTS lease_token VARCHAR(64)"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE assurance_quarantine_observation "
                    "ADD COLUMN IF NOT EXISTS received_at TIMESTAMPTZ"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE assurance_quarantine_observation "
                    "ADD COLUMN IF NOT EXISTS request_fingerprint VARCHAR(64)"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE assurance_quarantine_observation "
                    "ADD COLUMN IF NOT EXISTS lease_token VARCHAR(64)"
                )
            )
            rows = connection.execute(
                text(
                    "SELECT observation_id, quarantine_id, incident_id, observed_at, "
                    "health, source, actor, idempotency_key, metrics_json, transition, "
                    "created_at FROM assurance_quarantine_observation "
                    "WHERE received_at IS NULL OR request_fingerprint IS NULL"
                )
            ).mappings().all()
            for raw in rows:
                row = dict(raw)
                connection.execute(
                    text(
                        "UPDATE assurance_quarantine_observation "
                        "SET received_at = COALESCE(received_at, :received_at), "
                        "request_fingerprint = COALESCE("
                        "request_fingerprint, :request_fingerprint) "
                        "WHERE observation_id = :observation_id"
                    ),
                    {
                        "observation_id": row["observation_id"],
                        "received_at": row.get("created_at") or row["observed_at"],
                        "request_fingerprint": self._legacy_observation_fingerprint(row),
                    },
                )
            connection.execute(
                text(
                    "ALTER TABLE assurance_quarantine_observation "
                    "ALTER COLUMN received_at SET NOT NULL"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE assurance_quarantine_observation "
                    "ALTER COLUMN request_fingerprint SET NOT NULL"
                )
            )
            old_constraints = connection.execute(
                text(
                    """
                    SELECT constraint_name
                    FROM information_schema.table_constraints
                    WHERE table_schema = current_schema()
                      AND table_name = 'assurance_quarantine_observation'
                      AND constraint_type = 'UNIQUE'
                    """
                )
            ).scalars().all()
            for constraint_name in old_constraints:
                columns = connection.execute(
                    text(
                        """
                        SELECT column_name
                        FROM information_schema.constraint_column_usage
                        WHERE table_schema = current_schema()
                          AND table_name = 'assurance_quarantine_observation'
                          AND constraint_name = :constraint_name
                        ORDER BY column_name
                        """
                    ),
                    {"constraint_name": constraint_name},
                ).scalars().all()
                if columns == ["idempotency_key"]:
                    quoted = constraint_name.replace('"', '""')
                    connection.exec_driver_sql(
                        "ALTER TABLE assurance_quarantine_observation "
                        f'DROP CONSTRAINT "{quoted}"'
                    )

            # RC2 used ``unique=True`` together with ``index=True`` on the
            # idempotency column. SQLAlchemy renders that combination as a
            # standalone unique PostgreSQL index rather than a table
            # constraint. Remove that legacy shape as well, otherwise an
            # upgraded database would still reject the same adapter-local key
            # when it is used by a different quarantine.
            old_unique_indexes = connection.execute(
                text(
                    """
                    SELECT index_class.relname AS index_name,
                           array_agg(
                               attribute.attname
                               ORDER BY key_column.ordinality
                           ) AS column_names
                    FROM pg_class AS table_class
                    JOIN pg_namespace AS namespace
                      ON namespace.oid = table_class.relnamespace
                    JOIN pg_index AS index_metadata
                      ON index_metadata.indrelid = table_class.oid
                    JOIN pg_class AS index_class
                      ON index_class.oid = index_metadata.indexrelid
                    JOIN LATERAL unnest(index_metadata.indkey)
                         WITH ORDINALITY AS key_column(attnum, ordinality)
                      ON TRUE
                    JOIN pg_attribute AS attribute
                      ON attribute.attrelid = table_class.oid
                     AND attribute.attnum = key_column.attnum
                    WHERE namespace.nspname = current_schema()
                      AND table_class.relname =
                          'assurance_quarantine_observation'
                      AND index_metadata.indisunique
                      AND NOT index_metadata.indisprimary
                    GROUP BY index_class.relname
                    """
                )
            ).mappings().all()
            for index in old_unique_indexes:
                if list(index["column_names"] or []) == ["idempotency_key"]:
                    quoted = str(index["index_name"]).replace('"', '""')
                    connection.exec_driver_sql(
                        f'DROP INDEX IF EXISTS "{quoted}"'
                    )
            scoped_exists = connection.execute(
                text(
                    """
                    SELECT 1
                    FROM information_schema.table_constraints
                    WHERE table_schema = current_schema()
                      AND table_name = 'assurance_quarantine_observation'
                      AND constraint_name = 'uq_quarantine_observation_scope'
                    """
                )
            ).scalar_one_or_none()
            if scoped_exists is None:
                connection.execute(
                    text(
                        "ALTER TABLE assurance_quarantine_observation "
                        "ADD CONSTRAINT uq_quarantine_observation_scope "
                        "UNIQUE (quarantine_id, idempotency_key)"
                    )
                )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS "
                    "ix_assurance_quarantine_observation_received_at "
                    "ON assurance_quarantine_observation (received_at)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_assurance_quarantine_lease_token "
                    "ON assurance_quarantine (lease_token)"
                )
            )

    def _insert_do_nothing(
        self,
        session: Session,
        row_type: type[Any],
        values: dict[str, Any],
    ) -> bool:
        """Insert one row without leaking a concurrent uniqueness conflict."""

        dialect = self.engine.dialect.name
        if dialect == "postgresql":
            statement = postgresql_insert(row_type).values(**values).on_conflict_do_nothing()
            return session.execute(statement).rowcount == 1
        if dialect == "sqlite":
            statement = sqlite_insert(row_type).values(**values).on_conflict_do_nothing()
            return session.execute(statement).rowcount == 1
        try:
            with session.begin_nested():
                session.execute(insert(row_type).values(**values))
            return True
        except IntegrityError:
            return False

    @staticmethod
    def _incident_values(state: IncidentState) -> dict[str, Any]:
        return {
            "incident_id": state.incident_id,
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
                state.rca_domain_deterministic.value
                if state.rca_domain_deterministic
                else None
            ),
            "rca_domain_llm": state.rca_domain_llm.value if state.rca_domain_llm else None,
            "domain_agreement": state.domain_agreement,
            "selected_action": (
                state.selected_action.action_type.value if state.selected_action else None
            ),
            "state_json": state.model_dump(mode="json"),
            "created_at": state.created_at,
            "updated_at": state.updated_at,
        }

    @staticmethod
    def _assurance_episode_values(episode: AssuranceEpisode) -> dict[str, Any]:
        return {
            "episode_id": episode.episode_id,
            "source_key": episode.source_key,
            "origin": episode.origin.value,
            "incident_id": episode.incident_id,
            "install_run_id": episode.install_run_id,
            "install_watch_id": episode.install_watch_id,
            "install_episode_id": episode.install_episode_id,
            "service_id": episode.service_id,
            "device_id": episode.device_id,
            "technology": episode.technology,
            "status": episode.status.value,
            "workflow_stage": episode.workflow_stage,
            "title": episode.title,
            "metadata_json": episode.metadata,
            "created_at": episode.created_at,
            "updated_at": episode.updated_at,
        }

    @staticmethod
    def _assurance_event_values(event: AssuranceEpisodeEvent) -> dict[str, Any]:
        return {
            "event_id": event.event_id,
            "episode_id": event.episode_id,
            "incident_id": event.incident_id,
            "event_type": event.event_type,
            "actor": event.actor,
            "occurred_at": event.occurred_at,
            "payload_json": event.payload,
        }

    @staticmethod
    def _quarantine_values(quarantine: PostActionQuarantine) -> dict[str, Any]:
        return {
            "quarantine_id": quarantine.quarantine_id,
            "episode_id": quarantine.episode_id,
            "incident_id": quarantine.incident_id,
            "action_id": quarantine.action_id,
            "action_type": quarantine.action_type,
            "status": quarantine.status.value,
            "pre_action_health_json": quarantine.pre_action_health,
            "immediate_post_action_health_json": quarantine.immediate_post_action_health,
            "started_at": quarantine.started_at,
            "minimum_release_at": quarantine.minimum_release_at,
            "next_check_at": quarantine.next_check_at,
            "required_healthy_checks": quarantine.required_healthy_checks,
            "healthy_checks": quarantine.healthy_checks,
            "extension_count": quarantine.extension_count,
            "max_extensions": quarantine.max_extensions,
            "check_interval_seconds": quarantine.check_interval_seconds,
            "version": quarantine.version,
            "lease_owner": quarantine.lease_owner,
            "lease_token": quarantine.lease_token,
            "lease_until": quarantine.lease_until,
            "completed_at": quarantine.completed_at,
            "metadata_json": quarantine.metadata,
            "created_at": quarantine.created_at,
            "updated_at": quarantine.updated_at,
        }

    @staticmethod
    def _quarantine_observation_values(
        observation: QuarantineObservation,
    ) -> dict[str, Any]:
        return {
            "observation_id": observation.observation_id,
            "quarantine_id": observation.quarantine_id,
            "incident_id": observation.incident_id,
            "observed_at": observation.observed_at,
            "received_at": observation.received_at,
            "health": observation.health.value,
            "source": observation.source,
            "actor": observation.actor,
            "idempotency_key": observation.idempotency_key,
            "request_fingerprint": observation.request_fingerprint,
            "lease_token": observation.lease_token,
            "metrics_json": observation.metrics,
            "transition": observation.transition.value,
            "created_at": observation.created_at,
        }

    @staticmethod
    def _apply_values(row: Any, values: dict[str, Any], *, primary_key: str) -> None:
        for key, value in values.items():
            if key != primary_key:
                setattr(row, key, value)

    def save_incident(self, state: IncidentState) -> IncidentState:
        state.updated_at = datetime.now(UTC)
        with self.session_factory.begin() as session:
            row = session.get(IncidentRow, state.incident_id)
            values = self._incident_values(state)
            values.pop("incident_id")
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

    def save_assurance_episode(self, episode: AssuranceEpisode) -> AssuranceEpisode:
        episode.updated_at = datetime.now(UTC)
        with self.session_factory.begin() as session:
            row = session.get(AssuranceEpisodeRow, episode.episode_id)
            if row is None:
                row = session.scalar(
                    select(AssuranceEpisodeRow).where(
                        AssuranceEpisodeRow.source_key == episode.source_key
                    )
                )
            values = self._assurance_episode_values(episode)
            values.pop("episode_id")
            if row is None:
                session.add(AssuranceEpisodeRow(episode_id=episode.episode_id, **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
        return episode

    def get_assurance_episode(self, episode_id: str) -> AssuranceEpisode | None:
        with self.session_factory() as session:
            row = session.get(AssuranceEpisodeRow, episode_id)
            return self._assurance_episode_from_row(row) if row is not None else None

    def get_assurance_episode_by_source(self, source_key: str) -> AssuranceEpisode | None:
        with self.session_factory() as session:
            row = session.scalar(
                select(AssuranceEpisodeRow).where(
                    AssuranceEpisodeRow.source_key == source_key
                )
            )
            return self._assurance_episode_from_row(row) if row is not None else None

    def get_assurance_episode_by_incident(self, incident_id: str) -> AssuranceEpisode | None:
        with self.session_factory() as session:
            row = session.scalar(
                select(AssuranceEpisodeRow).where(
                    AssuranceEpisodeRow.incident_id == incident_id
                )
            )
            return self._assurance_episode_from_row(row) if row is not None else None

    def list_assurance_episodes(self, limit: int = 200) -> list[AssuranceEpisode]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(AssuranceEpisodeRow)
                .order_by(AssuranceEpisodeRow.updated_at.desc())
                .limit(limit)
            ).all()
            return [self._assurance_episode_from_row(row) for row in rows]

    def append_assurance_event(
        self,
        event: AssuranceEpisodeEvent,
    ) -> AssuranceEpisodeEvent:
        with self.session_factory.begin() as session:
            self._insert_do_nothing(
                session,
                AssuranceEpisodeEventRow,
                self._assurance_event_values(event),
            )
        return event

    def list_assurance_events(self, episode_id: str) -> list[AssuranceEpisodeEvent]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(AssuranceEpisodeEventRow)
                .where(AssuranceEpisodeEventRow.episode_id == episode_id)
                .order_by(AssuranceEpisodeEventRow.occurred_at.asc())
            ).all()
            return [
                AssuranceEpisodeEvent(
                    event_id=row.event_id,
                    episode_id=row.episode_id,
                    incident_id=row.incident_id,
                    event_type=row.event_type,
                    actor=row.actor,
                    occurred_at=row.occurred_at,
                    payload=dict(row.payload_json or {}),
                )
                for row in rows
            ]

    def claim_install_handoff(
        self,
        *,
        request_fingerprint: str,
        incident: IncidentState,
        episode: AssuranceEpisode,
        claim_event: AssuranceEpisodeEvent,
    ) -> tuple[InstallHandoffClaim, bool]:
        """Atomically create or adopt a canonical install handoff.

        The durable claim, incident, assurance episode and first audit event are
        committed together. Concurrent callers use conflict-free inserts and
        converge on the same source identity.
        """

        now = datetime.now(UTC)
        incident.updated_at = now
        episode.updated_at = now
        claim_values = {
            "source_key": episode.source_key,
            "episode_id": episode.episode_id,
            "incident_id": episode.incident_id,
            "request_fingerprint": request_fingerprint,
            "state": InstallHandoffState.CLAIMED.value,
            "lease_owner": None,
            "lease_until": None,
            "attempt_count": 0,
            "last_error": None,
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
        }

        with self.session_factory.begin() as session:
            self._insert_do_nothing(session, InstallHandoffClaimRow, claim_values)
            claim_row = session.get(InstallHandoffClaimRow, episode.source_key)
            if claim_row is None:
                raise RuntimeError("INSTALL_HANDOFF_CLAIM_NOT_VISIBLE")
            if claim_row.request_fingerprint != request_fingerprint:
                raise InstallHandoffConflictError(
                    "INSTALL_HANDOFF_SOURCE_PAYLOAD_CONFLICT"
                )
            if (
                claim_row.episode_id != episode.episode_id
                or claim_row.incident_id != episode.incident_id
            ):
                raise InstallHandoffConflictError(
                    "INSTALL_HANDOFF_SOURCE_IDENTITY_CONFLICT"
                )

            existing_episode = session.scalar(
                select(AssuranceEpisodeRow).where(
                    AssuranceEpisodeRow.source_key == episode.source_key
                )
            )
            episode_created = existing_episode is None
            if existing_episode is not None:
                expected = {
                    "episode_id": episode.episode_id,
                    "incident_id": episode.incident_id,
                    "origin": episode.origin.value,
                    "install_run_id": episode.install_run_id,
                    "install_watch_id": episode.install_watch_id,
                    "install_episode_id": episode.install_episode_id,
                    "service_id": episode.service_id,
                    "device_id": episode.device_id,
                    "technology": episode.technology,
                }
                actual = {key: getattr(existing_episode, key) for key in expected}
                if actual != expected:
                    raise InstallHandoffConflictError(
                        "INSTALL_HANDOFF_EPISODE_IDENTITY_CONFLICT"
                    )

            self._insert_do_nothing(
                session,
                IncidentRow,
                self._incident_values(incident),
            )
            self._insert_do_nothing(
                session,
                AssuranceEpisodeRow,
                self._assurance_episode_values(episode),
            )
            self._insert_do_nothing(
                session,
                AssuranceEpisodeEventRow,
                self._assurance_event_values(claim_event),
            )
            session.flush()

            stored_episode = session.scalar(
                select(AssuranceEpisodeRow).where(
                    AssuranceEpisodeRow.source_key == episode.source_key
                )
            )
            stored_incident = session.get(IncidentRow, episode.incident_id)
            if stored_episode is None or stored_incident is None:
                raise RuntimeError("INSTALL_HANDOFF_CANONICAL_ROWS_MISSING")
            if (
                stored_episode.episode_id != episode.episode_id
                or stored_episode.incident_id != episode.incident_id
            ):
                raise InstallHandoffConflictError(
                    "INSTALL_HANDOFF_CANONICAL_ROW_CONFLICT"
                )
            claim = self._install_handoff_claim_from_row(claim_row)
        return claim, episode_created

    def get_install_handoff_claim(self, source_key: str) -> InstallHandoffClaim | None:
        with self.session_factory() as session:
            row = session.get(InstallHandoffClaimRow, source_key)
            return self._install_handoff_claim_from_row(row) if row is not None else None

    def try_acquire_install_handoff(
        self,
        *,
        source_key: str,
        owner: str,
        now: datetime,
        lease_seconds: int,
    ) -> InstallHandoffClaim | None:
        """Acquire the single workflow-start lease for an incomplete handoff."""

        lease_until = now + timedelta(seconds=lease_seconds)
        with self.session_factory.begin() as session:
            result = session.execute(
                update(InstallHandoffClaimRow)
                .where(
                    InstallHandoffClaimRow.source_key == source_key,
                    InstallHandoffClaimRow.state
                    != InstallHandoffState.WORKFLOW_STARTED.value,
                    or_(
                        InstallHandoffClaimRow.lease_until.is_(None),
                        InstallHandoffClaimRow.lease_until <= now,
                    ),
                )
                .values(
                    state=InstallHandoffState.WORKFLOW_STARTING.value,
                    lease_owner=owner,
                    lease_until=lease_until,
                    attempt_count=InstallHandoffClaimRow.attempt_count + 1,
                    last_error=None,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                return None
            row = session.get(InstallHandoffClaimRow, source_key)
            if row is None:
                raise RuntimeError("INSTALL_HANDOFF_CLAIM_DISAPPEARED")
            return self._install_handoff_claim_from_row(row)

    def mark_install_handoff_started(
        self,
        *,
        source_key: str,
        owner: str,
        now: datetime,
    ) -> InstallHandoffClaim:
        with self.session_factory.begin() as session:
            result = session.execute(
                update(InstallHandoffClaimRow)
                .where(
                    InstallHandoffClaimRow.source_key == source_key,
                    InstallHandoffClaimRow.lease_owner == owner,
                    InstallHandoffClaimRow.state
                    == InstallHandoffState.WORKFLOW_STARTING.value,
                )
                .values(
                    state=InstallHandoffState.WORKFLOW_STARTED.value,
                    lease_owner=None,
                    lease_until=None,
                    last_error=None,
                    updated_at=now,
                    completed_at=now,
                )
            )
            if result.rowcount != 1:
                raise RuntimeError("INSTALL_HANDOFF_LEASE_LOST")
            row = session.get(InstallHandoffClaimRow, source_key)
            if row is None:
                raise RuntimeError("INSTALL_HANDOFF_CLAIM_DISAPPEARED")
            return self._install_handoff_claim_from_row(row)

    def renew_install_handoff_lease(
        self,
        *,
        source_key: str,
        owner: str,
        now: datetime,
        lease_seconds: int,
    ) -> bool:
        """Extend a live workflow-start lease without reviving a stolen claim."""

        with self.session_factory.begin() as session:
            result = session.execute(
                update(InstallHandoffClaimRow)
                .where(
                    InstallHandoffClaimRow.source_key == source_key,
                    InstallHandoffClaimRow.lease_owner == owner,
                    InstallHandoffClaimRow.state
                    == InstallHandoffState.WORKFLOW_STARTING.value,
                )
                .values(
                    lease_until=now + timedelta(seconds=lease_seconds),
                    updated_at=now,
                )
            )
            return result.rowcount == 1

    def mark_install_handoff_retryable(
        self,
        *,
        source_key: str,
        owner: str,
        now: datetime,
        error: str,
    ) -> InstallHandoffClaim | None:
        with self.session_factory.begin() as session:
            result = session.execute(
                update(InstallHandoffClaimRow)
                .where(
                    InstallHandoffClaimRow.source_key == source_key,
                    InstallHandoffClaimRow.lease_owner == owner,
                    InstallHandoffClaimRow.state
                    == InstallHandoffState.WORKFLOW_STARTING.value,
                )
                .values(
                    state=InstallHandoffState.FAILED_RETRYABLE.value,
                    lease_owner=None,
                    lease_until=None,
                    last_error=error[:4000],
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                return None
            row = session.get(InstallHandoffClaimRow, source_key)
            return self._install_handoff_claim_from_row(row) if row is not None else None

    def _quarantine_write_guard(self):
        if self.engine.dialect.name == "sqlite":
            return self._sqlite_quarantine_lock
        return nullcontext()

    def save_quarantine(
        self,
        quarantine: PostActionQuarantine,
    ) -> PostActionQuarantine:
        quarantine.updated_at = datetime.now(UTC)
        with self._quarantine_write_guard():
            with self.session_factory.begin() as session:
                row = session.get(QuarantineRow, quarantine.quarantine_id)
                if row is None:
                    quarantine.version = max(quarantine.version, 0)
                    session.add(QuarantineRow(**self._quarantine_values(quarantine)))
                else:
                    quarantine.version = row.version + 1
                    self._apply_values(
                        row,
                        self._quarantine_values(quarantine),
                        primary_key="quarantine_id",
                    )
        return quarantine

    def get_quarantine(self, quarantine_id: str) -> PostActionQuarantine | None:
        with self.session_factory() as session:
            row = session.get(QuarantineRow, quarantine_id)
            return self._quarantine_from_row(row) if row is not None else None

    def get_quarantine_by_action(self, action_id: str) -> PostActionQuarantine | None:
        with self.session_factory() as session:
            row = session.scalar(
                select(QuarantineRow).where(QuarantineRow.action_id == action_id)
            )
            return self._quarantine_from_row(row) if row is not None else None

    def list_quarantines(
        self,
        *,
        status: QuarantineStatus | None = None,
        incident_id: str | None = None,
        limit: int = 200,
    ) -> list[PostActionQuarantine]:
        statement = select(QuarantineRow)
        if status is not None:
            statement = statement.where(QuarantineRow.status == status.value)
        if incident_id is not None:
            statement = statement.where(QuarantineRow.incident_id == incident_id)
        statement = statement.order_by(QuarantineRow.updated_at.desc()).limit(limit)
        with self.session_factory() as session:
            rows = session.scalars(statement).all()
            return [self._quarantine_from_row(row) for row in rows]

    def append_quarantine_observation(
        self,
        observation: QuarantineObservation,
    ) -> QuarantineObservation:
        with self.session_factory.begin() as session:
            self._insert_do_nothing(
                session,
                QuarantineObservationRow,
                self._quarantine_observation_values(observation),
            )
            existing = session.scalar(
                select(QuarantineObservationRow).where(
                    QuarantineObservationRow.quarantine_id == observation.quarantine_id,
                    QuarantineObservationRow.idempotency_key
                    == observation.idempotency_key,
                )
            )
            if existing is None:
                raise RuntimeError("QUARANTINE_OBSERVATION_NOT_VISIBLE")
            if existing.request_fingerprint != observation.request_fingerprint:
                raise QuarantineObservationConflictError(
                    "QUARANTINE_IDEMPOTENCY_PAYLOAD_CONFLICT"
                )
        return observation

    def get_quarantine_observation_by_key(
        self,
        quarantine_id: str,
        idempotency_key: str,
    ) -> QuarantineObservation | None:
        with self.session_factory() as session:
            row = session.scalar(
                select(QuarantineObservationRow).where(
                    QuarantineObservationRow.quarantine_id == quarantine_id,
                    QuarantineObservationRow.idempotency_key == idempotency_key,
                )
            )
            return self._quarantine_observation_from_row(row) if row is not None else None

    def list_quarantine_observations(
        self,
        quarantine_id: str,
    ) -> list[QuarantineObservation]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(QuarantineObservationRow)
                .where(QuarantineObservationRow.quarantine_id == quarantine_id)
                .order_by(
                    QuarantineObservationRow.received_at.asc(),
                    QuarantineObservationRow.observation_id.asc(),
                )
            ).all()
            return [self._quarantine_observation_from_row(row) for row in rows]

    def apply_quarantine_observation(
        self,
        *,
        quarantine_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        build_mutation: QuarantineMutationBuilder,
    ) -> QuarantineApplyResult:
        """Lock, validate and persist one complete P2 transition atomically."""

        with self._quarantine_write_guard():
            with self.session_factory.begin() as session:
                quarantine_statement = select(QuarantineRow).where(
                    QuarantineRow.quarantine_id == quarantine_id
                )
                incident_statement = select(IncidentRow)
                episode_statement = select(AssuranceEpisodeRow)
                if self.engine.dialect.name == "postgresql":
                    quarantine_statement = quarantine_statement.with_for_update()
                    incident_statement = incident_statement.with_for_update()
                    episode_statement = episode_statement.with_for_update()

                quarantine_row = session.scalar(quarantine_statement)
                if quarantine_row is None:
                    raise KeyError(quarantine_id)

                incident_row = session.scalar(
                    incident_statement.where(
                        IncidentRow.incident_id == quarantine_row.incident_id
                    )
                )
                episode_row = session.scalar(
                    episode_statement.where(
                        AssuranceEpisodeRow.episode_id == quarantine_row.episode_id
                    )
                )
                if incident_row is None or episode_row is None:
                    raise RuntimeError("QUARANTINE_CANONICAL_ROWS_MISSING")

                existing_row = session.scalar(
                    select(QuarantineObservationRow).where(
                        QuarantineObservationRow.quarantine_id == quarantine_id,
                        QuarantineObservationRow.idempotency_key == idempotency_key,
                    )
                )
                if existing_row is not None:
                    if existing_row.request_fingerprint != request_fingerprint:
                        raise QuarantineObservationConflictError(
                            "QUARANTINE_IDEMPOTENCY_PAYLOAD_CONFLICT"
                        )
                    return QuarantineApplyResult(
                        created=False,
                        quarantine=self._quarantine_from_row(quarantine_row),
                        observation=self._quarantine_observation_from_row(existing_row),
                        incident=IncidentState.model_validate(incident_row.state_json),
                        episode=self._assurance_episode_from_row(episode_row),
                    )

                latest_row = session.scalar(
                    select(QuarantineObservationRow)
                    .where(QuarantineObservationRow.quarantine_id == quarantine_id)
                    .order_by(
                        QuarantineObservationRow.received_at.desc(),
                        QuarantineObservationRow.observation_id.desc(),
                    )
                    .limit(1)
                )
                latest = (
                    self._quarantine_observation_from_row(latest_row)
                    if latest_row is not None
                    else None
                )
                mutation = build_mutation(
                    self._quarantine_from_row(quarantine_row),
                    IncidentState.model_validate(incident_row.state_json),
                    self._assurance_episode_from_row(episode_row),
                    latest,
                )
                if (
                    mutation.quarantine.quarantine_id != quarantine_id
                    or mutation.observation.quarantine_id != quarantine_id
                    or mutation.incident.incident_id != quarantine_row.incident_id
                    or mutation.episode.episode_id != quarantine_row.episode_id
                    or mutation.observation.request_fingerprint != request_fingerprint
                ):
                    raise RuntimeError("QUARANTINE_MUTATION_IDENTITY_MISMATCH")

                mutation.quarantine.version = quarantine_row.version + 1
                self._apply_values(
                    quarantine_row,
                    self._quarantine_values(mutation.quarantine),
                    primary_key="quarantine_id",
                )
                self._apply_values(
                    incident_row,
                    self._incident_values(mutation.incident),
                    primary_key="incident_id",
                )
                self._apply_values(
                    episode_row,
                    self._assurance_episode_values(mutation.episode),
                    primary_key="episode_id",
                )
                session.add(
                    QuarantineObservationRow(
                        **self._quarantine_observation_values(mutation.observation)
                    )
                )
                self._insert_do_nothing(
                    session,
                    AssuranceEpisodeEventRow,
                    self._assurance_event_values(mutation.lineage_event),
                )
                session.flush()
                self._before_quarantine_commit(session, mutation)
                return QuarantineApplyResult(
                    created=True,
                    quarantine=mutation.quarantine,
                    observation=mutation.observation,
                    incident=mutation.incident,
                    episode=mutation.episode,
                )

    def _before_quarantine_commit(
        self,
        _session: Session,
        _mutation: QuarantineMutation,
    ) -> None:
        """Test seam for proving rollback of the complete P2 transaction."""

    def claim_due_quarantines(
        self,
        *,
        now: datetime,
        worker_id: str,
        lease_seconds: int,
        limit: int = 20,
    ) -> list[PostActionQuarantine]:
        lease_until = now + timedelta(seconds=lease_seconds)
        with self._quarantine_write_guard():
            with self.session_factory.begin() as session:
                statement = (
                    select(QuarantineRow)
                    .where(
                        QuarantineRow.status == QuarantineStatus.ACTIVE.value,
                        QuarantineRow.next_check_at <= now,
                        or_(
                            QuarantineRow.lease_until.is_(None),
                            QuarantineRow.lease_until <= now,
                        ),
                    )
                    .order_by(QuarantineRow.next_check_at.asc())
                    .limit(limit)
                )
                if self.engine.dialect.name == "postgresql":
                    statement = statement.with_for_update(skip_locked=True)
                rows = session.scalars(statement).all()
                for row in rows:
                    row.lease_owner = worker_id
                    row.lease_token = uuid4().hex
                    row.lease_until = lease_until
                    row.version += 1
                    row.updated_at = now
                return [self._quarantine_from_row(row) for row in rows]

    def renew_quarantine_lease(
        self,
        *,
        quarantine_id: str,
        worker_id: str,
        lease_token: str,
        now: datetime,
        lease_seconds: int,
    ) -> bool:
        """Renew only the live lease identified by both owner and unique token."""

        with self.session_factory.begin() as session:
            result = session.execute(
                update(QuarantineRow)
                .where(
                    QuarantineRow.quarantine_id == quarantine_id,
                    QuarantineRow.status == QuarantineStatus.ACTIVE.value,
                    QuarantineRow.lease_owner == worker_id,
                    QuarantineRow.lease_token == lease_token,
                    QuarantineRow.lease_until > now,
                )
                .values(
                    lease_until=now + timedelta(seconds=lease_seconds),
                    version=QuarantineRow.version + 1,
                    updated_at=now,
                )
            )
            return result.rowcount == 1

    def reset(self) -> None:
        with self.session_factory.begin() as session:
            session.execute(delete(QuarantineObservationRow))
            session.execute(delete(QuarantineRow))
            session.execute(delete(InstallHandoffClaimRow))
            session.execute(delete(AssuranceEpisodeEventRow))
            session.execute(delete(AssuranceEpisodeRow))
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
            "quarantined": sum(
                item.status == CaseStatus.QUARANTINED for item in incidents
            ),
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
    def _quarantine_from_row(row: QuarantineRow) -> PostActionQuarantine:
        return PostActionQuarantine(
            quarantine_id=row.quarantine_id,
            episode_id=row.episode_id,
            incident_id=row.incident_id,
            action_id=row.action_id,
            action_type=row.action_type,
            status=QuarantineStatus(row.status),
            pre_action_health=dict(row.pre_action_health_json or {}),
            immediate_post_action_health=dict(
                row.immediate_post_action_health_json or {}
            ),
            started_at=row.started_at,
            minimum_release_at=row.minimum_release_at,
            next_check_at=row.next_check_at,
            required_healthy_checks=row.required_healthy_checks,
            healthy_checks=row.healthy_checks,
            extension_count=row.extension_count,
            max_extensions=row.max_extensions,
            check_interval_seconds=row.check_interval_seconds,
            version=row.version,
            lease_owner=row.lease_owner,
            lease_token=row.lease_token,
            lease_until=row.lease_until,
            completed_at=row.completed_at,
            metadata=dict(row.metadata_json or {}),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _quarantine_observation_from_row(
        row: QuarantineObservationRow,
    ) -> QuarantineObservation:
        return QuarantineObservation(
            observation_id=row.observation_id,
            quarantine_id=row.quarantine_id,
            incident_id=row.incident_id,
            observed_at=row.observed_at,
            received_at=row.received_at,
            health=QuarantineHealth(row.health),
            source=row.source,
            actor=row.actor,
            idempotency_key=row.idempotency_key,
            request_fingerprint=row.request_fingerprint,
            lease_token=row.lease_token,
            metrics=dict(row.metrics_json or {}),
            transition=QuarantineTransition(row.transition),
            created_at=row.created_at,
        )

    @staticmethod
    def _assurance_episode_from_row(row: AssuranceEpisodeRow) -> AssuranceEpisode:
        return AssuranceEpisode(
            episode_id=row.episode_id,
            source_key=row.source_key,
            origin=AssuranceOrigin(row.origin),
            incident_id=row.incident_id,
            install_run_id=row.install_run_id,
            install_watch_id=row.install_watch_id,
            install_episode_id=row.install_episode_id,
            service_id=row.service_id,
            device_id=row.device_id,
            technology=row.technology,
            status=EpisodeStatus(row.status),
            workflow_stage=row.workflow_stage,
            title=row.title,
            metadata=dict(row.metadata_json or {}),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _install_handoff_claim_from_row(
        row: InstallHandoffClaimRow,
    ) -> InstallHandoffClaim:
        return InstallHandoffClaim(
            source_key=row.source_key,
            episode_id=row.episode_id,
            incident_id=row.incident_id,
            request_fingerprint=row.request_fingerprint,
            state=InstallHandoffState(row.state),
            lease_owner=row.lease_owner,
            lease_until=row.lease_until,
            attempt_count=row.attempt_count,
            last_error=row.last_error,
            created_at=row.created_at,
            updated_at=row.updated_at,
            completed_at=row.completed_at,
        )

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
