from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import re
from typing import Literal

_ALLOWED_KEY_PART = re.compile(r"^[A-Za-z0-9._:@/+-]*$")


def _normalize_key_part(value: object | None) -> str:
    """Normalize one durable key component without introducing randomness.

    ``None`` and an empty string remain distinct. Unexpected characters are
    represented by a stable digest rather than making action execution fail.
    """

    if value is None:
        return "<none>"
    text = str(value).strip()
    if text == "":
        return "<empty>"
    if _ALLOWED_KEY_PART.fullmatch(text):
        return text
    return f"sha256:{sha256(text.encode('utf-8')).hexdigest()[:20]}"


def derive_action_key(
    *,
    incident_id: str,
    action_type: str,
    attempt_index: int,
    delimiter_id: str | None = None,
) -> str:
    """Return a replay-stable key for one intended external effect.

    The key is a pure function of durable incident state. It intentionally does
    not include a timestamp, process identifier, random UUID, or model output.
    A new attempt yields a new key; replaying the same attempt yields the same
    key even after a process restart.
    """

    if attempt_index < 0:
        raise ValueError("attempt_index must be non-negative")
    material = "|".join(
        (
            "lpr-cpe-action-v2",
            _normalize_key_part(incident_id),
            _normalize_key_part(action_type),
            str(attempt_index),
            _normalize_key_part(delimiter_id),
        )
    )
    return f"idem-{sha256(material.encode('utf-8')).hexdigest()[:40]}"


def derive_approval_id(
    *,
    incident_id: str,
    approval_kind: str,
    action_type: str,
    attempt_index: int,
    delimiter_id: str | None = None,
) -> str:
    """Return a replay-stable approval identifier for the intended effect."""

    action_key = derive_action_key(
        incident_id=incident_id,
        action_type=action_type,
        attempt_index=attempt_index,
        delimiter_id=delimiter_id,
    )
    material = "|".join(("lpr-cpe-approval-v2", approval_kind, action_key))
    return f"apr-{sha256(material.encode('utf-8')).hexdigest()[:32]}"


def authoritative_sla_deadline(
    *,
    own_deadline: datetime,
    sla_mode: Literal["own", "inherits_parent", "paused"],
    parent_deadline: datetime | None,
) -> datetime:
    """Return the deadline that governs the incident without resetting clocks."""

    if sla_mode == "inherits_parent":
        if parent_deadline is None:
            raise ValueError("inherits_parent requires parent_sla_deadline")
        return parent_deadline
    return own_deadline


def sla_authority_label(
    *,
    sla_mode: Literal["own", "inherits_parent", "paused"],
    parent_incident_id: str | None,
) -> str:
    if sla_mode == "inherits_parent":
        return f"parent {parent_incident_id or 'unknown'}"
    if sla_mode == "paused":
        return "paused"
    return "own clock"
