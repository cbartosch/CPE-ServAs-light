# Workflow — v2.4.0 P0 Fixed R3

1. Validate configuration and scenario set and derive the immutable run ID from the full config, including `generator_version=2.4.0-r3`.
2. Generate/stream the subscriber/service/CPE footprint and technology-compatible case attempts.
3. Create pre-action telemetry/alarm/contact evidence. A non-repeat creates one root incident; a repeat attaches to the existing root incident and increments its repeat/escalation state.
4. Produce deterministic RCA/action eligibility from case-local evidence IDs.
5. Produce the LLM/model challenge when enabled, otherwise an explicit fake/disabled/unavailable state.
6. Reconcile the model and deterministic decisions. Repeat attempts add a non-bypassable supervisor-review requirement.
7. Stop live human-gated cases at `BLOCKED_PENDING_HUMAN`; no downstream work, MR, validation or resolution exists before approval.
8. For approved/policy-auto history, materialize only the selected branch.
9. Before any field assignment, require completed diagnosis, matching technician skill, confirmed parts/CPE, access and readiness. Dispatch follows assignment.
10. For CPE replacement, capture a separate failed diagnostic plus reason before replacement begins.
11. For MR/plant work, enforce initial evidence -> MR create -> accept -> dispatch -> repair complete -> MR completion evidence -> MR complete.
12. Generate healthy post-fix telemetry when a restoring action succeeds.
13. Require PASS/stable service validation, objective evidence and the complete closure checklist before a resolution can close the root incident.
14. Run the 16-group fail-closed quality gate, including canonical case graph and policy recomputation.
15. Hash all datasets and write the catalog. Concurrent callers for the same run serialize and return the same completed catalog.
16. A later live approval updates exported control/action records, materializes the same simulated branch, re-runs quality checks, re-hashes affected files and advances the mutable case state.

## Human-review rules

Human review is mandatory when the model is fake/disabled/unavailable/invalid, model and deterministic results disagree, evidence is invalid, confidence/safe-to-automate is insufficient, or the action has side effects. **A repeat attempt always requires supervisor/senior review**, even if the base branch would otherwise be read-only.

## Hard operating rules

- No diagnosis/readiness -> no assignment or dispatch.
- No skill/parts/CPE/access confirmation -> no assignment.
- No failed CPE diagnostic -> no CPE replacement.
- No objective PASS/stable validation + required checklist -> no closure.
- Repeat -> same root incident, repeat counter and supervisor escalation; never a new incident.
