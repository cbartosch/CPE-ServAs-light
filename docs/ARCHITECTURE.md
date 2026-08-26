# Architecture

## Container footprint

| Service | Port | Purpose |
|---|---:|---|
| `ui` | 8501 | Streamlit cockpit, incident workbench, decisions and monitoring |
| `api` | 8000 | FastAPI query/command layer and LangGraph runtime |
| `mcp-sim` | 8100 | Strict stateless MCP simulation endpoint |
| `postgres` | 5432 | Operational read model and LangGraph checkpoints |
| `test` | profile only | Reproducible framework, workflow and coverage gate |

The API and UI share the app image. The MCP simulator has a smaller purpose-specific image. Both images support staged corporate CAs.

## Responsibility separation

```mermaid
flowchart TB
    OP[Operator] --> UI[Streamlit]
    UI -->|Queries and typed human decisions| API[FastAPI]
    API --> READ[(Operational read model)]
    API --> GRAPH[LangGraph case controller]
    GRAPH <--> CHECKPOINT[(PostgreSQL checkpoints)]
    GRAPH --> RULES[Deterministic rules, budgets and policy]
    GRAPH --> LLM[Optional LangChain RCA assistant]
    LLM -->|Validated proposal only| GRAPH
    GRAPH --> MCP[MCP HTTP client]
    MCP --> SIM[MCP simulation tools]
    SIM --> EFFECTS[(Idempotency and consumed approvals)]
    GRAPH --> READ
```

- Streamlit never queries checkpoint tables.
- The model receives a compact evidence packet and never executes tools.
- LangGraph selects every read or write tool call.
- Every side effect is simulated and requires a matching signed approval token.
- PostgreSQL holds two different concerns: durable graph checkpoints and a queryable operational read model.
- The MCP effect store is separate because checkpoint replay safety does not itself deduplicate an external effect.

## Workflow runtime

The portable workflow engine is the single source for process-step logic. The LangGraph wrapper adds:

- one thread per incident;
- durable checkpoints;
- conditional transitions;
- a dedicated exactly-one-interrupt approval node;
- same-thread resume after a human decision.

Effect execution occurs only after the approval node resumes and routes to the next process step. The full Docker verification recreates the workflow service while an incident is paused, then resumes it from the PostgreSQL checkpointer.

## Replay and history controls

Three layers address different replay risks:

1. **Graph state replay:** deterministic event/action identifiers and replay-safe append methods suppress identical evidence, timeline and action records.
2. **Operational read model:** stable incident, approval and idempotency identifiers upsert rather than create random duplicates.
3. **External-effect boundary:** the MCP effect store returns the prior result for the same idempotency key and rejects reuse of a consumed approval for another key.

Work-order and MR collections preserve later status revisions while dropping an identical repeated revision.

## MCP compatibility profile

The mockup uses an explicit compatibility profile:

```text
MCP_PROFILE=custom_stateless_2026
MCP_PROTOCOL_VERSION=2026-07-28
MCP_STRICT_VERSION=true
```

The API checks the MCP `/health` response before workflow startup and fails on profile, protocol-version or statelessness mismatch. The custom implementation exposes only the tool-list and tool-call subset required by the demonstration.

## Shared measurement and projection layer

Stage 2 adds one semantic contract above the existing repositories:

```mermaid
flowchart LR
    DT[Digital Twin immutable run] --> DTP[Canonical run projection]
    OPS[Live workflow repository] --> OPP[Operations projection]
    PLAN[Seeded planning model] --> PM[Planning mode only]
    DTP --> CONTRACT[Shared grains, formulas, status partition and provenance]
    OPP --> CONTRACT
    CONTRACT --> EXEC[Executive / Predictive / Care / Operations views]
    PM --> LEGACY[Legacy Control Tower planning panels]
```

The projections share definitions without pretending the repositories are the
same population. The Digital Twin projection reads complete run datasets; the
Operations projection reads the complete workflow repository and resolves
`parent_incident_id` to a durable root. Paginated tables never drive headline
counts. See `docs/SHARED_MEASUREMENT_CONTRACT.md`.

## DvSum CADDI / Genesys call-center boundary

DvSum CADDI is the existing LPR call-center correlation and presentation layer integrated
with Genesys. It is represented explicitly in this bundle as a contract-only layer;
there is no live DvSum CADDI client or source data connection.

```mermaid
flowchart LR
    SRC[CSG / OTS / Intraway / NXT / Symphonica / Dvision-LLA / Plume] -->|authoritative facts| DvSum CADDI[DvSum CADDI context]
    GEN[Genesys interaction] --> DvSum CADDI
    DvSum CADDI --> AGENT[Call-center agent]
    SRC --> ASSURE[Assurance and orchestration]
    ASSURE --> OPS[Operations / Clean Boots / jTrack / repair]
    OPS -->|customer-safe state projection| DvSum CADDI
```

The originating systems remain authoritative. DvSum CADDI correlates and presents the
context needed by the call center. Operations remains authoritative for incident,
work-order, MR, maintenance, repair and validated closure state. The preferred
target is to augment or federate with DvSum CADDI before considering selective replacement.
See `docs/CADI_INTEGRATION_CONTRACT.md` for the capability and discovery contract.

## LPR data represented by fixtures

- CommScope ServAssure NXT alarm and health evidence
- HFC DOCSIS/PNM and shared-node context
- PON OLT/ONT optical evidence and ODP topology
- customer, CPE and Wi-Fi context
- customer ticket and prior-incident context
- Clean Boots measurements, photos and delimiter findings
- WFM work orders and jTrack MR lifecycle
- Dirty Boots/plant actions and post-fix validation

## Operational boundary

- HFC delimiter: tap
- PON delimiter: ODP
- Clean Boots: CPE, Wi-Fi, premise wiring and customer-side/drop work
- Dirty Boots: access network, distribution/feeder, OLT/node and plant-side work
- Joint: cases where both responsibility domains are implicated
- Reverse handover: same incident, evidence contract, attempt history and SLA clock
