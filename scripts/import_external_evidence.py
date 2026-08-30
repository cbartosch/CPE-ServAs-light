#!/usr/bin/env python3
"""Import local CSV evidence into a read-only scenario batch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lpr_cpe_demo.digital_twin.external_evidence import (
    add_csv_content,
    analyze_import_batch,
    create_import_batch,
    materialize_import_batch,
    validate_import_batch,
)

SOURCE_ARGUMENTS = {
    "identity_map": "identity",
    "nxt_telemetry": "nxt_telemetry",
    "nxt_alarms": "nxt_alarms",
    "dvsum_caddi_insights": "dvsum_caddi",
    "genesys_interactions": "genesys",
    "jtrack_events": "jtrack",
    "install_cohort": "install_cohort",
}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description=(
            "Import NXT, DvSum CADDI, Genesys, JTrack and installation CSVs into "
            "an immutable, simulation-only evidence batch."
        )
    )
    result.add_argument("--data-root", type=Path, required=True)
    result.add_argument(
        "--mode",
        choices=("historical_replay", "point_in_time", "install_watch", "shadow"),
        default="historical_replay",
    )
    result.add_argument("--name", default="External evidence import")
    result.add_argument("--as-of")
    result.add_argument("--run-id", help="Optional canonical run to receive a child overlay")
    result.add_argument(
        "--provider",
        choices=("disabled", "fake", "openai", "anthropic"),
        default="fake",
    )
    result.add_argument("--model", default="")
    result.add_argument("--disable-llm", action="store_true")
    for option in SOURCE_ARGUMENTS.values():
        result.add_argument(f"--{option.replace('_', '-')}", type=Path)
    return result


def main() -> int:
    args = parser().parse_args()
    batch = create_import_batch(
        args.data_root,
        mode=args.mode,
        name=args.name,
        as_of=args.as_of,
    )
    batch_id = batch["batch_id"]
    uploaded = 0
    for source, option in SOURCE_ARGUMENTS.items():
        path = getattr(args, option)
        if path is None:
            continue
        add_csv_content(
            args.data_root,
            batch_id,
            source_type=source,
            filename=path.name,
            content=path.read_text(encoding="utf-8-sig"),
        )
        uploaded += 1
    if not uploaded:
        raise SystemExit("At least one CSV path must be supplied.")
    quality = validate_import_batch(args.data_root, batch_id)
    if quality["status"] == "REJECTED":
        print(json.dumps({"batch": batch, "quality": quality}, indent=2))
        return 2
    analysis = analyze_import_batch(
        args.data_root,
        batch_id,
        enable_llm=not args.disable_llm,
        llm_provider=args.provider,
        llm_model=args.model,
    )
    scenario = materialize_import_batch(
        args.data_root,
        batch_id,
        run_id=args.run_id,
    )
    print(
        json.dumps(
            {
                "batch_id": batch_id,
                "quality": quality,
                "analysis": analysis,
                "scenario": scenario,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
