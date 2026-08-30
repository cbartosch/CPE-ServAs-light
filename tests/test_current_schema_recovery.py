from __future__ import annotations

import importlib.util
from pathlib import Path

from lpr_cpe_demo.digital_twin import api, storage

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/repair_current_schema_run.py"


def _module():
    spec = importlib.util.spec_from_file_location("repair_current_schema_run", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_api_exposes_current_run_schema_and_structured_quality_conflicts() -> None:
    source = (ROOT / "src/lpr_cpe_demo/digital_twin/api.py").read_text(encoding="utf-8")
    assert storage.RUN_SCHEMA_VERSION == (
        "lpr-digital-twin-run-v3-execution-economics"
    )
    assert '"run_schema_version": RUN_SCHEMA_VERSION' in source
    assert '"error": "live_decision_quality_gate_failed"' in source
    assert '"expected_run_schema_version": RUN_SCHEMA_VERSION' in source
    assert api.RUN_SCHEMA_VERSION == storage.RUN_SCHEMA_VERSION


def test_recovery_builds_a_new_safe_config_without_mutating_input() -> None:
    module = _module()
    previous = {"config": {"homes": 500_000, "profile": "full", "seed": 1}}
    config = module.build_config(
        previous,
        homes=500,
        profile="smoke",
        seed=2401,
        run_date="2026-08-30",
    )
    assert previous["config"]["homes"] == 500_000
    assert config["homes"] == 500
    assert config["profile"] == "smoke"
    assert config["seed"] == 2401
    assert config["enable_llm"] is False
    assert module.EXPECTED_SCHEMA == storage.RUN_SCHEMA_VERSION


def test_windows_and_posix_recovery_entry_points_exist() -> None:
    assert (ROOT / "scripts/Repair-LPR-CurrentSchemaRun.ps1").is_file()
    assert (ROOT / "scripts/repair-current-schema-run.sh").is_file()
