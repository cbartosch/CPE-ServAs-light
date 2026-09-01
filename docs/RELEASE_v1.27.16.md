# Release v1.27.16 — target Ruff closure

This release closes the two target-side Ruff 0.13.3 findings discovered during the v1.27.15 Windows verification gate.

## Corrections

- Remove the unused `sys` import from `scripts/repair_current_schema_run.py`.
- Keep only the type annotation import at module scope in `src/lpr_cpe_demo/ui/client.py`, and load `os` and `httpx` at their call sites. This removes the ambiguous mixed module-level import block without adding a lint suppression and preserves runtime behavior.
- Add regression guards that parse the affected modules and verify the exact import contracts.

## Preserved contracts

- Canonical product name: **DvSum CADDI**.
- Runtime target: Python 3.14.7.
- Test and lint gates: pytest 9.0.2 and Ruff 0.13.3.
- Current Digital Twin run schema: `lpr-digital-twin-run-v3-execution-economics`.
- Production writes remain disabled.
- Legacy runs and child artifacts remain immutable.
- The v1.27.15 workflow API routing, scenario execution timeout, runtime smoke test, legacy-child compatibility, responsive workspace navigation, and dark Streamlit header remain intact.
