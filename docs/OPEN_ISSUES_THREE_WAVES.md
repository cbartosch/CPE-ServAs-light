# Open-issue remediation in three gated waves

The three waves are intentionally sequential. A later wave is not released until
its predecessor has passed the Windows, Docker and semantic acceptance gates and
has been signed off.

## Wave 1 — Cost and canonical-data integrity

**Status in v1.27.2: implemented for review.**

Scope:

- verify catalog hashes and row counts before any cost output;
- fail closed when a case cannot join to its subscriber, root incident,
  deterministic decision or action event;
- require work orders, MRs, validation and resolution records to remain case-local;
- separate generated-execution economics from planning-route forecast economics;
- add generated work-order road distance, ferry and overnight facts;
- require PASS/stable/complete validation before resolution costing;
- separate actual synthetic/validated fault domain from recommendation;
- reconcile exact work-order and MR identifier sets;
- split executed and forecast truck rolls and publish metric denominators.

Exit gate:

```text
catalog hashes and row counts verified
mandatory case graph verified
no planning-route premium in generated execution cost
validation requires PASS + stable + complete checklist
exact work-order/MR identity reconciliation
Windows Ruff + focused tests + manifest + scenario matrix pass
```

## Wave 2 — Scale, economic grain and footprint calibration

**Not started.**

Planned scope:

- immutable run-keyed materialization/cache;
- summary, paginated case-list and single-case-detail endpoints;
- root-incident consolidated cost, case-attempt cost and repeat-work incremental cost;
- common-cause work-order/MR reuse policy and duplicate-economics controls;
- configurable footprint archetype weights, CSV/OSS/GIS import and visible provenance;
- Streamlit pages changed to consume summary/page/detail rather than the full response.

Exit gate:

```text
500,000-home summary response under 2 seconds after materialization
bounded response size and memory
root/case/repeat economics reconcile
configured footprint distribution is visible and reproducible
```

## Wave 3 — Install Assurance and deployment hardening

**Not started.**

Planned scope:

- correct GPON/HFC install-domain classification;
- deduplicate common-cause Install Assurance incidents and MRs;
- remove healthy-only cohort dilution and correct remote-stabilization denominator;
- route promoted install incidents through the governed workflow;
- enforce chronological Care/incident linkage and idempotent concurrent watch creation;
- exercise pending-baseline and invalidated lifecycle states;
- remove automatic `pip --trusted-host` fallback;
- repair clean-clone environment bootstrapping;
- add bounded database/DNS startup retry and dependency-aware readiness;
- tighten production network exposure and authentication configuration.

Exit gate:

```text
Install Assurance semantic invariants pass at multiple cohort sizes
concurrent watch creation is idempotent
strict TLS only
clean-clone Docker startup passes
API readiness proves PostgreSQL and MCP connectivity
production-like network/auth profile documented and tested
```
