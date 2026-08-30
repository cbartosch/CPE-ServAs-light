# Stage 3 DvSum CADDI naming repair audit

## Scope

This patch changes the project-facing integration name from the incomplete or
legacy project spellings to **DvSum CADDI** across the Stage 3
Executive, Predictive/Customer Care, Operations, Install Assurance, API, and
standalone Control Tower surfaces.

The correction is intentionally semantic-preserving:

- Stage 2 measurement formulas and values do not change.
- Stage 3 install-assurance episode generation and outcomes do not change.
- CADDI/CADI imports, routes, and query parameters remain deprecated compatibility
  aliases.
- No live DvSum CADDI or Genesys connection is claimed.

## Canonical surfaces

| Surface | Canonical value |
|---|---|
| Python module | `lpr_cpe_demo.caddi` |
| API route | `GET /api/integrations/caddi` |
| UI query | `digital-twin?view=caddi` |
| Display label | `DvSum CADDI` |
| Analytical source layer | `dvsum_caddi` |
| Install child dataset | `caddi_contexts.jsonl.gz` |

Compatibility aliases remain available through `lpr_cpe_demo.caddi`,
`lpr_cpe_demo.cadi`, `/api/integrations/caddi`, `/api/integrations/cadi`, and the
former query values.

## Defects repaired

The Stage 3 merge had also left conflicting DvSum integration imports in both API
modules. Those imports are now single-sourced through the canonical CADDI module.
The dashboard and telemetry contract use the same canonical implementation, while
stable internal block keys remain unchanged for Stage 1/2 compatibility.

## Verification

The following focused suite passed:

```text
214 tests passed
```

It covers DvSum CADDI contracts and aliases, both APIs, all relevant dashboards,
24-Hour Install Assurance, Stage 2 measurement semantics, standalone HTML,
telemetry, and lint-baseline policy.

Additional checks passed:

```text
Python compileall: source, scripts, tests
Standalone Control Tower HTML regeneration
Stage 2 canonical projection comparison
Stage 3 install-watch behavior comparison
```

The Stage 2 comparison produced identical canonical JSON hashes:

```text
acd93f09ae1b37df86c6dfd17973bc0b6aa8b6012760b42f9a2b43a6686504f0
```

The Stage 3 install-watch comparison, after normalizing only product-name fields,
produced identical behavior hashes:

```text
edf7f477508d2eccc52840db6cd95f0703b5cffc59fb261f63084cec9d7e1a13
```

The exact Ruff executable was unavailable in the isolated packaging runtime. The
new CADDI and Install Assurance files remain outside the legacy per-file baseline,
line lengths were checked, imports were reviewed, and the target-laptop release
gate remains:

```powershell
python -m ruff check src scripts tests
```
