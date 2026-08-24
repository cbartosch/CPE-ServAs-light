# P0 remediation status — v2.4.0 P0 Fixed R3

R3 addresses the independent R2 Git-bundle audit findings.

| R2 independent-audit finding | R3 status | Release evidence |
|---|---|---|
| Broad fail-closed quality gate still accepts 14 critical mutations | **Fixed + regression tested** | canonical graph validation, non-empty evidence, MR chronology, delimiter validation and reconciliation-policy recomputation; test 31 reproduces all 14 audit cases |
| Repeat cases become new/independently closed incidents | **Fixed + regression tested** | repeat attempts share `root_incident_id`; no child incident is generated; 30-day window + supervisor escalation enforced; test 32 + 500k stress |
| Hard Phase-1 operating controls not enforceable | **Fixed + regression tested** | job readiness/skills/parts/access gates, separate failed CPE diagnostic, closure checklist/objective evidence; test 33 |
| Live human approval changes only SQLite | **Fixed + regression tested** | live approval updates exported human/action records, materializes action/validation/resolution, re-hashes catalog and closes mutable case when restored; test 34 |
| Concurrent same-run generation / interrupted run recovery | **Fixed + regression tested** | per-run lock + atomic staging promotion + rebuild of incomplete run; test 35 |
| API client errors returned 500 | **Fixed + regression tested** | invalid run ID -> 400; unsupported Parquet request -> 422; test 36 |
| Docker non-root `/data` permission risk | **Code fixed; runtime Docker verification pending** | image creates/chowns `/data`; test 37 statically validates the contract |

R3 keeps production integrations/writes out of scope. Request-evidence/reject/escalate outcomes are durably mirrored into exports, but a future evidence-submission/resume workflow can further extend those non-approved branches.
