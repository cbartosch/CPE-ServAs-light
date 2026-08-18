from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any


class ApprovalTokenError(ValueError):
    pass


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    """Decode, raising ApprovalTokenError rather than leaking binascii.Error.

    A malformed token is untrusted input and must surface as a typed rejection.
    Letting binascii.Error escape means a caller catching ApprovalTokenError does
    not catch it, and a bad token becomes a 500 instead of a clean refusal.
    """
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except (binascii.Error, ValueError) as exc:
        raise ApprovalTokenError("APPROVAL_TOKEN_MALFORMED") from exc


def create_approval_token(claims: dict[str, Any], secret: str) -> str:
    payload = json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = _b64encode(payload)
    signature = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded}.{_b64encode(signature)}"


def verify_approval_token(token: str, secret: str) -> dict[str, Any]:
    try:
        encoded, signature_text = token.split(".", 1)
    except ValueError as exc:
        raise ApprovalTokenError("APPROVAL_TOKEN_MALFORMED") from exc
    expected = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    supplied = _b64decode(signature_text)
    if not hmac.compare_digest(expected, supplied):
        raise ApprovalTokenError("APPROVAL_TOKEN_INVALID")
    try:
        claims = json.loads(_b64decode(encoded).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ApprovalTokenError("APPROVAL_TOKEN_MALFORMED") from exc
    if not isinstance(claims, dict):
        raise ApprovalTokenError("APPROVAL_TOKEN_MALFORMED")
    expires_at = claims.get("exp")
    if expires_at is None:
        raise ApprovalTokenError("APPROVAL_TOKEN_NO_EXPIRY")
    if datetime.fromtimestamp(float(expires_at), UTC) <= datetime.now(UTC):
        raise ApprovalTokenError("APPROVAL_TOKEN_EXPIRED")
    return claims


class ApprovalMismatch(ApprovalTokenError):
    """A valid token, issued for a different action."""


def verify_approval_for(token: str, secret: str, *, incident_id: str,
                        action_type: str, idempotency_key: str) -> dict[str, Any]:
    """Verify the signature AND that the token authorises THIS action.

    Red-team finding: `verify_approval_token` returns `incident_id`,
    `action_type` and `idempotency_key`, and no caller compared them to the action
    being performed. A token legitimately issued for one incident and lane could
    therefore authorise a different one — a confused deputy. The claims existed
    precisely to prevent that and nothing read them.

    Signature verification alone answers "was this issued by us". It does not
    answer "was this issued for what I am about to do", and only the second
    question protects a customer from a crew arriving to do something nobody
    approved.
    """
    claims = verify_approval_token(token, secret)
    expected = {"incident_id": incident_id, "action_type": action_type,
                "idempotency_key": idempotency_key}
    for field, wanted in expected.items():
        actual = claims.get(field)
        if actual != wanted:
            raise ApprovalMismatch(
                f"APPROVAL_SCOPE_MISMATCH: token authorises {field}={actual!r} "
                f"but the action is {field}={wanted!r}")
    return claims
