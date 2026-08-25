# ruff: noqa: E501
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field

from . import __version__
from .executive_projection import build_executive_projection
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


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__, "production_writes": False, "release": "P0 Fixed R3 Hotfix5.5", "predictive_care_integration": True}


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
    return {"dataset": dataset, "returned": len(rows), "total": total, "rows": rows}


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
    for row in iter_jsonl_gz(path):
        if status and row.get("status") != status:
            continue
        if priority and row.get("priority") != priority:
            continue
        if predictive_match is not None and row.get("predictive_match") is not predictive_match:
            continue
        rows.append(row)
        if len(rows) >= limit:
            break
    return {"returned": len(rows), "rows": rows}


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
