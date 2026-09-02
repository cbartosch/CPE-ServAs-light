"""Durable post-action quarantine contracts and policy evaluation.

P2 prevents a successful immediate post-action test from closing a repair case
before a configurable stability window and repeated health observations complete.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import Field

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


class QuarantinePolicy(StrictModel):
    enabled: bool = False
    duration_seconds: int = Field(default=900, ge=1)
    check_interval_seconds: int = Field(default=60, ge=1)
    required_healthy_checks: int = Field(default=2, ge=1)
    max_extensions: int = Field(default=2, ge=0)
    lease_seconds: int = Field(default=120, ge=5)


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
    lease_owner: str | None = None
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
    health: QuarantineHealth
    source: str
    actor: str
    idempotency_key: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    transition: QuarantineTransition
    created_at: datetime = Field(default_factory=utc_now)


class QuarantineObservationRequest(StrictModel):
    health: QuarantineHealth
    observed_at: datetime = Field(default_factory=utc_now)
    source: str = "operator"
    actor: str = "operations.operator"
    idempotency_key: str
    metrics: dict[str, Any] = Field(default_factory=dict)


def quarantine_id_for(episode_id: str, action_id: str) -> str:
    """Return the stable quarantine identifier for one material action."""

    return stable_id(episode_id, action_id, prefix="quar")


def observation_id_for(quarantine_id: str, idempotency_key: str) -> str:
    """Return a replay-safe observation identifier."""

    return stable_id(quarantine_id, idempotency_key, prefix="qobs")


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

    start = started_at or utc_now()
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
) -> tuple[PostActionQuarantine, QuarantineTransition]:
    """Apply the deterministic P2 health policy to one observation."""

    if quarantine.minimum_release_at.tzinfo is None:
        quarantine.minimum_release_at = quarantine.minimum_release_at.replace(tzinfo=UTC)
    if quarantine.next_check_at.tzinfo is None:
        quarantine.next_check_at = quarantine.next_check_at.replace(tzinfo=UTC)
    if request.observed_at.tzinfo is None:
        request.observed_at = request.observed_at.replace(tzinfo=UTC)

    if quarantine.status != QuarantineStatus.ACTIVE:
        return quarantine, QuarantineTransition.CONTINUE

    observed_at = request.observed_at
    transition = QuarantineTransition.CONTINUE
    if request.health == QuarantineHealth.DEGRADED:
        quarantine.status = QuarantineStatus.REOPENED
        quarantine.completed_at = observed_at
        transition = QuarantineTransition.REOPEN
    elif request.health == QuarantineHealth.UNKNOWN:
        if quarantine.extension_count < quarantine.max_extensions:
            quarantine.extension_count += 1
            quarantine.minimum_release_at += timedelta(
                seconds=quarantine.check_interval_seconds
            )
            quarantine.next_check_at = observed_at + timedelta(
                seconds=quarantine.check_interval_seconds
            )
            transition = QuarantineTransition.EXTEND
        else:
            quarantine.status = QuarantineStatus.ESCALATED
            quarantine.completed_at = observed_at
            transition = QuarantineTransition.ESCALATE
    else:
        quarantine.healthy_checks += 1
        if (
            observed_at >= quarantine.minimum_release_at
            and quarantine.healthy_checks >= quarantine.required_healthy_checks
        ):
            quarantine.status = QuarantineStatus.RELEASED
            quarantine.completed_at = observed_at
            transition = QuarantineTransition.RELEASE
        else:
            quarantine.next_check_at = observed_at + timedelta(
                seconds=quarantine.check_interval_seconds
            )

    quarantine.lease_owner = None
    quarantine.lease_until = None
    quarantine.updated_at = utc_now()
    return quarantine, transition
