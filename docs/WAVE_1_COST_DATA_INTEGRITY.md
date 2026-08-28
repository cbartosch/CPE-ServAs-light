# Wave 1 — Cost and canonical-data integrity

Wave 1 makes the Stage 5 financial projection fail closed rather than producing a
precise-looking number from incomplete or contradictory run data.

## Integrity sequence

Before a projection is built, the service now verifies:

1. every catalogued dataset file exists inside the immutable run directory;
2. every file SHA-256 matches the catalog;
3. every row count matches the catalog;
4. every scenario case joins to a subscriber, root incident, deterministic
   decision and action event;
5. work orders, MRs, validation and resolution records are case-local;
6. each MR cites an existing work order;
7. each resolution cites a passing, case-local validation;
8. every closed incident has a resolution record.

The API returns HTTP 409 with a structured `dispatch_projection_integrity_failed`
report when any check fails.

## Two cost bases

### Generated execution

Uses generated work-order data:

- dispatch-to-arrival duration;
- arrival-to-completion duration;
- one-way road distance;
- ferry-used flag;
- overnight-used flag.

The route planner remains visible as a comparison and hub-staging aid, but its
vehicle, ferry and overnight economics do not enter generated-execution cost.
Rates remain explicit demo assumptions.

### Governed forecast

Uses the deterministic recommended action, planning route, hub, ferry and
same-day feasibility assumptions. It remains a forecast and is not described as
incurred spend.

## Domain, validation and reconciliation

The projection now distinguishes:

```text
actual_domain       synthetic scenario truth or validated resolution domain
recommended_domain  deterministic recommendation
```

A misdispatch premium is calculated only when these differ.

`validated=true` requires:

```text
service_test == PASS
stable == true
all required closure checklist items == true
```

Reconciliation includes exact missing/orphaned work-order and MR identifiers,
duplicate work-order IDs and MR revision IDs. Counts remain for convenience but
are no longer the only control.

## Compatibility

New runs use schema:

```text
lpr-digital-twin-run-v3-execution-economics
```

This prevents a corrected configuration from reusing an immutable older run.
Older runs are rejected with a structured HTTP 409 response because they do not
contain the generated execution-economics contract. Regenerate the active demo
run before reviewing cost or dispatch results.
