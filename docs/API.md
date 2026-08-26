# API Summary

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | container health |
| GET | `/ready` | runtime and integration readiness |
| GET | `/api/scenarios` | list fixtures |
| POST | `/api/scenarios/{name}/start` | start a case |
| GET | `/api/incidents` | incident queue |
| GET | `/api/incidents/{id}` | full workbench state |
| GET | `/api/incidents/{id}/timeline` | audit timeline |
| POST | `/api/incidents/{id}/run` | run one step or to pause |
| GET | `/api/approvals` | human decision queue |
| POST | `/api/approvals/{id}/decision` | approve, override, request more or reject |
| GET | `/api/dashboard` | legacy cockpit summary |
| GET | `/api/measurement-contract` | canonical entity grains, formulas, statuses and invariants |
| GET | `/api/operations-projection` | complete live-workflow projection using the shared metric schema |
| GET | `/api/measurement-projection` | alias of the live Operations projection |
| GET | `/api/integrations/cadi` | contract-only DvSum CADDI/Genesys capability and authority map |
| GET | `/api/system/status` | engine, model and MCP status |
| POST | `/api/reset` | clear demo data with confirmation |

OpenAPI is available at `http://localhost:8000/docs`.

## Digital Twin API measurement endpoints

The Digital Twin API on port 8001 requires Basic Auth and additionally exposes:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/measurement-contract` | same canonical measurement contract |
| GET | `/api/active-run` | persisted active-run catalog |
| PUT | `/api/active-run` | select the canonical active run |
| GET | `/api/executive-projection` | complete active-run semantic projection |
| GET | `/api/runs/{run_id}/executive-projection` | projection for one explicit run |
| GET | `/api/runs/{run_id}/datasets/{dataset}` | paginated display rows with total/truncation metadata |
| GET | `/api/runs/{run_id}/care/tickets` | full filtered aggregates plus paginated contact rows |

Headline dashboard metrics come from the projection endpoints, not dataset page
lengths. See `docs/SHARED_MEASUREMENT_CONTRACT.md`.

## Install Assurance

- `POST /api/runs/{run_id}/install-assurance/watches` creates an immutable child
  watch without changing the canonical run.
- `GET /api/runs/{run_id}/install-assurance/watches` lists watch snapshots.
- `GET /api/runs/{run_id}/install-assurance/watches/{watch_id}` returns episode,
  observation, action, contact, incident and DvSum CADDI context rows.
- `GET /api/runs/{run_id}/install-assurance/projection` returns the latest watch
  projection for a run.
- `GET /api/install-assurance/projection` returns the latest watch for the active
  run.

Canonical DvSum CADDI contract: `GET /api/integrations/caddi`. The former
`/api/integrations/cadi` spelling remains a deprecated compatibility alias.
