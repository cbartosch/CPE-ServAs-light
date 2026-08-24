# ruff: noqa: E501
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

from . import __version__
from .models import GenerationConfig, HumanDecision
from .orchestrator import DATASETS, generate, materialize_live_decision
from .storage import iter_jsonl_gz, load_jsonl_gz, safe_run_path
from .workflow import CaseStore

security = HTTPBasic()
DATA_ROOT = Path(os.getenv("DT_DATA_ROOT", "/data"))


def principal(credentials: HTTPBasicCredentials = Depends(security)) -> dict:
    if credentials.username != os.getenv("DT_USER", "demo") or credentials.password != os.getenv("DT_PASSWORD", "CHANGE_ME"):
        raise HTTPException(401, "invalid credentials", headers={"WWW-Authenticate": "Basic"})
    return {"user": credentials.username, "role": os.getenv("DT_USER_ROLE", "operator")}


class RunRequest(BaseModel):
    config: GenerationConfig


app = FastAPI(title="LPR CPE Digital Twin", version=__version__)


def _run_path(run_id: str) -> Path:
    try:
        return safe_run_path(DATA_ROOT, run_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__, "production_writes": False, "release": "P0 Fixed R3"}


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
        return generate(request.config, DATA_ROOT)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, _: dict = Depends(principal)):
    path = _run_path(run_id) / "catalog.json"
    if not path.exists():
        raise HTTPException(404, "run not found")
    return json.loads(path.read_text(encoding="utf-8"))


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
