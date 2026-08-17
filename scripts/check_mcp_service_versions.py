from __future__ import annotations

import os
import re
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^]]+\])?==([^\s;]+)$")


def expected_pins() -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in (ROOT / "requirements-mcp.txt").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = PIN_RE.fullmatch(line)
        if match is None:
            raise SystemExit(f"MCP dependency is not exactly pinned: {line}")
        result[match.group(1).lower().replace("_", "-")] = match.group(2)
    return result


def main() -> int:
    health_url = os.getenv("MCP_HEALTH_URL", "http://localhost:8100/health")
    response = httpx.get(health_url, timeout=10)
    response.raise_for_status()
    payload = response.json()
    observed = {
        str(name).lower().replace("_", "-"): str(value)
        for name, value in dict(payload.get("runtime_versions") or {}).items()
    }
    expected = expected_pins()
    missing = sorted(set(expected) - set(observed))
    if missing:
        raise SystemExit(f"MCP health response omitted pinned packages: {missing}")
    mismatches = {
        name: {"expected": version, "observed": observed.get(name)}
        for name, version in expected.items()
        if observed.get(name) != version
    }
    if mismatches:
        raise SystemExit(f"MCP image version mismatch: {mismatches}")
    print("MCP service exact-version check: PASS")
    for name in sorted(expected):
        print(f"- {name}: {observed[name]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
