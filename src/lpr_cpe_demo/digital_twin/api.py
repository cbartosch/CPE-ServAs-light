# ruff: noqa: E501
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field

from ..dalli import dalli_contract
from ..measurement import measurement_contract
from . import __version__
from .executive_projection import build_executive_projection
from .install_assurance import (
    create_install_assurance_watch,
    install_assurance_contract,
    latest_install_assurance_projection,
    list_install_assurance_watches,
    load_install_assurance_watch,
)
from .models import GenerationConfig, HumanDecision
from .orchestrator import (
    DATASETS,
    generate,
    list_predictive_scans,
    load_predictive_scan,
    materialize_live_decision,
    run_predictive_scan,
)
from .storage import (
    get_active_run,
    iter_jsonl_gz,
    load_jsonl_gz,
    safe_run_path,
    set_active_run,
)
from .workflow import CaseStore

security = HTTPBasic()
DATA_ROOT = Path(os.getenv("DT_DATA_ROOT", "/data"))


def principal(credentials: HTTPBasicCredentials = Depends(security)) -> dict:
    if credentials.username != os.getenv("DT_USER", "demo") or credentials.password != os.getenv("DT_PASSWORD", "CHANGE_ME"):
        raise HTTPException(401, "invalid credentials", headers={"WWW-Authenticate": "Basic"})
    return {"user": credentials.username, "role": os.getenv("DT_USER_ROLE", "operator")}


class RunRequest(BaseModel):
    config: GenerationConfig


class ActiveRunRequest(BaseModel):
    run_id: str


class PredictiveScanRequest(BaseModel):
    population: int = Field(default=20_000, ge=1, le=500_000)
    days: int = Field(default=14, ge=7, le=60)
    day_index: int = Field(default=0, ge=0, le=365)


class InstallAssuranceWatchRequest(BaseModel):
    population: int = Field(default=12, ge=1, le=5_000)
    as_of_hours: float = Field(default=24.0, ge=0, le=72)
    stability_tail_hours: float = Field(default=4.0, ge=1, le=12)
    seed: int = Field(default=0, ge=0, le=2_147_483_647)


app = FastAPI(title="LPR CPE Digital Twin", version=__version__)


def _run_path(run_id: str) -> Path:
    try:
        return safe_run_path(DATA_ROOT, run_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _load_catalog(run_id: str) -> dict:
    path = _run_path(run_id) / "catalog.json"
    if not path.exists():
        raise HTTPException(404, "run not found")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(409, "run catalog is unreadable") from exc


def _activate_run(run_id: str) -> dict:
    try:
        set_active_run(DATA_ROOT, run_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, "run not found") from exc
    return _load_catalog(run_id)


def _active_run_id() -> str:
    run_id = get_active_run(DATA_ROOT)
    if run_id is None:
        raise HTTPException(404, "no active run")
    return run_id


def _build_projection(run_id: str) -> dict:
    try:
        return build_executive_projection(DATA_ROOT, run_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "run not found") from exc
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(409, f"executive projection unavailable: {exc}") from exc


@app.get("/api/integrations/dalli")
@app.get("/api/integrations/caddi", deprecated=True)
@app.get("/api/integrations/cadi", deprecated=True)
def dalli_integration(_: dict = Depends(principal)):
    return dalli_contract()


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": __version__,
        "production_writes": False,
        "release": "Stage 3 install assurance with DvSum DALLI",
        "predictive_care_integration": True, "external_evidence_csv": True, "llm_triangulation": True,
        "install_assurance": True,
        "dalli_integration": "contract_only",
        "measurement_schema": "1.0",
    }


@app.get("/ready")
def ready(_: dict = Depends(principal)):
    try:
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        probe = DATA_ROOT / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise HTTPException(503, f"data root is not writable: {exc}") from exc
    return {"status": "ready", "data_root": str(DATA_ROOT)}


@app.get("/api/measurement-contract")
def _measurement_contract(_: dict = Depends(principal)):
    return measurement_contract()


