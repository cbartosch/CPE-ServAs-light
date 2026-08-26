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
| GET | `/api/dashboard` | cockpit metrics |
| GET | `/api/integrations/cadi` | contract-only CADI/Genesys capability and authority map |
| GET | `/api/system/status` | engine, model and MCP status |
| POST | `/api/reset` | clear demo data with confirmation |

OpenAPI is available at `http://localhost:8000/docs`.
