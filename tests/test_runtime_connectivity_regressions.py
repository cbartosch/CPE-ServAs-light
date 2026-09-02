from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from lpr_cpe_demo.digital_twin.executive_projection import build_executive_projection
from lpr_cpe_demo.digital_twin.install_assurance import (
    IncompleteInstallAssuranceArtifactError,
    create_install_assurance_watch,
    latest_install_assurance_projection,
)
from lpr_cpe_demo.digital_twin.models import GenerationConfig
from lpr_cpe_demo.digital_twin.orchestrator import generate
from lpr_cpe_demo.digital_twin.storage import safe_run_path
from lpr_cpe_demo.ui.client import APIError, DemoAPI

ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


class _Response:
    status_code = 200
    content = b"{}"
    text = "{}"

    @staticmethod
    def json() -> dict[str, Any]:
        return {}


def test_ui_container_has_explicit_service_routes_and_request_budgets() -> None:
    compose = _source("docker-compose.yml")
    assert "API_URL: http://api:8000" in compose
    assert "API_TIMEOUT_SECONDS: ${API_TIMEOUT_SECONDS:-30}" in compose
    assert "API_SCENARIO_TIMEOUT_SECONDS: ${API_SCENARIO_TIMEOUT_SECONDS:-240}" in compose
    assert "DT_API_URL: http://digital-twin-api:8001" in compose
    assert 'LPR_APP_RELEASE: "1.29.2"' in compose


def test_demo_api_uses_a_separate_long_scenario_timeout(monkeypatch) -> None:
    observed: list[float] = []

    def fake_request(*args: Any, **kwargs: Any) -> _Response:
        observed.append(float(kwargs["timeout"]))
        return _Response()

    monkeypatch.setattr(httpx, "request", fake_request)
    client = DemoAPI(
        "http://api:8000",
        request_timeout=31,
        scenario_timeout=241,
    )
    client.get("/health")
    client.start("slow_wifi")
    assert observed == [31, 241]


def test_demo_api_timeout_message_names_budget_method_and_path(monkeypatch) -> None:
    request = httpx.Request("POST", "http://api:8000/api/scenarios/slow_wifi/start")

    def timeout(*args: Any, **kwargs: Any) -> None:
        raise httpx.ReadTimeout("timed out", request=request)

    monkeypatch.setattr(httpx, "request", timeout)
    client = DemoAPI("http://api:8000", scenario_timeout=240)
    with pytest.raises(APIError, match=r"240 seconds: POST /api/scenarios/slow_wifi/start"):
        client.start("slow_wifi")


def test_scenario_launcher_uses_spinner_and_actionable_timeout_guidance() -> None:
    source = _source("src/lpr_cpe_demo/ui/pages/scenarios.py")
    assert "with st.spinner(" in source
    assert "API may still be processing the scenario" in source
    assert "docker compose logs api" in source


def test_active_workspace_layout_is_fail_safe_and_header_is_dark() -> None:
    style = _source("src/lpr_cpe_demo/digital_twin/executive_style.py")
    assert "display:block !important;" in style
    assert "width:100% !important;" in style
    assert "grid-template-columns:repeat(auto-fit,minmax(min(100%,9rem),1fr))" in style
    assert "white-space:normal !important;" in style
    assert 'header[data-testid="stHeader"]' in style
    assert '[data-testid="stDecoration"]' in style
    assert "background-color: #383C41 !important;" in style


def test_startup_scripts_force_recreate_and_run_the_container_smoke() -> None:
    for relative in (
        "scripts/start_demo.ps1",
        "scripts/start_demo.sh",
        "scripts/start_digital_twin.ps1",
        "scripts/start_digital_twin.sh",
    ):
        source = _source(relative)
        assert "--force-recreate" in source
        assert "runtime_smoke.py" in source
    smoke = _source("scripts/runtime_smoke.py")
    assert "stale application image" in smoke
    assert "stale workflow API image" in smoke
    assert '"/api/scenarios"' in smoke
    assert '"/api/executive-projection"' in smoke


def test_incomplete_legacy_install_child_does_not_break_parent_projection(
    tmp_path: Path,
) -> None:
    catalog = generate(
        GenerationConfig(
            homes=100,
            seed=2715,
            scenarios=("fiber_cut", "slow_wifi", "power_outage"),
        ),
        tmp_path,
    )
    run_path = safe_run_path(tmp_path, catalog["run_id"])
    summary = create_install_assurance_watch(
        run_path,
        population=12,
        as_of_hours=24,
        stability_tail_hours=4,
        seed=15,
    )
    context_path = (
        run_path
        / "install_assurance"
        / summary["watch_id"]
        / "caddi_contexts.jsonl.gz"
    )
    context_path.unlink()

    with pytest.raises(IncompleteInstallAssuranceArtifactError) as exc_info:
        latest_install_assurance_projection(run_path)
    assert exc_info.value.missing_files == ("caddi_contexts.jsonl.gz",)

    assert latest_install_assurance_projection(run_path, skip_incomplete=True) is None
    projection = build_executive_projection(tmp_path, catalog["run_id"])
    assert projection["run_id"] == catalog["run_id"]
    assert "install_assurance" not in projection


def test_incomplete_install_child_is_409_but_parent_projection_stays_available(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from lpr_cpe_demo.digital_twin import api

    catalog = generate(
        GenerationConfig(
            homes=100,
            seed=2716,
            scenarios=("fiber_cut", "slow_wifi", "power_outage"),
        ),
        tmp_path,
    )
    run_path = safe_run_path(tmp_path, catalog["run_id"])
    summary = create_install_assurance_watch(
        run_path,
        population=12,
        as_of_hours=24,
        stability_tail_hours=4,
        seed=16,
    )
    (
        run_path
        / "install_assurance"
        / summary["watch_id"]
        / "caddi_contexts.jsonl.gz"
    ).unlink()

    monkeypatch.setattr(api, "DATA_ROOT", tmp_path)
    client = TestClient(api.app)
    auth = ("demo", "CHANGE_ME")

    parent = client.get(
        f"/api/runs/{catalog['run_id']}/executive-projection",
        auth=auth,
    )
    assert parent.status_code == 200
    assert parent.json()["run_id"] == catalog["run_id"]

    detail = client.get(
        f"/api/runs/{catalog['run_id']}/install-assurance/watches/"
        f"{summary['watch_id']}",
        auth=auth,
    )
    assert detail.status_code == 409
    assert detail.json()["detail"] == {
        "error": "install_assurance_artifact_incomplete",
        "watch_id": summary["watch_id"],
        "missing_files": ["caddi_contexts.jsonl.gz"],
        "canonical_parent_run_unchanged": True,
    }


def test_sidebar_exposes_loaded_application_release() -> None:
    source = _source("src/lpr_cpe_demo/ui/sidebar.py")
    assert "from .. import __version__" in source
    assert "Application release {lines['release']}" in source
