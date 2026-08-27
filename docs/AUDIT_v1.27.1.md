# Audit v1.27.1 — Delimiter-region topology P0 repair

## Scope

This patch addresses only Stage 5 finding `S5-P0-001`: mixed-region serving
TAP/ODP groups distorted mapped dispatch geography and modelled cost. The open
Stage 5 P1/P2 findings are deliberately unchanged.

## Repair

1. Subscriber geography is generated at serving-delimiter grain. Every group of
   up to eight services behind one `delimiter_id` inherits one planning region.
2. The complete subscriber-master stream enforces the one-delimiter-to-one-region
   invariant while it is written.
3. The canonical quality gate also reports any delimiter that spans multiple
   planning regions.
4. The dispatch/cost projector fails closed on a legacy mixed-region delimiter.
   It no longer selects a majority region or uses a tie-break.
5. Run identifiers include `RUN_SCHEMA_VERSION`. The same user configuration
   therefore creates a new corrected immutable run instead of returning an older
   topology generated under the previous algorithm.

## Compatibility behavior

Existing runs are not rewritten. A Stage 5 projection against an older mixed
run returns a conflict explaining that the run must be regenerated. Other
Digital Twin views remain able to read the old immutable artifact.

## Validation

A 100,000-home board-profile run was generated with the corrected topology:

- 100,000 subscriber rows.
- 12,500 serving delimiter groups.
- 0 mixed-region delimiter groups.
- 500 projected case attempts.
- 0 case-region versus mapped-archetype mismatches.
- 0 ferry routes assigned to a non-remote generated region.
- The catalog recorded
  `lpr-digital-twin-run-v2-delimiter-region` as its run schema.

Regression tests also construct a legacy mixed-region subscriber master and
verify that both the direct projection and API endpoint reject it.

## Remaining open findings

This focused P0 patch does not change:

- generated-execution versus modelled-route cost mixing;
- 500,000-home caching/pagination;
- common-cause/repeat cost duplication;
- `.env` and Docker TLS deployment findings;
- workload denominator semantics;
- actual versus recommended fault-domain separation;
- exact ID-set reconciliation;
- successful-validation semantics.
