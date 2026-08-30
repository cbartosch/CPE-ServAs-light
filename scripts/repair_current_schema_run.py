#!/usr/bin/env python3
"""Generate, activate and verify a current-schema Digital Twin run.

The command never mutates an existing run. It uses the authenticated ``POST
/api/runs`` contract, verifies the durable active-run pointer, verifies the current
run schema and quality gate, and confirms that the previous catalog remains
byte-for-byte unchanged.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

EXPECTED_SCHEMA = "lpr-digital-twin-run-v3-execution-economics"


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def request_json(
    base_url: str,
    path: str,
    *,
    user: str,
    password: str,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=payload,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API {exc.code}: {detail}") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError(f"expected JSON object from {path}")
    return decoded


def canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_config(
    previous: dict[str, Any] | None,
    *,
    homes: int,
    profile: str,
    seed: int,
    run_date: str,
) -> dict[str, Any]:
    config = dict((previous or {}).get("config") or {})
    config.update(
        {
            "profile": profile,
            "homes": homes,
            "seed": seed,
            "run_date": run_date,
            "enable_llm": False,
            "llm_provider": "fake",
            "llm_model": "",
        }
    )
    return config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--user")
    parser.add_argument("--password")
    parser.add_argument("--homes", type=int, default=500)
    parser.add_argument("--profile", default="smoke")
    parser.add_argument("--seed", type=int, default=2401)
    parser.add_argument("--run-date", default=date.today().isoformat())
    parser.add_argument("--expected-schema", default=EXPECTED_SCHEMA)
    args = parser.parse_args(argv)

    if not 1 <= args.homes <= 500_000:
        parser.error("--homes must be between 1 and 500000")
    if args.seed < 0:
        parser.error("--seed must be non-negative")

    env = read_env(args.env_file)
    user = args.user or env.get("DT_USER", "demo")
    password = args.password or env.get("DT_PASSWORD", "CHANGE_ME")

    before: dict[str, Any] | None
    try:
        before = request_json(
            args.base_url,
            "/api/active-run",
            user=user,
            password=password,
        )
    except RuntimeError as exc:
        if "API 404" not in str(exc):
            raise
        before = None

    before_id = str((before or {}).get("run_id") or "")
    before_hash = hashlib.sha256(canonical_json(before)).hexdigest() if before else None
    config = build_config(
        before,
        homes=args.homes,
        profile=args.profile,
        seed=args.seed,
        run_date=args.run_date,
    )

    created = request_json(
        args.base_url,
        "/api/runs",
        user=user,
        password=password,
        method="POST",
        body={"config": config},
    )
    active = request_json(
        args.base_url,
        "/api/active-run",
        user=user,
        password=password,
    )

    new_id = str(created.get("run_id") or "")
    active_id = str(active.get("run_id") or "")
    schema = str(active.get("run_schema_version") or "")
    quality_passed = bool((active.get("quality") or {}).get("passed"))

    legacy_unchanged = True
    if before_id and before_hash:
        legacy = request_json(
            args.base_url,
            f"/api/runs/{before_id}",
            user=user,
            password=password,
        )
        legacy_hash = hashlib.sha256(canonical_json(legacy)).hexdigest()
        legacy_unchanged = legacy_hash == before_hash

    result = {
        "status": "PASS",
        "previous_run_id": before_id or None,
        "new_run_id": new_id,
        "active_run_id": active_id,
        "new_run_created": bool(new_id and new_id != before_id),
        "active_pointer_moved": bool(active_id and active_id == new_id),
        "run_schema_version": schema,
        "schema_is_current": schema == args.expected_schema,
        "quality_passed": quality_passed,
        "legacy_run_mutation": not legacy_unchanged,
        "homes": (active.get("config") or {}).get("homes"),
        "profile": (active.get("config") or {}).get("profile"),
        "seed": (active.get("config") or {}).get("seed"),
    }

    required = (
        result["new_run_created"],
        result["active_pointer_moved"],
        result["schema_is_current"],
        result["quality_passed"],
        legacy_unchanged,
    )
    if not all(required):
        result["status"] = "FAIL"

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
