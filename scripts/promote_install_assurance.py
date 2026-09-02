"""Promote one degraded install watch episode into the shared repair workflow."""

from __future__ import annotations

import argparse
import base64
import json
import os
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--digital-twin-url", default="http://127.0.0.1:8001")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--watch-id", required=True)
    parser.add_argument("--episode-id", required=True)
    parser.add_argument("--username", default=os.getenv("DT_USER", "demo"))
    parser.add_argument("--password", default=os.getenv("DT_PASSWORD", "CHANGE_ME"))
    args = parser.parse_args()
    token = base64.b64encode(f"{args.username}:{args.password}".encode()).decode("ascii")
    body = json.dumps({"install_episode_id": args.episode_id}).encode()
    path = (
        f"/api/runs/{args.run_id}/install-assurance/watches/"
        f"{args.watch_id}/promote"
    )
    request = urllib.request.Request(
        f"{args.digital_twin_url.rstrip('/')}{path}",
        data=body,
        headers={
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        payload = json.loads(response.read().decode("utf-8"))
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
