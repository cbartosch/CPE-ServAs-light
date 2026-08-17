from __future__ import annotations

import base64
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
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


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
    claims = json.loads(_b64decode(encoded).decode("utf-8"))
    expires_at = claims.get("exp")
    if expires_at is None:
        raise ApprovalTokenError("APPROVAL_TOKEN_NO_EXPIRY")
    if datetime.fromtimestamp(float(expires_at), UTC) <= datetime.now(UTC):
        raise ApprovalTokenError("APPROVAL_TOKEN_EXPIRED")
    return claims
