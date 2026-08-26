# Executive demo experience — Stage 2

Stage 2 reconciles the presentation semantics without changing deterministic
operating controls. The Digital Twin workspace remains organized around:

1. **Prevent** — identify forecast-risk and currently degraded services.
2. **Connect** — measure customer contacts and attach them to a durable root
   incident.
3. **Control** — keep case attempts, approvals and action workload separate from
   mutually exclusive root-incident status.
4. **Prove** — expose complete evidence, provenance and reconciliation checks.

## Shared active-run context

Executive View, Predictive Health, Customer Experience and the active-run legacy
Control Tower now use `/api/runs/{run_id}/executive-projection`. Each surface
shows the same run ID, as-of time, population, scan coverage, primary grain and
completeness status. Headline figures are calculated from complete immutable
datasets rather than paginated table rows.

## Metric waterfall

```text
services in footprint
  → devices scanned
  → forecast-risk + degraded = unique at-risk services
  → matched + reactive-only = Care contacts
  → case attempts ≥ root incidents
  → open + waiting + closed + escalated + quarantined = root incidents
```

Care priority and predictive network-risk severity remain separate. The former
`duplicate incidents avoided` label is replaced by the observable count of
contacts attached to a canonical root incident.

## Legacy Control Tower

The Control Tower defaults to **Active run evidence**. Its seeded fault and cost
model remains available as **Planning model**, with a separate context ribbon and
no blending into active-run KPIs. Shape-only service-health panels are off by
default. The requested dark-grey legacy background is unchanged.

## Operations Cockpit

The Operations Cockpit projects the complete workflow repository through the same
metric schema. It explicitly states that live Operations is not implicitly linked
to the active Digital Twin run, so values may legitimately differ. Common-cause
children are collapsed through `parent_incident_id`; approvals and action counters
remain separate workload measures.

## Child scans

A fresh predictive scan is an exploratory child artifact with its own population,
trend window and simulation day. It does not alter the parent run, executive
scorecard or Care queue unless a future governed promotion operation is added.

## Stage boundary

DvSum DALLI remains the explicit Genesys-facing context layer from Stage 1. Stage 2 does
not add a live DvSum DALLI adapter and does not implement the 24-Hour Install Assurance
Watch.
