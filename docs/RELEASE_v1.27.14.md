# Release v1.27.14 — executive workspace layout closure

This release is based on the complete v1.27.13 application release and corrects the active-run Predictive & Customer Care navigation panel shown in the browser UAT. Data semantics, safety controls and product contracts are unchanged.

## Browser-layout correction

- The navigation panel now uses two vertical zones: a full-width narrative summary and a fluid grid of destination buttons.
- The summary can no longer be reduced to a narrow column by the intrinsic width of seven non-wrapping navigation links.
- Button labels can wrap normally, and the action grid falls back to two columns and then one column at small widths.
- The Streamlit header and toolbar inherit the same dark surface and readable foreground as the workspace.
- The layout contract is protected by `tests/test_predictive_workspace_layout_regression.py`.

## Rendered acceptance evidence

The release layout was rendered in Chromium with the same CSS and markup used by the application. At a 1600×900 viewport, the summary width is 608 px, all seven actions fit on one row, and the panel height is 160 px. At a 1366×768 viewport, the summary remains 608 px and the actions wrap to two rows without compressing the narrative. The header resolves to `rgb(56, 60, 65)`.

## Preserved contracts

- Canonical product name: **DvSum CADDI**.
- Runtime contract: Python 3.14.7, pytest 9.0.2 and Ruff 0.13.3.
- Current Digital Twin schema: `lpr-digital-twin-run-v3-execution-economics`.
- Production writes remain disabled.
- Legacy runs remain immutable and incompatible runs fail closed.
- Manifest verification remains LF/CRLF independent for UTF-8 text and byte-exact for binary files.
