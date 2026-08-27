# Audit — v1.26.0 approval scope and scenario-matrix gate repair

## Scope

This patch addresses only the two release-blocking findings requested after the
Stage 3 deep audit:

1. application-generated approval tokens omitted the action's restart-stable
   `idempotency_key`; and
2. `scripts/run_scenario_matrix.py` accepted any terminal state and printed PASS
   without checking the intended outcome.

The remaining Stage 3 deep-audit findings are unchanged and remain open. This
patch is not a Stage 3 sign-off.

## Approval-token correction

`build_approval_token()` now signs the exact key stored on `ApprovalRequest`:

```text
approval_id
incident_id
action_type
idempotency_key
status
expiry
```

The MCP execution boundary already verifies the same four scope fields before a
side effect. The application and the verifier now share one scope contract.
Manual token helpers in the MCP tests were updated accordingly.

## Scenario-matrix correction

The matrix now has an explicit contract for all nine deterministic scenarios.
It checks:

- expected terminal status;
- exact action sequence;
- remote, self-help, field and MR counters;
- diagnostic-cycle count;
- verification result;
- preservation of the original incident identity;
- work-order record count, uniqueness and outcomes; and
- MR record count, uniqueness and outcomes.

Missing, duplicate or unexpected scenarios fail the gate. Any field mismatch
fails the gate. A second guard rejects a result set in which every scenario has
an empty action history.

## Acceptance evidence

The corrected scenario matrix produces the intended outcomes, including:

- `hfc_remote_success` closes through one remote reprovision;
- `hfc_remote_fail_clean_success` returns to RCA and closes through Clean Boots;
- `pon_odp_handover` creates one MR after one failed Clean Boots visit;
- `hfc_failed_plant_action_rerca` updates one MR across failed and successful
  revisions; and
- `bounded_remote_failure` is the only expected escalation.

The new regression suite directly verifies the signed idempotency claim and
proves that a nominal scenario changed to `escalated` with no action history is
rejected by the matrix validator.

## Executed validation

```text
PASS  69 focused workflow, MCP, API, red-team and release-gate tests
PASS  all nine deterministic scenarios against the explicit result contract
PASS  833 tests in the complete per-file audit
SKIP  2 environment-dependent tests
KNOWN 4 inherited failures outside this patch scope
PASS  282 / 282 integrity-manifest entries
PASS  Python compileall for source, scripts and tests
PASS  git diff --check
```

The four inherited failures are unchanged from the audited parent: the clean
clone does not contain `.env`, two Dockerfiles still permit the documented
`--trusted-host` fallback, the static reachability heuristic misclassifies
FastAPI route handlers, and one test still expects a Python 3.12 base image while
the project targets Python 3.14.2.

## Non-scope

No changes were made to Stage 2 metric semantics, DvSum DALLI naming, Install
Assurance episode generation, Docker networking/TLS policy, or the other open
findings in the Stage 3 deep audit.
