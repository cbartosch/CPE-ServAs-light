"""Run due P2 post-action quarantine jobs through the protected workflow API."""

from __future__ import annotations

import argparse
import json
import os
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--internal-token",
        default=os.getenv("WORKFLOW_INTERNAL_TOKEN", ""),
        help="Protected workflow mutation token; defaults to WORKFLOW_INTERNAL_TOKEN.",
    )
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    if not args.internal_token:
        raise SystemExit(
            "WORKFLOW_INTERNAL_TOKEN or --internal-token is required for P2 mutations"
        )

    body = json.dumps({"limit": args.limit}).encode()
    request = urllib.request.Request(
        f"{args.workflow_url.rstrip('/')}/api/assurance/quarantine-jobs/run-due",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-LPR-Internal-Token": args.internal_token,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=240) as response:
        payload = json.loads(response.read().decode("utf-8"))
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
