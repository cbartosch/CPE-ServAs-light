"""Shared repair/install assurance episode contracts.

P1 projects every repair case and every promoted installation defect into one
canonical assurance episode. Source systems remain authoritative; the episode
owns only cross-system correlation, workflow state and audit lineage.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from lpr_cpe_demo.domain import StrictModel, stable_id, utc_now


class AssuranceOrigin(StrEnum):
    REPAIR = "repair"
    INSTALL = "install"


class EpisodeStatus(StrEnum):
    ACTIVE = "active"
    WAITING = "waiting"
    QUARANTINED = "quarantined"
    CLOSED = "closed"
    ESCALATED = "escalated"


class AssuranceEpisode(StrictModel):
    episode_id: str
    origin: AssuranceOrigin
    source_key: str
    incident_id: str
    install_run_id: str | None = None
    install_watch_id: str | None = None
    install_episode_id: str | None = None
    service_id: str | None = None
    device_id: str | None = None
    technology: str
    status: EpisodeStatus = EpisodeStatus.ACTIVE
    workflow_stage: str
    title: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssuranceEpisodeEvent(StrictModel):
    event_id: str
    episode_id: str
    incident_id: str
    event_type: str
    actor: str
    occurred_at: datetime = Field(default_factory=utc_now)
    payload: dict[str, Any] = Field(default_factory=dict)


class InstallHandoffRequest(StrictModel):
    run_id: str
    watch_id: str
    install_episode_id: str
    service_id: str
    device_id: str
    technology: Literal["HFC", "PON"]
    title: str = "Install assurance defect requires repair"
    priority: str = "P2"
    reason: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    source_summary: dict[str, Any] = Field(default_factory=dict)
    production_write: bool = False

    @property
    def source_key(self) -> str:
        return f"install:{self.run_id}:{self.watch_id}:{self.install_episode_id}"


class InstallHandoffResult(StrictModel):
    created: bool
    episode: AssuranceEpisode
    incident: dict[str, Any]


def episode_id_for_repair(incident_id: str) -> str:
    """Return a stable episode ID for a repair-originated incident."""

    return stable_id("repair", incident_id, prefix="ase")


def episode_id_for_install(request: InstallHandoffRequest) -> str:
    """Return a stable episode ID for a promoted installation defect."""

    return stable_id(request.source_key, prefix="ase")
