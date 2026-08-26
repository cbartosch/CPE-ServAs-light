# Ruff baseline policy

## Purpose

Stage 1 makes CADI explicit without silently turning a long-standing repository-wide
style backlog into product scope. The Ruff gate still runs across `src`, `scripts`, and
`tests`, but existing findings are recorded as exact path-and-rule exemptions in
`pyproject.toml`.

The baseline is intentionally constrained:

- no wildcard path is permitted;
- `ALL` is not permitted;
- undefined-name findings (`F821`) are never baselined;
- new CADI files and future Stage 2/Stage 3 files receive the full rule set;
- a file may only suppress rule codes that were present in the captured baseline.

## Stage 1 fixes made outside the baseline

The candidate fixes the two correctness defects found by the first full Ruff run:

- `INITIAL_VIEW` is now imported by the optional Folium footprint renderer;
- `Any` is now imported by the UI widget static-analysis test.

It also removes the small set of findings in Stage 1 runtime files where a mechanical
change was low risk: CADI API typing, dashboard imports, telemetry imports, control-tower
`zip(..., strict=True)`, and dashboard-test imports.

## Removal policy

An exemption is removed when its file is touched for functional work or through a
dedicated hygiene change. New exemptions require an explicit review and must not use
wildcards or `ALL`. This keeps the Stage 1 gate honest while preventing unrelated legacy
formatting work from being confused with CADI functionality.

## Gate

```powershell
python -m ruff check src scripts tests
```

The command remains the repository gate. The baseline changes what is acknowledged as
pre-existing; it does not narrow the paths that Ruff scans.