@app.get("/api/runs")
def list_runs(_: dict = Depends(principal)):
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    result = []
    for catalog_path in sorted(DATA_ROOT.glob("RUN-*/catalog.json"), reverse=True):
        try:
            result.append(json.loads(catalog_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return result


@app.post("/api/runs")
def create_run(request: RunRequest, _: dict = Depends(principal)):
    try:
        catalog = generate(request.config, DATA_ROOT)
        set_active_run(DATA_ROOT, catalog["run_id"])
        return catalog
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/active-run")
def active_run(_: dict = Depends(principal)):
    return _load_catalog(_active_run_id())


@app.post("/api/active-run")
@app.put("/api/active-run")
def select_active_run(request: ActiveRunRequest, _: dict = Depends(principal)):
    return _activate_run(request.run_id)


@app.post("/api/active-run/{run_id}")
@app.put("/api/active-run/{run_id}")
@app.post("/api/runs/{run_id}/activate")
def select_active_run_by_path(run_id: str, _: dict = Depends(principal)):
    return _activate_run(run_id)


@app.get("/api/executive-projection")
@app.get("/api/active-run/executive-projection")
def active_executive_projection(_: dict = Depends(principal)):
    return _build_projection(_active_run_id())


@app.get("/api/runs/{run_id}/executive-projection")
def run_executive_projection(run_id: str, _: dict = Depends(principal)):
    return _build_projection(run_id)


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, _: dict = Depends(principal)):
    return _load_catalog(run_id)


@app.get("/api/runs/{run_id}/datasets/{dataset}")
def dataset_rows(run_id: str, dataset: str, limit: int = Query(default=100, ge=1, le=5000), _: dict = Depends(principal)):
    if dataset not in DATASETS:
        raise HTTPException(404, "unknown dataset")
    run_path = _run_path(run_id)
    path = run_path / f"{dataset}.jsonl.gz"
    if not path.exists():
        raise HTTPException(404, "dataset not found")
    rows = load_jsonl_gz(path, limit=limit)
    catalog_path = run_path / "catalog.json"
    total = None
    if catalog_path.exists():
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        entry = next((d for d in catalog.get("datasets", []) if d.get("dataset") == dataset), None)
        total = entry.get("row_count") if entry else None
    returned = len(rows)
    return {
        "dataset": dataset,
        "returned": returned,
        "total": total,
        "truncated": total is not None and returned < int(total),
        "headline_safe": False,
        "rows": rows,
    }


@app.get("/api/runs/{run_id}/subscriber/{service_id}")
def subscriber_360(run_id: str, service_id: str, _: dict = Depends(principal)):
    run_path = _run_path(run_id)
    subscriber = next((r for r in iter_jsonl_gz(run_path / "subscriber_master.jsonl.gz") if r["service_id"] == service_id), None)
    if subscriber is None:
        raise HTTPException(404, "service not found")
    related = {}
    for dataset in DATASETS[1:]:
        path = run_path / f"{dataset}.jsonl.gz"
        if not path.exists():
            continue
        matched = [r for r in iter_jsonl_gz(path) if r.get("service_id") == service_id]
        if matched:
            related[dataset] = matched
    return {"subscriber": subscriber, "related": related}


@app.get("/api/runs/{run_id}/cases/{case_id}")
def get_case(run_id: str, case_id: str, _: dict = Depends(principal)):
    store = CaseStore(_run_path(run_id) / "control.sqlite")
    try:
        return store.get(case_id)
    except KeyError as exc:
        raise HTTPException(404, "case not found") from exc


@app.post("/api/runs/{run_id}/decisions")
def decide(run_id: str, decision: HumanDecision, actor: dict = Depends(principal)):
    if actor["role"] not in {"operator", "supervisor"}:
        raise HTTPException(403, "role cannot decide")
    if decision.actor != actor["user"]:
        raise HTTPException(400, "actor must be the authenticated principal")
    run_path = _run_path(run_id)
    store = CaseStore(run_path / "control.sqlite")
    try:
        store_result = store.decide(decision)
        return materialize_live_decision(run_path, decision, store, store_result)
    except KeyError as exc:
        raise HTTPException(404, "case not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

@app.post("/api/runs/{run_id}/predictive/scans")
def create_predictive_scan(
    run_id: str,
    request: PredictiveScanRequest,
    _: dict = Depends(principal),
):
    run_path = _run_path(run_id)
    if not (run_path / "catalog.json").exists():
        raise HTTPException(404, "run not found")
    try:
        return run_predictive_scan(
            run_path,
            population=request.population,
            days=request.days,
            day_index=request.day_index,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/runs/{run_id}/predictive/scans")
def predictive_scans(run_id: str, _: dict = Depends(principal)):
    run_path = _run_path(run_id)
    if not (run_path / "catalog.json").exists():
        raise HTTPException(404, "run not found")
    return list_predictive_scans(run_path)


@app.get("/api/runs/{run_id}/predictive/scans/{scan_id}")
def predictive_scan_detail(
    run_id: str,
    scan_id: str,
    limit: int = Query(default=100, ge=1, le=5000),
    _: dict = Depends(principal),
):
    try:
        return load_predictive_scan(_run_path(run_id), scan_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "predictive scan not found") from exc


@app.get("/api/install-assurance/contract")
def install_watch_contract(_: dict = Depends(principal)):
    return install_assurance_contract()


@app.post("/api/runs/{run_id}/install-assurance/watches")
def create_install_watch(
    run_id: str,
    request: InstallAssuranceWatchRequest,
    _: dict = Depends(principal),
):
    run_path = _run_path(run_id)
    if not (run_path / "catalog.json").is_file():
        raise HTTPException(404, "run not found")
    try:
        return create_install_assurance_watch(
            run_path,
            population=request.population,
            as_of_hours=request.as_of_hours,
            stability_tail_hours=request.stability_tail_hours,
            seed=request.seed,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/runs/{run_id}/install-assurance/watches")
def install_watches(run_id: str, _: dict = Depends(principal)):
    run_path = _run_path(run_id)
    if not (run_path / "catalog.json").is_file():
        raise HTTPException(404, "run not found")
    return list_install_assurance_watches(run_path)


@app.get("/api/runs/{run_id}/install-assurance/watches/{watch_id}")
def install_watch_detail(
    run_id: str,
    watch_id: str,
    limit: int = Query(default=500, ge=1, le=5000),
    _: dict = Depends(principal),
):
    try:
        return load_install_assurance_watch(_run_path(run_id), watch_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "install assurance watch not found") from exc


@app.get("/api/runs/{run_id}/install-assurance/projection")
def install_watch_projection(run_id: str, _: dict = Depends(principal)):
    projection = latest_install_assurance_projection(_run_path(run_id))
    if projection is None:
        raise HTTPException(404, "no install assurance watch for run")
    return projection


@app.get("/api/install-assurance/projection")
def active_install_watch_projection(_: dict = Depends(principal)):
    projection = latest_install_assurance_projection(_run_path(_active_run_id()))
    if projection is None:
        raise HTTPException(404, "no install assurance watch for active run")
    return projection


@app.get("/api/runs/{run_id}/care/tickets")
def care_ticket_queue(
    run_id: str,
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    predictive_match: bool | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=5000),
    _: dict = Depends(principal),
):
    run_path = _run_path(run_id)
    path = run_path / "care_tickets.jsonl.gz"
    if not path.exists():
        raise HTTPException(404, "care ticket dataset not found")
    rows = []
    total = 0
    filtered_total = 0
    summary = {
        "open": 0,
        "closed": 0,
        "p1": 0,
        "p2": 0,
        "p3": 0,
        "predictively_matched": 0,
        "reactive_only": 0,
        "repeat_contacts": 0,
    }
    for row in iter_jsonl_gz(path):
        total += 1
        if status and row.get("status") != status:
            continue
        if priority and row.get("priority") != priority:
            continue
        if predictive_match is not None and row.get("predictive_match") is not predictive_match:
            continue
        filtered_total += 1
        ticket_status = str(row.get("status", "")).lower()
        if ticket_status in {"open", "closed"}:
            summary[ticket_status] += 1
        ticket_priority = str(row.get("priority", "")).lower()
        if ticket_priority in {"p1", "p2", "p3"}:
            summary[ticket_priority] += 1
        if row.get("predictive_match"):
            summary["predictively_matched"] += 1
        else:
            summary["reactive_only"] += 1
        if row.get("repeat_contact"):
            summary["repeat_contacts"] += 1
        if len(rows) < limit:
            rows.append(row)
    return {
        "total": total,
        "filtered_total": filtered_total,
        "returned": len(rows),
        "truncated": len(rows) < filtered_total,
        "headline_safe": True,
        "summary": summary,
        "rows": rows,
    }


@app.get("/api/runs/{run_id}/care/tickets/{care_ticket_id}")
def care_ticket_detail(run_id: str, care_ticket_id: str, _: dict = Depends(principal)):
    run_path = _run_path(run_id)
    ticket = next(
        (r for r in iter_jsonl_gz(run_path / "care_tickets.jsonl.gz") if r.get("care_ticket_id") == care_ticket_id),
        None,
    )
    if ticket is None:
        raise HTTPException(404, "care ticket not found")
    review = next(
        (r for r in iter_jsonl_gz(run_path / "care_ticket_reviews.jsonl.gz") if r.get("care_ticket_id") == care_ticket_id),
        None,
    )
    predictive = None
    predictive_id = ticket.get("predictive_ticket_id")
    if predictive_id:
        predictive = next(
            (r for r in iter_jsonl_gz(run_path / "predictive_tickets.jsonl.gz") if r.get("ticket_id") == predictive_id),
            None,
        )
    case = None
    try:
        case = CaseStore(run_path / "control.sqlite").get(ticket["case_id"])
    except KeyError:
        pass
    return {"ticket": ticket, "review": review, "predictive": predictive, "case": case}


# ---------------------------------------------------------------------------
# External CSV evidence imports. These endpoints accept CSV text in JSON so the
# demo does not need multipart parsing or a production file-transfer service.
class ExternalImportBatchRequest(BaseModel):
    mode: str = Field(
        default="historical_replay",
        pattern="^(historical_replay|point_in_time|install_watch|shadow)$",
    )
    name: str = Field(default="", max_length=160)
    as_of: str | None = None


class ExternalCSVFileRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=240)
    content: str
    replace: bool = False


class ExternalAnalysisRequest(BaseModel):
    enable_llm: bool = True
    llm_provider: str = Field(default="fake", pattern="^(disabled|fake|openai|anthropic)$")
    llm_model: str = Field(default="", max_length=200)
    max_services: int = Field(default=25, ge=1, le=50)


class ExternalMaterializeRequest(BaseModel):
    run_id: str | None = None


@app.get("/api/external-evidence/contract")
def external_evidence_contract(_: dict = Depends(principal)):
    from .external_evidence import external_evidence_contract as build_contract

    return build_contract()


@app.get("/api/external-evidence/templates/{source_type}")
def external_evidence_template(source_type: str, _: dict = Depends(principal)):
    from .external_evidence import canonical_source_type, csv_template

    try:
        source = canonical_source_type(source_type)
        return {"source_type": source, "filename": f"{source}.csv", "content": csv_template(source)}
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/import-batches")
def create_external_import_batch(
    request: ExternalImportBatchRequest,
    _: dict = Depends(principal),
):
    from .external_evidence import create_import_batch

    try:
        return create_import_batch(
            DATA_ROOT,
            mode=request.mode,
            name=request.name,
            as_of=request.as_of,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/import-batches")
def external_import_batches(_: dict = Depends(principal)):
    from .external_evidence import list_import_batches

    return list_import_batches(DATA_ROOT)


@app.get("/api/import-batches/{batch_id}")
def external_import_batch(batch_id: str, _: dict = Depends(principal)):
    from .external_evidence import get_import_batch

    try:
        return get_import_batch(DATA_ROOT, batch_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, "import batch not found") from exc


@app.post("/api/import-batches/{batch_id}/files/{source_type}")
def upload_external_csv(
    batch_id: str,
    source_type: str,
    request: ExternalCSVFileRequest,
    _: dict = Depends(principal),
):
    from .external_evidence import add_csv_content

    try:
        return add_csv_content(
            DATA_ROOT,
            batch_id,
            source_type=source_type,
            filename=request.filename,
            content=request.content,
            replace=request.replace,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, "import batch not found") from exc
    except FileExistsError as exc:
        raise HTTPException(409, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/import-batches/{batch_id}/validate")
def validate_external_import_batch(batch_id: str, _: dict = Depends(principal)):
    from .external_evidence import validate_import_batch

    try:
        return validate_import_batch(DATA_ROOT, batch_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, "import batch not found") from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/import-batches/{batch_id}/analyze")
def analyze_external_import_batch(
    batch_id: str,
    request: ExternalAnalysisRequest,
    _: dict = Depends(principal),
):
    from .external_evidence import analyze_import_batch

    try:
        return analyze_import_batch(
            DATA_ROOT,
            batch_id,
            enable_llm=request.enable_llm,
            llm_provider=request.llm_provider,
            llm_model=request.llm_model,
            max_services=request.max_services,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, "import batch not found") from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/import-batches/{batch_id}/materialize")
def materialize_external_import_batch(
    batch_id: str,
    request: ExternalMaterializeRequest,
    _: dict = Depends(principal),
):
    from .external_evidence import materialize_import_batch

    try:
        return materialize_import_batch(DATA_ROOT, batch_id, run_id=request.run_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, "import batch or run not found") from exc


@app.get("/api/runs/{run_id}/external-evidence")
def run_external_evidence(run_id: str, _: dict = Depends(principal)):
    from .external_evidence import list_run_external_evidence

    try:
        return list_run_external_evidence(DATA_ROOT, run_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/import-batches/{batch_id}/quality")
def external_import_quality(batch_id: str, _: dict = Depends(principal)):
    from .external_evidence import get_import_batch

    try:
        result = get_import_batch(DATA_ROOT, batch_id)["quality_report"]
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, "import batch not found") from exc
    if result is None:
        raise HTTPException(404, "batch has not been validated")
    return result


@app.get("/api/import-batches/{batch_id}/correlations")
def external_import_correlations(batch_id: str, _: dict = Depends(principal)):
    from .external_evidence import get_import_batch

    try:
        result = get_import_batch(DATA_ROOT, batch_id)["correlation_report"]
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, "import batch not found") from exc
    if result is None:
        raise HTTPException(404, "batch has not been validated")
    return result


@app.get("/api/import-batches/{batch_id}/timeline")
def external_import_timeline(batch_id: str, _: dict = Depends(principal)):
    from .external_evidence import get_import_batch

    try:
        result = get_import_batch(DATA_ROOT, batch_id)["timeline"]
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, "import batch not found") from exc
    if result is None:
        raise HTTPException(404, "batch has not been validated")
    return result


@app.get("/api/import-batches/{batch_id}/recommendations")
def external_import_recommendations(batch_id: str, _: dict = Depends(principal)):
    from .external_evidence import get_import_batch

    try:
        result = get_import_batch(DATA_ROOT, batch_id)["recommendation_report"]
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, "import batch not found") from exc
    if result is None:
        raise HTTPException(404, "batch has not been analyzed")
    return result


@app.get("/api/import-batches/{batch_id}/projection")
def external_import_projection(batch_id: str, _: dict = Depends(principal)):
    from .external_evidence import build_external_scenario_projection

    try:
        return build_external_scenario_projection(DATA_ROOT, batch_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, "import batch not found") from exc


@app.get("/api/import-batches/{batch_id}/dispositions")
def external_import_dispositions(
    batch_id: str,
    limit: int = Query(default=500, ge=1, le=5000),
    _: dict = Depends(principal),
):
    from .external_evidence import safe_batch_path

    try:
        path = safe_batch_path(DATA_ROOT, batch_id) / "normalized" / "row_dispositions.jsonl.gz"
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not path.exists():
        raise HTTPException(404, "batch has not been validated")
    rows = load_jsonl_gz(path, limit=limit)
    return {"returned": len(rows), "limit": limit, "rows": rows}
