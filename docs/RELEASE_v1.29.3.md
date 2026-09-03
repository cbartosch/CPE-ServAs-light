# Release v1.29.3 RC3 — reliable P1 handoff and hardened P2 quarantine

This corrective candidate descends from immutable v1.29.2 and the P1 reliability
RC2. It retains the atomic, resumable install handoff and closes the minimum P2
findings required before post-action quarantine can be treated as a mandatory
closure control.

## P1 retained from RC2

- The handoff claim, deterministic repair incident, assurance episode and initial
  lineage event are created in one database transaction.
- A bounded durable lease makes interrupted workflow start retryable.
- Parallel identical requests converge on one episode, incident and workflow
  owner; incompatible replay is rejected.
- Concurrent Digital Twin receipt writers converge on one authoritative receipt.
- The target-reported Ruff `B904` paths use explicit `raise ... from None`.

## One atomic P2 transition

Each accepted observation is processed under one repository transaction and one
locked quarantine row. The transaction contains all five durable effects:

1. append the scoped quarantine observation;
2. update the quarantine state and version;
3. update the canonical incident state and timeline;
4. synchronize the shared assurance episode; and
5. append the corresponding episode lineage event.

An exception before commit rolls back the complete transition. Retrying the same
idempotency key can therefore perform the work instead of returning a stranded
partial observation.

## Server-authoritative time

`received_at` is assigned by the workflow service and controls due-time checks,
minimum duration, extensions, completion and lease validity. `observed_at` is an
external measurement timestamp retained for audit only. It must be timezone-aware,
monotonic within a quarantine and within the configured clock-skew bound. A future
measurement cannot release a quarantine before server time reaches the minimum.

## Terminal-state and replay rules

Released, reopened and escalated quarantines reject every new observation. An
exact replay of a previously committed observation remains safe and returns the
stored observation and current canonical state. Idempotency is unique within
`(quarantine_id, idempotency_key)`, allowing the same adapter-local key to be used
for a different quarantine. A canonical request fingerprint detects changed
health, measurement time, metrics or trusted identity under the same scoped key.

## Concurrency and leases

PostgreSQL uses `SELECT ... FOR UPDATE` around observation evaluation and
persistence, preventing lost counters and competing terminal transitions. SQLite
uses an in-process lock for the local test profile. Every due-job claim receives a
new random lease token. Scheduled mutation requires the matching owner, token and
unexpired lease; after expiry another worker can claim a new token and the stale
worker is rejected.

## Trusted mutation boundary

The install handoff, quarantine-observation and run-due endpoints require
`X-LPR-Internal-Token`. The request body can no longer supply quarantine actor or
source. Those values are derived from authenticated runtime settings and stored in
the observation and lineage event. With no configured token, mutation endpoints
fail closed with HTTP 503.

This is a service-to-service demonstration token, not a replacement for production
OIDC, workload identity, token rotation or signed source artifacts.

## PostgreSQL acceptance profile

`tests/test_post_action_quarantine_p2_postgres.py` covers:

- interruption rollback;
- same-key parallel convergence;
- serialization of distinct observations without lost updates;
- unique-token lease exclusion and expiry takeover;
- scoped replay and changed-payload rejection; and
- server-time and terminal-state enforcement; and
- migration of the RC2 standalone global unique index to scoped uniqueness.

Run it through `scripts/test_p2_postgres.ps1` or
`scripts/test_p2_postgres.sh`. Each test uses a disposable PostgreSQL schema and
drops it after the test.

## Required target gates

```text
python -m ruff check src scripts tests
python -m pytest
python scripts/run_scenario_matrix.py
python scripts/verify_manifest.py
docker compose config
scripts/test_p2_postgres.ps1
scripts/verify_docker.ps1
scripts/test_bundle.ps1
```

The Docker verifier creates a random local workflow token in an untracked `.env`
when the value is blank and runs an authenticated degraded-health smoke. The smoke
uses an immediate reopen transition rather than bypassing or waiting through the
configured stability duration.

## Retained boundaries

- Production writes remain disabled by default.
- Health generation remains simulated until approved NXT/service-test adapters
  are connected.
- The internal-token boundary is appropriate for the demo, not final production
  authentication.
- Live PostgreSQL, Docker Desktop, Python 3.14.7 and Ruff 0.13.3 remain mandatory
  target-workstation gates.
- Earlier release commits and tags must not be amended or moved.
