# Shared Measurement Contract — Stage 2

## Purpose

Stage 2 fixes the semantic mismatch between the legacy Executive Control Tower,
the Digital Twin Predictive/Customer Care workspace and the live Operations
Cockpit. Navigation alone did not make their figures comparable: each surface
used a different population, record grain, time window and data source.

The implementation now publishes one machine-readable metric contract and two
source projections:

```text
Digital Twin canonical run ──┐
                             ├── shared measurement schema ── dashboards
Live workflow repository ────┘

Legacy seeded fault model ───── planning mode only; never blended with run KPIs
```

Equal definitions do not imply equal values. The Digital Twin and Operations
repositories remain different populations until explicit run/service identity is
projected between them.

## Canonical grains

| Entity | Key | Meaning |
|---|---|---|
| Footprint service | `service_id` | One subscribed broadband service |
| Device | `device_id` | One modem, gateway or ONT |
| Predictive risk record | `predictive_ticket_id` | One canonical risk record |
| Customer contact | `contact_id` | One customer interaction |
| Care workflow record | `care_ticket_id` | Contact-grain record in the demo |
| Root incident | `incident_id` | Durable executive and status grain |
| Case attempt | `case_id` or operational `IncidentState` | One diagnosis/action attempt |
| Approval | `approval_id` | One human-decision object |
| Field work | `work_order_id` | One field execution record |
| Plant handoff | `mr_id` | One MR lifecycle identity |

The default rule is:

> Executive and operational status KPIs count unique root incidents unless the
> label explicitly says services, devices, contacts, case attempts, approvals,
> work orders or MRs.

## Common measurement context

Every active-run or live-operational view exposes:

```text
mode
source
run_id or explicit not-linked state
as_of
window
primary_grain
completeness
scan coverage when available
planning_model flag
```

The Digital Twin projection reads complete immutable datasets. The Operations
projection reads the complete workflow repository. Paginated rows are display
artifacts and are never the source of headline totals.

## Canonical metrics

The contract is available from both APIs at:

```text
GET /api/measurement-contract
```

Core definitions include:

| Metric | Definition |
|---|---|
| Services in footprint | Distinct eligible `service_id` population |
| Devices scanned | Distinct devices with a canonical predictive pull |
| Scan coverage | Scanned devices divided by eligible services/devices |
| At-risk services | Distinct services with a canonical predictive risk |
| Forecast-risk services | At-risk services forecast to breach, not currently degraded |
| Currently degraded services | Distinct services with a current threshold breach |
| Care contacts | Distinct customer contacts |
| Predictive match rate | Matched contacts divided by all Care contacts |
| Canonical root attachments | Contacts carrying a durable root-incident reference |
| Root incidents | Distinct durable root identities |
| Case attempts | Distinct diagnosis/action attempts; may exceed root incidents |
| Pending approvals | Pending approval objects, outside incident status totals |
| Field-dispatched root incidents | Roots with field work |
| Work orders | Distinct work-order identities |
| Maintenance requests | Distinct MR identities |

The former `duplicate incidents avoided` headline is not treated as observed. The
synthetic Care generator attaches contacts to a canonical root incident, but it
does not emit an audited attempted duplicate-creation event. The supported metric
is therefore `canonical_root_attachments`; an actual interception counter remains
unavailable until such events exist.

## Mutually exclusive status partition

All dashboards use:

```text
open + waiting + closed + escalated + quarantined = root incidents
```

Pending approvals, case attempts, contacts, remote attempts, field visits and MR
attempts are workload counters. They are displayed separately and are not added to
the status partition.

For live Operations, `parent_incident_id` collapses common-cause child cases into
one durable root. A root is closed only when every related case is closed; active,
waiting, escalated or quarantined states take precedence.

## Digital Twin projection

The existing executive projection is now the authoritative source for active-run
headline metrics:

```text
GET /api/executive-projection
GET /api/runs/{run_id}/executive-projection
```

It publishes:

```text
measurement_context
metrics
status_partition
predictive_funnel
care_funnel
operational_funnel
workload
data_completeness
reconciliation
provenance
customer stories
```

The projection joins predictive records, Care contacts, root incidents,
deterministic and agent decisions, reconciliation, human decisions, actions,
validation and resolution.

## Live Operations projection

The operational API publishes the same schema at:

```text
GET /api/operations-projection
GET /api/measurement-projection
```

Predictive and Care metrics are explicitly unavailable when the workflow
repository cannot observe them. The UI does not substitute zeros. The Operations
Cockpit can compare its values with the active Digital Twin run, but clearly marks
the populations as not implicitly linked.

## Display rules

1. The legacy Control Tower defaults to **Active run evidence**.
2. Its seeded fault generator remains available only as **Planning model**.
3. Shape-only service-health curves are off by default.
4. Predictive child scans are labelled exploratory and do not alter the canonical
   run, executive scorecard or Care queue.
5. Queue and dataset endpoints expose `total`, `filtered_total`, `returned` and
   `truncated` metadata where applicable.
6. Care priority and predictive network-risk severity remain separate concepts.
7. `quality checks` is presented as `data-integrity controls`.
8. CADI remains the Genesys-facing context layer; no live CADI adapter is claimed.

## Reconciliation invariants

The Digital Twin projection fails its semantic reconciliation status when any of
the following is false:

```text
forecast-risk services + degraded services = at-risk services
matched contacts + reactive-only contacts = all Care contacts
open + waiting + closed + escalated + quarantined = root incidents
case attempts >= root incidents
scanned devices <= services in footprint
canonical root attachments <= Care contacts
headline totals are derived from complete aggregates, not page rows
```

The Operations projection enforces the applicable root-status, case/root and
pagination invariants.

## Stage boundary

Stage 2 includes semantic reconciliation only. It does **not** implement the
24-Hour Install Assurance Watch, assurance-episode lifecycle, short-horizon
install detector or install metrics. Those remain Stage 3 and require explicit
operator sign-off on this stage first.
