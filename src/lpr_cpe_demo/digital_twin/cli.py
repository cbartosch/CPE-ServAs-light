from __future__ import annotations

import argparse
import json
from pathlib import Path

from .models import GenerationConfig
from .orchestrator import generate

PROFILES = {"smoke": 500, "preview": 5_000, "board": 50_000, "full": 500_000}


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--profile", choices=PROFILES, default="smoke")
    g.add_argument("--homes", type=int)
    g.add_argument("--data-root", default="./data")
    g.add_argument("--scenarios", default="slow_wifi,fiber_cut,power_outage")
    g.add_argument("--seed", type=int, default=2400)
    args = parser.parse_args()
    if args.command == "generate":
        config = GenerationConfig(
            profile=args.profile,
            homes=args.homes or PROFILES[args.profile],
            scenarios=tuple(x.strip() for x in args.scenarios.split(",") if x.strip()),
            seed=args.seed,
        )
        catalog = generate(config, Path(args.data_root))
        print(json.dumps(catalog, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
