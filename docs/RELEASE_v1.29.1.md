# Release v1.29.1 — unified assurance and post-action quarantine

This release implements P1 and P2 of the target service-assurance architecture.

## P1 — shared repair and install assurance

- `AssuranceEpisode` is the common lifecycle and correlation model for repair-originated and install-originated cases.
- A degraded install-assurance episode can be promoted through the Digital Twin API into the existing repair workflow.
- The handoff is deterministic and retry-safe: the same source key resolves to the same episode and incident.
- PostgreSQL stores the episode read model and append-only episode events.
- The immutable install-watch evidence remains unchanged; a separate workflow handoff receipt records the linkage.

## P2 — mandatory post-action stability control

- The repair workflow records pre-action health before execution.
- A successful action is followed by an immediate post-action health check.
- Closure is blocked in `post_action_quarantine` until the policy duration and repeated healthy-check count both pass.
- A degraded observation returns the same incident to failure review.
- Unknown health extends the window until the configured budget is exhausted, then escalates.
- Quarantine jobs are claimed with durable, expiring leases so API restarts do not lose scheduled work.

## Runtime and governance

- Docker enables P2 by default for the demo; unit-test defaults remain disabled to preserve explicit test control.
- Production writes remain disabled.
- DvSum CADDI is the only canonical product terminology in the current tree.
- Existing deterministic policy, evidence, approval, idempotency and simulation-only action controls remain authoritative.

## Release gates

The delivery verifier requires Python 3.14.7, pytest 9.0.2 and Ruff 0.13.3, then runs compilation, lint, P1/P2 tests, the complete test suite, scenario matrix, manifest verification, terminology checks, Docker Compose validation and optional Docker runtime smoke tests.
