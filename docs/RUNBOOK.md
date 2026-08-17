# Operations Runbook

## Purpose

This runbook operates the simulation-only Docker Desktop demonstration. It covers startup, verification, service inspection, reset, TLS/proxy troubleshooting and common workflow failures. It does not enable production NXT, CPE, WFM, TM Forum or jTrack writes.

## Safe startup sequence

### 1. Prepare the environment

The bundle includes a safe `.env`. When starting from a source-control checkout instead of the ZIP:

```bash
make env
```

Confirm these values remain in place unless deliberately testing another mode:

```dotenv
APPLICATION_MODE=simulation
PRODUCTION_WRITES_ENABLED=false
MODEL_PROVIDER=fake
MCP_PROFILE=custom_stateless_2026
```

### 2. Check Docker, DNS, proxy and TLS

```bash
./scripts/tls-doctor.sh
```

```powershell
.\scripts\tls-doctor.ps1
```

When a corporate HTTPS-inspection proxy re-signs traffic, stage the corporate root or issuing CA before building:

```bash
./scripts/stage-ca.sh /path/to/corporate-root.crt
```

```powershell
.\scripts\stage-ca.ps1 -CaFile C:\path\corporate-root.cer
```

Do not use `--trusted-host`, `verify=false`, an HTTP package index or a website leaf certificate as a trust anchor.

### 3. Start the stack

```bash
./scripts/start_demo.sh
```

```powershell
.\scripts\start_demo.ps1
```

Equivalent command:

```bash
docker compose up --build -d --wait --wait-timeout 300
```

### 4. Verify health

```bash
docker compose ps
```

Expected healthy services:

- `postgres`
- `mcp-sim`
- `api`
- `ui`

Run the smoke check from the test image when no local Python environment is available:

```bash
docker compose --profile test build test
docker compose --profile test run --rm \
  -e API_HEALTH_URL=http://api:8000/health \
  -e MCP_HEALTH_URL=http://mcp-sim:8100/health \
  -e UI_HEALTH_URL=http://ui:8501/_stcore/health \
  test python scripts/smoke_test.py
```

## URLs

| Surface | URL |
|---|---|
| Streamlit operations console | `http://localhost:8501` |
| FastAPI OpenAPI documentation | `http://localhost:8000/docs` |
| FastAPI health | `http://localhost:8000/health` |
| MCP simulator health | `http://localhost:8100/health` |
| MCP tool catalog | `http://localhost:8100/tools` |

## Demonstration procedure

1. Open **Scenario Launcher** and start a fixture.
2. Use **Incident Workbench** to inspect topology, evidence, deterministic RCA, assisted RCA, confidence, domain agreement, best action and next-best action.
3. Open **Human Decision Center** to approve, override, request more evidence or reject.
4. Observe the same incident thread resume.
5. Review the typed action, work order or MR in the workbench.
6. Confirm that restoration verification is a separate step from action acknowledgement.
7. Use **Decision and Model Monitor** to inspect model/provider metadata, policy result, human disposition and tool execution.

Recommended controls to demonstrate:

- `rca_disagreement_gate`: high confidence but different domains still pauses for a human.
- `hfc_failed_plant_action_rerca`: first plant action fails, the case returns to RCA and the same MR is updated rather than duplicated.
- `pon_reverse_handover`: the original incident returns from Dirty Boots to Clean Boots without resetting the SLA clock.
- `bounded_remote_failure`: retry ceilings cause escalation.

## Full verification

Run before any stakeholder demonstration:

```bash
./scripts/verify_docker.sh
```

```powershell
.\scripts\verify_docker.ps1
```

This performs the live Compose health checks, FastAPI-to-MCP workflow, exact dependency-pin validation, LangGraph interrupt/resume, PostgreSQL service recreation and resume, Streamlit startup, nine-scenario matrix, compilation and pytest coverage gate.

## Inspect service status and logs

```bash
docker compose ps
docker compose logs --tail=200 postgres
docker compose logs --tail=200 mcp-sim
docker compose logs --tail=200 api
docker compose logs --tail=200 ui
```

Follow all logs:

```bash
docker compose logs -f --tail=200
```

## Stop and reset

Stop without deleting data:

```bash
docker compose down
```

Remove PostgreSQL, checkpoint and MCP-effect data:

```bash
docker compose down -v
```

## Common problems

### Port already in use

Change one or more of these values in `.env`:

```dotenv
POSTGRES_PORT=5432
API_PORT=8000
MCP_PORT=8100
UI_PORT=8501
```

Then restart.

### Docker build cannot download packages

Run the TLS doctor. Distinguish DNS, proxy/CONNECT and certificate-chain failures before changing configuration. Configure an internal mirror through `PIP_INDEX_URL` when available.

### API is unhealthy

Check dependencies in order:

```bash
docker compose ps
docker compose logs postgres
docker compose logs mcp-sim
docker compose logs api
```

The API deliberately waits for healthy PostgreSQL and MCP services.

### MCP compatibility mismatch

The health response must advertise:

```json
{
  "protocol_profile": "custom_stateless_2026",
  "protocol_version": "2026-07-28",
  "stateless": true
}
```

Keep `MCP_PROFILE`, `MCP_PROTOCOL_VERSION` and `MCP_STRICT_VERSION` consistent in `.env`. A mismatch is supposed to fail closed.

### LangGraph cannot initialize PostgreSQL

Inside Compose, the DSN hostname must be `postgres`, not `localhost`:

```dotenv
LANGGRAPH_POSTGRES_DSN=postgresql://lpr:lpr_demo_change_me@postgres:5432/lpr_cpe_demo
```

Run the dedicated restart/resume check:

```bash
docker compose --profile test run --rm test python scripts/check_postgres_resume.py
```

### Streamlit displays stale state

The GUI reads the operational API/read model, not checkpoint tables. Confirm:

```dotenv
API_URL=http://api:8000
UI_REFRESH_SECONDS=2
```

Check the browser and UI logs. Increasing the refresh interval reduces laptop load.

### External LLM fails

Return to offline fake mode:

```dotenv
MODEL_PROVIDER=fake
MODEL_NAME=fake-lpr-cpe-v1
MODEL_API_KEY=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
```

Then restart the API. Deterministic workflow logic remains available.

### Approval is rejected

The Decision Center and audit trail show typed reasons. Common causes include:

- incorrect human role;
- expired or rejected approval;
- action mismatch after selecting a next-best action;
- consumed approval reused for a different idempotency key;
- incident claim mismatch.

The correct response to an action override is a new policy decision and fresh approval, not token reuse.

### Incident repeatedly returns to RCA

A failed action must add new evidence. The workflow escalates when it reaches remote, field, MR, diagnostic-cycle or total-step limits. Inspect `last_error`, attempt counters and the timeline rather than increasing limits first.

### Clear all local state

```bash
docker compose down -v
docker compose up --build -d --wait --wait-timeout 300
```

## Low-resource operation

```bash
docker compose -f docker-compose.yml -f docker-compose.low-resource.yml up --build -d --wait
```

Increase `UI_REFRESH_SECONDS` to 4–10 seconds and keep `MODEL_PROVIDER=fake` on limited hardware. See `docs/OFFLINE_AND_LOW_RESOURCE.md`.
