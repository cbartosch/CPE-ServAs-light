# Release v1.27.15 — runtime connectivity and legacy-child compatibility closure

This release corrects the browser UAT failures observed after v1.27.14: a scenario launch timing out at the UI boundary, an executive projection misreported as a missing run, a stale UI image retaining the old navigation layout, and a white Streamlit header.

## Runtime routing and request budgets

- The UI container now receives `API_URL=http://api:8000` explicitly.
- Routine workflow requests use a 30-second budget. Full scenario execution uses a separate 240-second budget.
- The Scenario Launcher shows a progress spinner and names the request, timeout and diagnostic command when the budget is exceeded.

## Digital Twin compatibility

- Current-schema Install Assurance watches remain complete and fail closed.
- A direct request for an immutable legacy watch that lacks required files returns a structured HTTP 409 with the watch ID and missing files.
- The parent executive projection skips incomplete optional legacy children, so a valid active run is never mislabeled as `run not found`.
- Canonical run datasets and existing child artifacts are never rewritten.

## Stale-image prevention and layout

- Startup scripts use `--force-recreate` and run `scripts/runtime_smoke.py` inside the UI container.
- The smoke test verifies the loaded application version, workflow API route, scenario list, Digital Twin API route, active run and executive projection when present.
- The sidebar exposes the loaded application release.
- The Predictive & Customer Care cross-link uses fail-safe full-width block and grid rules with `!important` boundaries, and all Streamlit header layers use the dark workspace surface.

## Preserved contracts

- Canonical product name: **DvSum CADDI**.
- Runtime: Python 3.14.7, pytest 9.0.2 and Ruff 0.13.3.
- Current run schema: `lpr-digital-twin-run-v3-execution-economics`.
- Production writes remain disabled.
- Legacy runs remain immutable and incompatible decisions remain fail closed.
