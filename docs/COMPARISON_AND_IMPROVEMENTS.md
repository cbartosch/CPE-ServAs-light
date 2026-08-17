# Comparison with `lpr-cpe-demo-fixed.zip` and adopted improvements

## Decision

The original LPR bundle remains the base because it already supplied the broader working vertical slice:

- a portable workflow and LangGraph wrapper;
- a real FastAPI-to-HTTP-MCP path;
- a six-page Streamlit console including decision/model monitoring;
- fake, OpenAI and Anthropic assistant adapters;
- eight executable scenarios in the original base, expanded to nine in this revision;
- API, strict-MCP, control and workflow tests;
- signed approval tokens and persistent MCP effect deduplication.

The comparison bundle contains strong audit-control and laptop-environment ideas, but its README explicitly identifies its graph, API, MCP and UI runtime layers as unexecuted and its graph-to-tool path as in-process. Replacing the original base would therefore remove working functionality and verification.

## Capability comparison

| Capability | Original bundle | Uploaded fixed bundle | Improved bundle |
|---|---|---|---|
| Streamlit operations GUI | Six pages, including model/decision monitor | Smaller draft UI; runtime not executed | Retained six-page GUI with configurable live refresh and SLA authority display |
| FastAPI workflow API | Implemented and exercised through TestClient | Drafted; runtime not executed | Retained and versioned at 1.2 |
| Graph runtime | Portable engine plus LangGraph wrapper | New draft graph; not executed | Retained both; added PostgreSQL recreate/resume target test |
| MCP boundary | Strict HTTP simulator plus in-process test client | Primary graph path in-process | HTTP remains the live path; in-process use is restricted to deterministic tests |
| Human controls | Signed approvals, role checks, action claims | Strong four-node approval pattern | Retained controls and added stable approval/action keys and fresh approval on override |
| Effect replay safety | Persistent MCP effect store | Dependency-free core idempotency design | Persistent effect store plus replay-safe workflow histories |
| Laptop/corporate network support | Basic Docker scripts | Strong CA, proxy, TLS-doctor approach | Adopted CA staging, proxy/mirror support, split images and health gates |
| Dependency policy | Exact pins in original runtime set | Broad compatible ranges | Exact split app/MCP/dev pins with installed-version verification |
| LPR operating scenarios | Eight executable scenarios | Nine specifications, runtime unexecuted | Nine executable scenarios including failed plant action and MR update |
| Verification evidence | Executed local suite and scenarios | Core tests only; runtime expressly unexecuted | 35 local tests, nine scenarios, 84.63% coverage, Docker gate included |

## Improvements adopted

### 1. Corporate proxy and CA support

Added trust-anchor staging, Debian system trust updates, consistent Python CA-bundle variables, proxy/mirror build arguments and Bash/PowerShell diagnostic tools. TLS verification remains enabled.

### 2. Purpose-specific images

Split the prior general image into:

- `docker/app.Dockerfile` for FastAPI, Streamlit, LangGraph, persistence and provider integrations;
- `docker/mcp.Dockerfile` for the smaller MCP simulator.

### 3. Restart-stable action and approval identities

Added versioned pure functions whose inputs are incident ID, action type, attempt index and tap/ODP delimiter. They contain no clock, random UUID or process-local value. A subprocess test proves stability across a fresh interpreter.

### 4. Replay-safe state histories

Adopted the comparison bundle's important distinction between effect idempotency and state-history idempotency:

- identical action results are deduplicated by idempotency key;
- timeline events have deterministic IDs;
- evidence is deduplicated by evidence ID;
- identical work-order and MR revisions are suppressed while later status revisions remain visible.

### 5. Explicit MCP profile and fail-fast compatibility check

Added `MCP_PROFILE=custom_stateless_2026`. Workflow startup verifies profile, protocol version and stateless operation against the server health response. The System Monitor displays the active profile and implementation.

### 6. Parent/child SLA authority

Common-cause children retain their original deadline, parent incident, parent deadline and authority mode. The workbench shows both the authoritative parent deadline and preserved child clock.

### 7. Safe next-best-action override

A token for one action cannot authorize a different action. Choosing an alternative consumes the original approval, re-runs deterministic policy and creates a fresh approval with the correct role and action claim.

### 8. Configurable Streamlit refresh

`UI_REFRESH_SECONDS` controls live cockpit, incident, decision and model-monitor fragments. The GUI still reads FastAPI's operational model rather than checkpoint tables.

### 9. PostgreSQL restart/resume gate

The full Docker verification now pauses an incident, disposes the workflow service, recreates it against the same PostgreSQL read model and LangGraph checkpointer, resumes the original approval and checks that one action and unique timeline events result.

### 10. Failed-plant-action scenario

Added a ninth executable scenario in which a Dirty Boots/MR action fails, the case returns to RCA with new evidence, and the same jTrack MR is updated for a second attempt rather than duplicated.

### 11. Expanded control tests

The local suite covers stable keys, delimiter sensitivity, profile mismatch, parent SLA authority, fresh approval after alternative selection, corporate CA support, split images and replay-safe history.

## Approaches deliberately not adopted

### Loose dependency ranges

The comparison bundle's broad framework ranges were replaced by exact pins. The Docker test reads those pins and compares every installed package version.

### In-process graph-to-MCP execution

The comparison runtime calls simulation functions in-process. The improved bundle retains the HTTP MCP boundary for the live API workflow and uses the in-process client only for isolated deterministic tests.

### Duplicate database schema ownership

The comparison bundle initializes raw SQL. The base already uses SQLAlchemy models as the schema owner; a second schema definition would create drift.

### Smaller UI and provider seam

The existing richer incident workbench, human decision center, model monitor and provider adapters were retained.

## Verification status

Executed locally for this revision:

- 35 automated tests passed;
- 84.63% measured source coverage;
- all nine scenarios passed;
- Compose structural validation passed;
- source, tests and scripts compiled successfully;
- FastAPI TestClient, strict MCP HTTP controls and separate-process FastAPI-to-MCP workflows passed for remote closure and failed-plant re-RCA with same-MR update.

Not executed in the assembly environment:

- Docker image build and container startup;
- real Streamlit server from the pinned image;
- pinned LangGraph runtime and PostgreSQL checkpoint restart;
- external provider API calls.

The included `verify_docker` scripts are the mandatory target-laptop gate for those remaining checks.
