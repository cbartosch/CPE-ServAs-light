# Demo-derived cost and dispatch projection

## Purpose

The Cost Simulator and Footprint & Dispatch pages now default to the same
persisted Digital Twin run used by Executive, Predictive Health and Customer
Care. They no longer create a second fault population when the user is reviewing
active-run evidence.

The legacy seeded simulator and manual site/skills check remain available as
explicit **Planning model** and **Manual planning inputs** modes.

## Source contract

The Digital Twin API builds one complete, non-paginated projection at:

```text
GET /api/dispatch-cost-projection
GET /api/active-run/dispatch-cost-projection
GET /api/runs/{run_id}/dispatch-cost-projection
GET /api/dispatch-cost-contract
```

The projection grain is one generated `case_id`. Each row links:

```text
run_id
case_id
root incident_id
service_id and device_id
scenario and lifecycle mode
technology
region and delimiter
RCA domain and recommended action
action status
human-decision state
work-order identity, type, skill, parts and timestamps
JTrack/MR identity
validation and resolution state
```

## Provenance boundary

The calculation deliberately separates three input classes.

### Run-derived

- Service, device, case and root-incident identity.
- Scenario, technology, region and delimiter identity.
- Deterministic domain and action.
- Action lifecycle state.
- Generated work-order skills, parts, timestamps, road distance, ferry use and overnight use.
- Generated JTrack/MR, validation and closure records.

### Modelled

The synthetic subscriber master has no surveyed latitude/longitude. The
projection therefore maps each generated delimiter deterministically to one
Puerto Rico planning site. Geography is generated at serving-delimiter grain:
every service behind one TAP or ODP inherits the same planning region, and the
same delimiter always maps to the same site.

Premise, delimiter and intervention coordinates, dispatch-hub selection, route
and blast radius remain modelled. A mixed-region delimiter is invalid topology;
the projection rejects that run and asks the operator to regenerate it rather
than selecting a majority region or applying a tie-break.

Run identifiers include the generation-schema version. Re-running the same user
configuration after this topology correction therefore creates a new immutable
run instead of silently reusing an older mixed-region artifact.

### Assumed

Labour, vehicle, ferry, overnight and parts prices remain the cost assumptions in
`lpr_cpe_demo.effort`. Standard triage, RCA, validation and closure durations are
also assumptions.

The UI therefore labels the result **modelled cost using run-derived inputs**. It
does not call the result an invoice, actual cost or surveyed dispatch route.

## Cost bases

```text
generated_execution
```

The demo action has status `SIMULATED_EXECUTED`. Generated work-order timestamps,
road distance, ferry use and overnight use drive the execution ledger. The
planning route remains visible as a comparison but does not contribute vehicle,
ferry or overnight charges to executed cost. Economic rates remain assumed.

```text
governed_forecast
```

The generated action is pending human review or remains a recommendation. The
projection prices the deterministic next action as a forecast and keeps it
separate from generated execution cost.

## UI behavior

### Cost Simulator

Default mode: **Active demo run**.

- Filters the complete generated case set by scenario, technology, action status,
  cost basis and field/plant involvement.
- Separates generated-execution cost from governed-forecast cost.
- Displays generated work-order and MR identities.
- Maps generated cases at their modelled intervention points.
- Shows a line-by-line ledger with duration and rate provenance.

### Footprint & Dispatch

Default mode: **Active demo run**.

- Selects a generated case, not an unrelated municipio.
- Uses the case's technology, delimiter, RCA domain, action, generated skills,
  parts, work order and MR as dispatch inputs. Generated readiness codes are
  mapped explicitly into the planning hub skill/stock vocabulary before staging.
- Shows generated work-order travel beside the modelled geographic route.
- Highlights the mapped intervention point and selected dispatch path.
- Retains manual planning mode for independent what-if checks.

## Safety and integrity

Before any economic output, the projector verifies the run schema, every catalog
SHA-256 and row count, and mandatory case/subscriber/incident/action/work-order/MR/
validation/resolution joins. A failure returns HTTP 409 with a structured
`dispatch_projection_integrity_failed` report and no cost result.

- The projection is read-only.
- It does not change the run catalog or any canonical dataset.
- It does not create work orders, MRs or production writes.
- It is computed from complete run datasets, not display-page row counts.
- Cross-page navigation links the active-run workspace, Footprint & Dispatch and
  Cost Simulator without changing the active run.
