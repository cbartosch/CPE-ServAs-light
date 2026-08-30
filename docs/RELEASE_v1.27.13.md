# Release v1.27.13 — DvSum CADDI, Python 3.14.7 and target-lint closure

This release is based on Wave 1 commit `2b46e9d351d6d5ba1de1573d4bfd0c6d27a94cf1` and applies the accumulated production-safety and portability corrections directly to the application tree.

## Canonical product and integration surfaces

- Product display name: **DvSum CADDI**.
- Canonical Python module: `lpr_cpe_demo.caddi`.
- Canonical API route: `/api/integrations/caddi`.
- Canonical Digital Twin view: `view=caddi`.
- Canonical analytical source: `dvsum_caddi` / `dvsum_caddi_insights`.
- Canonical install-assurance artifact: `caddi_contexts.jsonl.gz`.
- `lpr_cpe_demo.cadi` and `/api/integrations/cadi` remain deprecated machine-compatibility interfaces; they return the same DvSum CADDI contract and are not separate product names.

The current tree, tracked filenames and editable Office XML are guarded against the superseded two-L spelling.

## Runtime and supply-chain controls

- Host and container contract: Python 3.14.7.
- Dependency installation is either from vendored wheels or a TLS-verified package index.
- The former package-index host-trust bypass and its configuration switch are removed.
- Corporate CA staging and approved internal mirrors remain supported.

## Digital Twin compatibility and recovery

Current runs identify `lpr-digital-twin-run-v3-execution-economics` in `run_schema_version`. Legacy schema-less or incompatible runs remain immutable and fail closed at the live-decision/dispatch boundary. Use `scripts/Repair-LPR-CurrentSchemaRun.ps1` or `scripts/repair-current-schema-run.sh` to create and activate a new current-schema run while verifying that the prior catalog is unchanged.

Quality-gate conflicts return structured HTTP 409 detail with the run ID, issue list, expected schema and recovery action.

## UI and audit controls

- The legacy Control Tower cross-link uses a responsive flex layout and cannot collapse its narrative column to one character per line.
- The Streamlit header and toolbar use the same readable dark surface as the page.
- Manifest verification normalizes LF/CRLF for UTF-8 text but remains byte-exact for binary files.
- FastAPI/Starlette route decorators count as application reachability; genuinely unused public models are removed.


## Target lint closure

The release closes every Ruff 0.13.3 diagnostic reported by the Windows verification gate for v1.27.12. The target verifier runs `python -m ruff check src scripts tests` before any push.
