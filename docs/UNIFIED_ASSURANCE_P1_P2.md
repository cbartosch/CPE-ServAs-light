# Unified repair, install and post-action quarantine assurance

## Intent

The platform remains the process orchestrator and assurance backbone. Source
systems retain authority. Analytics may suggest and explain, while deterministic
policy and approved human gates govern execution.

## Shared episode

Every repair case is projected into an `AssuranceEpisode`. An eligible degraded
install watch creates an install-origin episode when it is promoted into the
canonical repair workflow.

```text
Install watch --promote--> Assurance episode --> Repair incident
Repair intake -----------> Assurance episode --> Repair incident
```

The source-derived handoff claim, deterministic incident, shared episode and
initial event are created atomically. A durable lease lets an interrupted workflow
start resume, and parallel identical requests converge on the same canonical
records.

## Mandatory P2 loop

```text
Pre-action evidence
  -> policy and approval gate
  -> controlled simulated action
  -> immediate post-action check
  -> durable quarantine
  -> repeated server-timed observations
  -> release and close | reopen | extend | escalate
```

A successful immediate test is necessary but not sufficient for closure.

## Atomic observation contract

One accepted observation produces one database transaction containing:

- the append-only observation;
- the versioned quarantine transition;
- the incident transition and timeline event;
- the synchronized assurance episode; and
- the append-only episode lineage event.

The PostgreSQL path locks the quarantine row before evaluation. The local SQLite
profile serializes the same critical section in process. An injected failure before
commit leaves none of the five effects behind.

## Time semantics

- `received_at`: server-authoritative time used for due checks, minimum duration,
  extension, completion and lease validity.
- `observed_at`: external measurement time retained for evidence only.
- External time must be aware, monotonic and within
  `POST_ACTION_QUARANTINE_MAX_MEASUREMENT_CLOCK_SKEW_SECONDS` of receipt time.
- Healthy or unknown checks before `next_check_at` are rejected. Degraded health
  can reopen immediately.

## Replay and terminal semantics

Observation identity is scoped to `(quarantine_id, idempotency_key)`. A canonical
SHA-256 fingerprint covers health, measurement time, metrics and trusted actor and
source. Exact replay returns the stored observation and current canonical state; changed replay is a conflict.
Released, reopened and escalated quarantines accept no new key, so a late message
cannot move a closed incident back into quarantine.

## Scheduler lease

Every claim stores owner, random lease token and expiry. Scheduled observation
requires all three values to match the locked row. A live lease excludes other
workers. After expiry a new worker receives a new token, and the former owner can
no longer commit.

## Trusted mutation APIs

These routes require `X-LPR-Internal-Token`:

- `POST /api/assurance/install-handoffs`
- `POST /api/assurance/quarantines/{quarantine_id}/observations`
- `POST /api/assurance/quarantine-jobs/run-due`

Actor and source are runtime-derived and cannot be supplied in a quarantine body.
Read APIs remain available to the demonstration UI. The token is a demo
service-to-service boundary; production workload identity and signed artifacts
remain future integration work.

## Durable records

PostgreSQL stores:

- assurance episodes and lineage events;
- install-handoff state, fingerprint and lease;
- versioned post-action quarantine state;
- scoped observations with measurement and receipt times;
- scheduler lease owner, token and expiry; and
- existing incident, approval and effect-idempotency records.

Digital Twin install-watch source files stay immutable, and concurrent receipt
writers converge on one separate authoritative receipt.

## Transition table

| Observation | Server-time condition | Outcome |
|---|---|---|
| Healthy | Before duration or required count | Continue; closure blocked |
| Healthy | Duration and count satisfied | Release, reconcile and close |
| Degraded | Any time while active | Reopen same incident |
| Unknown | Extension budget remains | Extend |
| Unknown | Extension budget exhausted | Escalate |
| Any new key | Quarantine terminal | Reject |
| Exact prior key and content | Any later retry | Return stored observation and current state |

## Verification

The default test suite covers the portable/SQLite profile. The mandatory
PostgreSQL profile uses disposable schemas and explicitly exercises rollback,
parallel replay, row-lock serialization, lease takeover, scoped idempotency,
server-time enforcement and terminal immutability.
