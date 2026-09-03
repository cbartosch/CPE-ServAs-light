# Release v1.29.3 — resumable and concurrent P1 handoff reliability

This corrective release is a descendant of the immutable v1.29.2 release
commit. It closes the two highest-severity P1 reliability findings without
rewriting or moving the v1.29.2 release reference.

## RC2 target-lint closure

The target Python 3.14.7/Ruff 0.13.3 gate found two `B904` findings in the
receipt publication fallback. RC2 explicitly suppresses incidental exception
context for those deliberate terminal race errors with `raise ... from None`
and adds an AST regression guard that runs even where Ruff is unavailable.

## Atomic durable claim

The workflow service now creates or adopts the following records in one database
transaction:

- the canonical install handoff claim;
- the deterministic repair incident;
- the shared assurance episode; and
- the initial `install_handoff_claimed` event.

A failure during canonical-row creation rolls the complete transaction back. A
retry therefore cannot observe a claim without the incident and episode it owns.

## Resumable workflow start

Each handoff has a durable state:

```text
CLAIMED -> WORKFLOW_STARTING -> WORKFLOW_STARTED
                    |
                    +-> FAILED_RETRYABLE -> WORKFLOW_STARTING
```

`WORKFLOW_STARTING` is protected by a bounded lease that the active owner renews
while the workflow executes. An ordinary exception releases the claim as
`FAILED_RETRYABLE`; process termination stops renewal and is recovered after
lease expiry. The configured caller wait must exceed the lease duration. A retry
loads the persisted incident and continues the existing workflow rather than
returning an incomplete episode as successful.

## Concurrent convergence

Database-native conflict-free inserts and a conditional lease acquisition make
parallel identical requests converge on the same source identity. Exactly one
caller owns workflow startup; all other callers wait for and return the canonical
result. A changed payload under an existing source key is rejected as a conflict.

## Receipt publication

Digital Twin receipt writers first create a complete temporary file and then use
atomic no-replace publication. The winning receipt becomes authoritative and all
concurrent losers return its stored content. A lock-file fallback covers file
systems without hard-link support.

## Upgrade behavior

`Repository.setup()` creates the additive `assurance_install_handoff` table for
an existing database. A v1.29.2 episode and incident that predate this table can
be adopted and resumed using their deterministic identities. No existing source
watch file is changed.

## Boundaries retained

- Production writes remain disabled.
- The handoff endpoint is still a simulation integration boundary; production
  authentication and signed source-artifact verification remain separate work.
- PostgreSQL remains the deployment database and SQLite remains the local test
  profile. The release must still pass its PostgreSQL and Docker target gates.
- The v1.29.2 branch, tag and commit must not be moved.

## Verification gates

The corrective release requires:

```text
python -m ruff check src scripts tests
python -m pytest
python scripts/run_scenario_matrix.py
python scripts/verify_manifest.py
docker compose config
docker compose up -d --build --force-recreate
```

The focused P1 gate includes interruption recovery, all-or-nothing claim
creation, v1.29.2 partial-state adoption, changed-payload rejection, 32-way
parallel handoff convergence and parallel receipt convergence.
