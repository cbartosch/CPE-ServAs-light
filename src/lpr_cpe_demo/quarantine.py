"""Durable post-action quarantine contracts and policy evaluation.

P2 prevents a successful immediate post-action test from closing a repair case
before a configurable stability window and repeated health observations complete.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import Field, field_validator

from lpr_cpe_demo.domain import StrictModel, stable_id, utc_now


class QuarantineHealth(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


class QuarantineStatus(StrEnum):
    ACTIVE = "active"
    RELEASED = "released"
    REOPENED = "reopened"
    ESCALATED = "escalated"


class QuarantineTransition(StrEnum):
    CONTINUE = "continue"
    RELEASE = "release"
    REOPEN = "reopen"
    EXTEND = "extend"
    ESCALATE = "escalate"


class QuarantineConflictError(RuntimeError):
    """A quarantine request conflicts with durable state."""


class QuarantineTerminalStateError(QuarantineConflictError):
    """A new observation targeted a completed quarantine."""


class QuarantineObservationConflictError(QuarantineConflictError):
    """An idempotency key was replayed with different canonical content."""


class QuarantineObservationTimeError(QuarantineConflictError):
    """An external measurement timestamp is invalid or outside policy bounds."""


class QuarantineObservationTooEarlyError(QuarantineConflictError):
    """A non-degraded observation arrived before the next server-side check."""


class QuarantineLeaseError(QuarantineConflictError):
    """A scheduled observation did not own the current durable lease."""


class QuarantinePolicy(StrictModel):
    enabled: bool = False
    duration_seconds: int = Field(default=900, ge=1)
    check_interval_seconds: int = Field(default=60, ge=1)
    required_healthy_checks: int = Field(default=2, ge=1)
    max_extensions: int = Field(default=2, ge=0)
    lease_seconds: int = Field(default=120, ge=5)
    max_measurement_clock_skew_seconds: int = Field(default=300, ge=0)


class PostActionQuarantine(StrictModel):
    quarantine_id: str
    episode_id: str
    incident_id: str
    action_id: str
    action_type: str
    status: QuarantineStatus = QuarantineStatus.ACTIVE
    pre_action_health: dict[str, Any]
    immediate_post_action_health: dict[str, Any]
    started_at: datetime = Field(default_factory=utc_now)
    minimum_release_at: datetime
    next_check_at: datetime
    required_healthy_checks: int = Field(ge=1)
    healthy_checks: int = Field(default=0, ge=0)
    extension_count: int = Field(default=0, ge=0)
    max_extensions: int = Field(default=2, ge=0)
    check_interval_seconds: int = Field(default=60, ge=1)
    version: int = Field(default=0, ge=0)
    lease_owner: str | None = None
    lease_token: str | None = None
    lease_until: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class QuarantineObservation(StrictModel):
    observation_id: str
    quarantine_id: str
    incident_id: str
    observed_at: datetime
    received_at: datetime
    health: QuarantineHealth
    source: str
    actor: str
    idempotency_key: str
    request_fingerprint: str
    lease_token: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    transition: QuarantineTransition
    created_at: datetime = Field(default_factory=utc_now)


class QuarantineObservationRequest(StrictModel):
    health: QuarantineHealth
    observed_at: datetime | None = None
    idempotency_key: str = Field(min_length=1, max_length=160)
    metrics: dict[str, Any] = Field(default_factory=dict)

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("observed_at must include a timezone offset")
        return value


def as_utc(value: datetime) -> datetime:
    """Normalize an aware timestamp to UTC."""

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def quarantine_id_for(episode_id: str, action_id: str) -> str:
    """Return the stable quarantine identifier for one material action."""

    return stable_id(episode_id, action_id, prefix="quar")


def observation_id_for(quarantine_id: str, idempotency_key: str) -> str:
    """Return a replay-safe observation identifier scoped to one quarantine."""

    return stable_id(quarantine_id, idempotency_key, prefix="qobs")


def observation_request_fingerprint(
    quarantine_id: str,
    request: QuarantineObservationRequest,
    *,
    actor: str,
    source: str,
) -> str:
    """Return a canonical fingerprint for scoped idempotency validation."""

    measured_at = as_utc(request.observed_at).isoformat() if request.observed_at else None
    payload = {
        "actor": actor,
        "health": request.health.value,
        "idempotency_key": request.idempotency_key,
        "metrics": request.metrics,
        "observed_at": measured_at,
        "quarantine_id": quarantine_id,
        "source": source,
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def start_post_action_quarantine(
    *,
    episode_id: str,
    incident_id: str,
    action_id: str,
    action_type: str,
    pre_action_health: dict[str, Any],
    immediate_post_action_health: dict[str, Any],
    policy: QuarantinePolicy,
    started_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> PostActionQuarantine:
    """Create the deterministic P2 quarantine record for an action."""

    start = as_utc(started_at or utc_now())
    return PostActionQuarantine(
        quarantine_id=quarantine_id_for(episode_id, action_id),
        episode_id=episode_id,
        incident_id=incident_id,
        action_id=action_id,
        action_type=action_type,
        pre_action_health=pre_action_health,
        immediate_post_action_health=immediate_post_action_health,
        started_at=start,
        minimum_release_at=start + timedelta(seconds=policy.duration_seconds),
        next_check_at=start + timedelta(seconds=policy.check_interval_seconds),
        required_healthy_checks=policy.required_healthy_checks,
        max_extensions=policy.max_extensions,
        check_interval_seconds=policy.check_interval_seconds,
        metadata=metadata or {},
    )


def evaluate_quarantine_observation(
    quarantine: PostActionQuarantine,
    request: QuarantineObservationRequest,
    *,
    received_at: datetime,
) -> tuple[PostActionQuarantine, QuarantineTransition]:
    """Apply P2 policy using server-authoritative receipt time.

    ``request.observed_at`` remains the external measurement timestamp for audit
    purposes. It never controls release, extension, lease, or completion timing.
    """

    server_time = as_utc(received_at)
    quarantine.minimum_release_at = as_utc(quarantine.minimum_release_at)
    quarantine.next_check_at = as_utc(quarantine.next_check_at)

    if quarantine.status != QuarantineStatus.ACTIVE:
        raise QuarantineTerminalStateError(
            f"QUARANTINE_TERMINAL:{quarantine.quarantine_id}:{quarantine.status.value}"
        )

    transition = QuarantineTransition.CONTINUE
    if request.health == QuarantineHealth.DEGRADED:
        quarantine.status = QuarantineStatus.REOPENED
        quarantine.completed_at = server_time
        transition = QuarantineTransition.REOPEN
    elif request.health == QuarantineHealth.UNKNOWN:
        if quarantine.extension_count < quarantine.max_extensions:
            quarantine.extension_count += 1
            quarantine.minimum_release_at += timedelta(
                seconds=quarantine.check_interval_seconds
            )
            quarantine.next_check_at = server_time + timedelta(
                seconds=quarantine.check_interval_seconds
            )
            transition = QuarantineTransition.EXTEND
        else:
            quarantine.status = QuarantineStatus.ESCALATED
            quarantine.completed_at = server_time
            transition = QuarantineTransition.ESCALATE
    else:
        quarantine.healthy_checks += 1
        if (
            server_time >= quarantine.minimum_release_at
            and quarantine.healthy_checks >= quarantine.required_healthy_checks
        ):
            quarantine.status = QuarantineStatus.RELEASED
            quarantine.completed_at = server_time
            transition = QuarantineTransition.RELEASE
        else:
            quarantine.next_check_at = server_time + timedelta(
                seconds=quarantine.check_interval_seconds
            )

    quarantine.lease_owner = None
    quarantine.lease_token = None
    quarantine.lease_until = None
    quarantine.updated_at = server_time
    return quarantine, transition
