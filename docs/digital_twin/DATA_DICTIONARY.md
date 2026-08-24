# Data dictionary — v2.4.0 P0 Fixed R3

The release writes the same 16 gzip-compressed JSON Lines datasets:

1. `subscriber_master`
2. `scenario_manifests`
3. `telemetry_tr181`
4. `nxt_alarms`
5. `contacts`
6. `incidents`
7. `work_orders`
8. `field_evidence`
9. `mrs`
10. `validation_events`
11. `resolution_events`
12. `deterministic_decisions`
13. `agent_decisions`
14. `reconciliation_records`
15. `human_decisions`
16. `action_events`

## R3 correlation and control fields

- `scenario_manifests.case_id`: unique attempt/correlation ID.
- `scenario_manifests.root_case_id`: durable case that owns the incident.
- `scenario_manifests.root_incident_id`: single incident shared by root and repeat attempts.
- `scenario_manifests.repeat_of_case_id`, `repeat_sequence`, `supervisor_escalation_required`: repeat chain and escalation policy.
- `scenario_manifests.delimiter_type`, `delimiter_id`: subscriber-bound HFC tap / PON ODP identity.
- `incidents.repeat_count`, `reopen_count`, `last_repeat_at`: durable repeat lifecycle.
- `work_orders.diagnosis_completed_at`, `readiness_checked_at`, `assigned_at`: enforce diagnosis/readiness before dispatch.
- `work_orders.required_skill`, `technician_skill`, `skill_confirmed`: skill gate.
- `work_orders.parts_required`, `parts_confirmed`, `cpe_available`, `access_confirmed`, `readiness_passed`: material/access readiness gates.
- `work_orders.replacement_started_at`, `precondition_evidence_refs`: CPE-swap authorization chain.
- `field_evidence.diagnostic_result`, `documented_reason`: explicit diagnostic/repair evidence.
- `mrs.evidence_refs`: initial evidence that must exist before MR creation/acceptance.
- `mrs.completion_evidence_refs`: completion evidence captured before MR completion.
- `validation_events.evidence_refs`: non-empty objective evidence set including healthy post-fix telemetry.
- `validation_events.closure_checklist`: all required closure checks must be true.
- `human_decisions.supervisor_escalation`: mandatory for repeats.
- `action_events.production_write`: must always be `false`.

`human_decisions.status` may be `PENDING`, `APPROVED`, `NOT_REQUIRED`, `EVIDENCE_REQUESTED`, `REJECTED` or `ESCALATED`; corresponding action states are `BLOCKED_PENDING_HUMAN`, `SIMULATED_EXECUTED`, `BLOCKED_NEEDS_EVIDENCE` or `BLOCKED_ESCALATED`.
