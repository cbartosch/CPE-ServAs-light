# Audit — v1.27.2 Wave 1 cost and canonical-data integrity

## Verdict

Wave 1 is implemented as a review candidate. It closes the data-integrity and
cost-basis issues assigned to the first remediation wave. Waves 2 and 3 remain
explicitly unimplemented and gated by operator sign-off.

## Scope delivered

- Verify every catalogued immutable dataset SHA-256 and row count before costing.
- Require the current run schema and reject older cost-incompatible runs.
- Require every case to join to its subscriber, root incident, deterministic
  decision and action event.
- Require work-order, MR, validation and resolution records to remain on the
  canonical case graph.
- Reject duplicate work-order identities and report MR revision identities.
- Store immutable scenario truth in each case manifest and keep it separate from
  the deterministic recommendation.
- Require PASS, stable telemetry and the full closure checklist before a
  validation can support a resolution.
- Use generated work-order time, road distance, ferry and overnight facts for
  generated-execution cost.
- Keep the planning route comparison-only for executed work and use it only for
  governed forecasts.
- Split executed and forecast truck-roll, ferry and overnight exposure.
- Expose case-weighted and root-incident household-impact grains and explicit
  Dirty Boots denominators.
- Return a structured HTTP 409 integrity report rather than a partial financial
  result when a control fails.

## Full-scale deterministic check

A fresh 500,000-home board-profile run covering all 13 Digital Twin scenarios
completed successfully in the audit runtime:

```text
homes                                      500,000
case attempts                                2,500
root incidents                               2,253
catalogued datasets verified                    20
catalogued rows verified                    612,675
execution-economics incomplete cases              0
exact work-order/MR identifier sets match       yes
executed cases importing model-route premiums      0
```

Measured in the audit runtime:

```text
generation time              23.38 seconds
projection time               5.74 seconds
peak generation RSS         246,236 KiB
peak projection RSS         208,676 KiB
```

The projection time and complete-response size remain Wave 2 work; this wave
prioritizes correctness and fail-closed behavior.

## Negative and mutation checks

The focused suite proves that projection fails when:

- a catalog hash no longer matches its dataset;
- an expected row count no longer matches;
- the run uses an older schema without generated execution economics;
- a subscriber or root-incident join is missing;
- immutable scenario truth is missing;
- a resolution cites a non-passing validation;
- a mixed-region delimiter is present.

The API returns HTTP 409 with:

```json
{
  "error": "dispatch_projection_integrity_failed",
  "issues": ["..."],
  "run_id": "RUN-..."
}
```

## Regression evidence

Passed in the assembly environment:

```text
20 Wave 1 dispatch/cost tests
complete Digital Twin P0 module
API and shared-measurement tests
External Evidence and LLM-triangulation tests
Install Assurance regression tests
executive/dashboard and DvSum DALLI tests
workflow, approval, MCP, security and red-team tests
telemetry and lint-baseline tests
governed nine-scenario matrix
Python compileall for src, scripts and tests
Compose structural validation
git diff --check
```

The Wave 1 dispatch/cost module reached 88% statement coverage under its focused
mutation and integration suite.

The complete 888-test collection was audited per module to avoid the long-running
single-process suite retaining generated data between modules:

```text
882 passed
4 inherited failures
2 skipped
```

The inherited failures are unchanged from the Stage 5 re-audit:

- clean-clone `.env` expectation;
- automatic Docker `--trusted-host` fallback;
- static FastAPI route-reachability heuristic;
- stale Python 3.12 Docker assertion while the project targets Python 3.14.2.

A clean-tree manifest and complete bundle check are executed after release
metadata is finalized and are recorded in `BUILD_TEST_REPORT.txt`.

## Preserved behavior

Wave 1 does not change:

- Stage 2 metric formulas or active-run measurement semantics;
- Stage 3 Install Assurance behavior;
- Stage 4 External Evidence ingestion or LLM authority boundaries;
- the governed nine-scenario workflow outcomes;
- production-write safety controls.

## Deferred Wave 2 work

- run-keyed materialization and cache;
- summary/page/detail endpoints;
- root-incident consolidated cost and repeat-work economics;
- common-cause work-order/MR reuse policy;
- configurable and imported footprint archetype weights.

## Deferred Wave 3 work

- inherited Install Assurance semantic and concurrency fixes;
- strict TLS with no automatic trusted-host fallback;
- clean-clone environment bootstrapping;
- startup retry, dependency-aware readiness and Docker DNS hardening;
- production-like network exposure and authentication.

## Limitations

The assembly environment did not provide Docker Engine, Python 3.14.2 or the
pinned Ruff 0.13.3 executable. The exact Windows/Docker acceptance commands in
the delivery response remain mandatory before sign-off.
