# Workflow — v2.4.0 P0 Fixed R3 Hotfix5

1. Validate configuration and derive the immutable run ID from the complete generation config.
2. Generate the subscriber/service/CPE footprint and technology-compatible case attempts.
3. Create pre-action TR-181 telemetry, NXT alarms and customer contacts. Repeats attach to the existing root incident.
4. Generate a service/device-correlated predictive modem snapshot. In the integrated host this is classified by `lpr_cpe_demo.predictive.scanner` into `forecast` and `proactive` tickets.
5. Correlate predictive tickets to later Customer Care contacts by service/device and time. A matched call attaches to the existing predictive root incident; it does not create duplicate work.
6. Promote contacts to governed `care_tickets` and create `care_ticket_reviews` that combine predictive context, deterministic RCA, model output and reconciliation state.
7. Produce deterministic RCA/action eligibility from case-local evidence IDs.
8. Produce the LLM/model challenge when enabled, otherwise an explicit fake/disabled/unavailable state.
9. Reconcile model and deterministic decisions. Repeat attempts add a non-bypassable supervisor-review requirement.
10. Stop live human-gated cases at `BLOCKED_PENDING_HUMAN`; no downstream work, MR, validation or resolution exists before approval.
11. For approved/policy-auto history, materialize only the selected branch.
12. Before any field assignment, require diagnosis, matching skill, parts/CPE, access and readiness.
13. For CPE replacement, require a separate failed diagnostic plus reason before replacement begins.
14. For MR/plant work, enforce evidence -> MR create -> accept -> dispatch -> repair -> completion evidence -> MR complete.
15. Generate healthy post-fix telemetry when a restoring action succeeds.
16. Require PASS/stable service validation, objective evidence and the complete closure checklist before resolution.
17. Mirror root-incident closure into the linked Customer Care ticket.
18. Run the 20-group fail-closed quality gate, including predictive/care causality and deduplication.
19. Hash all 20 canonical datasets and write the catalog.
20. Operator-requested predictive pulls create immutable `predictive_scans/SCAN-*` child artifacts and never change the canonical catalog.
21. A later live approval updates exported control/action/care records, re-runs quality checks, re-hashes affected canonical files and advances the mutable case state.

## Human-review rules

Human review remains mandatory when the model is fake/disabled/unavailable/invalid, model and deterministic results disagree, evidence is invalid, confidence/safe-to-automate is insufficient, or the action has side effects. A repeat attempt always requires supervisor/senior review.

## Hard operating rules

- No diagnosis/readiness -> no assignment or dispatch.
- No skill/parts/CPE/access confirmation -> no assignment.
- No failed CPE diagnostic -> no CPE replacement.
- No objective PASS/stable validation + checklist -> no closure.
- Repeat -> same root incident + supervisor escalation.
- Predictive finding + later care call -> same service/root incident; never duplicate the incident.
- Predictive correlation is valid only when the predictive ticket predates the customer contact.
