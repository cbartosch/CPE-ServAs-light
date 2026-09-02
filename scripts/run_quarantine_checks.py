"""Run due P2 post-action quarantine jobs through the workflow API."""

from __future__ import annotations

import argparse
import json
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow-url", default="http://127.0.0.1:8000")
    parser.add_argument("--worker-id", default="operator-cli")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    body = json.dumps(
        {"worker_id": args.worker_id, "limit": args.limit}
    ).encode()
    request = urllib.request.Request(
        f"{args.workflow_url.rstrip('/')}/api/assurance/quarantine-jobs/run-due",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=240) as response:
        payload = json.loads(response.read().decode("utf-8"))
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
