# Audit v1.27.0 — Demo-derived cost and dispatch

## Scope

This release links the Cost Simulator and Footprint & Dispatch pages to the
persisted active Digital Twin run. It does not convert planning assumptions into
operator actuals and it does not introduce production writes.

## Implemented data path

```text
Digital Twin RUN-* datasets
  -> complete dispatch/cost projection at case_id grain
  -> Cost Simulator and Footprint & Dispatch
```

The projection reads complete canonical run datasets rather than paginated UI
responses. It joins generated service, device, case, root incident, scenario,
technology, region, delimiter, deterministic decision, action, human decision,
work order, JTrack/MR, validation and resolution records.

Generated work-order readiness values are mapped explicitly into the existing
planning hub skill and stock vocabulary:

| Generated readiness | Planning dispatch requirement |
|---|---|
| `CPE_SWAP_CERTIFIED` | `cpe_swap` skill and `cpe` stock |
| `CLEAN_BOOTS_CERTIFIED` | `drop_replacement` skill and `drop` stock |
| `HFC_PLANT` | `hfc_plant` skill and `connectors` stock |
| `PON_PLANT` | `fibre_splice` skill and `splice_kit` stock |

## Provenance boundary

### Run-derived

- Identity, scenario, RCA and lifecycle state.
- Generated action status.
- Work-order type, skill, parts and timestamps.
- MR, validation and closure identity.

### Modelled

- Municipio and approximate coordinates, because the generated subscriber master
  has no surveyed latitude/longitude.
- Dispatch hub, road/ferry route and blast radius.
- Vehicle distance.

### Assumed

- Labour, vehicle, ferry, overnight and parts rates.
- Standard triage, RCA, review, validation and closure durations.

The UI labels the output as modelled cost using run-derived inputs. It separates
`generated_execution` from `governed_forecast` rather than presenting both as
actual spend.

## Validation performed

- Ten projection/API/UI regression tests pass.
- Focused Digital Twin, Executive, External Evidence, Install Assurance,
  measurement, workflow, MCP, security and telemetry suites pass.
- The governed nine-scenario matrix passes exact outcome contracts.
- A 20,000-home preview run projected 100 cases in under one second in the audit
  environment and reconciled all generated work-order and MR identifiers.
- The projection is deterministic and leaves every canonical run file unchanged.
- Python parsing and compilation pass for every changed module.
- `git diff --check` passes.

## Inherited release observations

The following pre-existing repository checks remain outside this feature scope:

1. The static reachability heuristic treats FastAPI-decorated route handlers as
   unreferenced public functions.
2. One UI test still expects a Python 3.12 base image while the repository and
   Dockerfiles target Python 3.14.2.
3. Asset tests expect a local `.env` file in a clean clone and reject the existing
   optional pip `--trusted-host` fallback.

These findings reproduce independently of the demo-derived cost/dispatch change.
The target Windows acceptance gate must still run the pinned Ruff executable and
the focused regression suite.
