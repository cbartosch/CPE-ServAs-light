# Data dictionary — v2.4.0 P0 Fixed R3 Hotfix5

The canonical release writes 20 gzip-compressed JSON Lines datasets:

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
17. `predictive_modem_pulls`
18. `predictive_tickets`
19. `care_tickets`
20. `care_ticket_reviews`

## Predictive modem fields

- `predictive_modem_pulls.pull_id`: unique evidence record for one modem in one scan.
- `scan_id`, `scan_timestamp`: predictive scan identity and time.
- `service_id`, `device_id`, serial/MAC and delimiter fields: cross-correlation keys.
- `source_system`: synthetic TR-069/TR-181/NXT adapter in this release.
- `engine`: integrated host predictive scanner or compatible standalone fallback.
- `trend_window_days`: number of samples considered.
- `kpis`: per-KPI first/latest value, slope, R-squared and sample count.
- `predictive_tickets.ticket_class`: `forecast` or `proactive`.
- `predictive_tickets.findings`: threshold, direction, current breach, days-to-breach, slope and R-squared evidence.

## Customer Care fields

- `care_ticket_id`: unique governed Customer Care ticket.
- `contact_id`, `case_id`, `root_case_id`, `incident_id`: canonical journey linkage.
- `priority`, `sla_due_at`, `status`, `closed_at`: care queue state.
- `predictive_match`, `predictive_ticket_id`: predictive correlation.
- `correlation_disposition`: attach to predictive or reactive canonical root incident.
- `duplicate_incident_suppressed`: must be `true`.
- `production_write`: must be `false`.
- `care_ticket_reviews`: deterministic domain/action, agent output, reconciliation requirement, predictive context and evidence references.

## Existing R3 control fields

- `scenario_manifests.repeat_of_case_id`, `repeat_sequence`, `supervisor_escalation_required`: repeat chain and escalation policy.
- `incidents.repeat_count`, `reopen_count`, `last_repeat_at`: durable repeat lifecycle.
- `work_orders.diagnosis_completed_at`, `readiness_checked_at`, `assigned_at`: diagnosis/readiness before dispatch.
- `work_orders.required_skill`, `technician_skill`, `skill_confirmed`: skill gate.
- `work_orders.parts_required`, `parts_confirmed`, `cpe_available`, `access_confirmed`, `readiness_passed`: material/access gates.
- `work_orders.replacement_started_at`, `precondition_evidence_refs`: CPE swap authorization chain.
- `field_evidence.diagnostic_result`, `documented_reason`: diagnostic/repair evidence.
- `mrs.evidence_refs`, `completion_evidence_refs`: MR evidence chain.
- `validation_events.evidence_refs`, `closure_checklist`: objective restoration and closure proof.
- `human_decisions.supervisor_escalation`: mandatory for repeats.
- `action_events.production_write`: always `false`.

Operator-requested predictive pulls are stored as child artifacts beneath `predictive_scans/SCAN-*` with `summary.json`, `predictive_modem_pulls.jsonl.gz` and `predictive_tickets.jsonl.gz`. They are deliberately outside the canonical catalog so the parent run remains immutable.
