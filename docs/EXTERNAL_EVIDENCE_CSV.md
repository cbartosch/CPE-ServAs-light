# External CSV Evidence, Triangulation, and Scenario Replay

## Purpose

The External Evidence capability imports CSV extracts from NXT, DvSum DALLI,
Genesys, JTrack, and an installation/identity source. It creates an immutable,
read-only evidence batch that can be replayed as a historical, point-in-time,
shadow, or 24-hour install-assurance scenario.

It does **not** write to any source system. Recommendations are advisory and must
pass deterministic policy and human review before an operational implementation
could act on them.

## Data path

```text
CSV files
  -> immutable raw files and SHA-256 lineage
  -> schema, identity, time and lifecycle validation
  -> accepted rows + quarantined rows + visible issues
  -> deterministic cross-source correlation
  -> deterministic RCA/action recommendation
  -> optional LLM triangulation agent
  -> recommendation reconciliation and human-review decision
  -> optional child scenario overlay (canonical run unchanged)
```

## Supported source types

| Source key | Expected grain |
|---|---|
| `identity_map` | Service/device relationship per validity period |
| `nxt_telemetry` | One metric observation |
| `nxt_alarms` | One alarm lifecycle event |
| `dvsum_dalli_insights` | One analytical insight/recommendation |
| `genesys_interactions` | One customer interaction |
| `jtrack_events` | One MR/work lifecycle event |
| `install_cohort` | One commissioning event |

The importer accepts `cadi`, `caddi`, `dali`, `dalli`, and `dvsum` as source-key
aliases, but normalizes them to `dvsum_dalli_insights`. This is compatibility for
file naming only; the displayed product name is **DvSum DALLI**.

## Identity and authority

`identity_map.csv` is required for deterministic cross-source correlation. Exact
service, device, MAC, serial, tap/ODP, and validity-period relationships take
precedence over text or model confidence.

Authority remains with the originating systems:

- NXT owns its telemetry and alarm facts.
- Genesys owns the interaction record.
- JTrack owns MR and repair lifecycle state.
- DvSum DALLI supplies analytical context, not source-system truth.
- LPR deterministic controls own the allowed recommendation and policy outcome.
- The LLM is advisory and cannot authorize or execute an action.

## LLM triangulation agent

The analysis endpoint supports `fake`, `disabled`, `openai`, and `anthropic`.
The offline `fake` provider exercises the same structured result and
reconciliation path without making a network call.

For `openai` or `anthropic`, the service requires both a model name and the
corresponding environment key. Missing credentials, a provider error, or an
invalid structured response fails closed to the offline deterministic result.
The report states whether an external provider call was actually attempted.

Before sending evidence to a provider, the service:

1. Runs deterministic validation first.
2. Excludes customer names, agent IDs, transcript text, billing fields, addresses,
   telephone numbers, and authentication/payment data.
3. Uses an allowlist of operational fields and caps record text.
4. Tells the model that CSV values are untrusted evidence and may contain prompt
   injection.
5. Requires structured output.
6. Rejects unsupported domains/actions and unknown evidence references.
7. Reconciles the result against the deterministic branch.

The agent flags:

- identity and technology disagreement;
- tap/ODP mismatch;
- impossible chronology;
- stale or future evidence;
- missing DvSum evidence references;
- JTrack lifecycle regressions;
- analytical-domain disagreement;
- missing evidence needed for a safe recommendation.

## API

```text
GET  /api/external-evidence/contract
GET  /api/external-evidence/templates/{source_type}
POST /api/import-batches
GET  /api/import-batches
GET  /api/import-batches/{batch_id}
POST /api/import-batches/{batch_id}/files/{source_type}
POST /api/import-batches/{batch_id}/validate
POST /api/import-batches/{batch_id}/analyze
GET  /api/import-batches/{batch_id}/quality
GET  /api/import-batches/{batch_id}/dispositions
GET  /api/import-batches/{batch_id}/correlations
GET  /api/import-batches/{batch_id}/timeline
GET  /api/import-batches/{batch_id}/recommendations
GET  /api/import-batches/{batch_id}/projection
POST /api/import-batches/{batch_id}/materialize
GET  /api/runs/{run_id}/external-evidence
```

CSV content is sent as UTF-8 text in JSON. This keeps the demonstration bundle
independent of multipart upload services. The default per-file limits are 15 MiB
and 200,000 rows.

## Point-in-time replay

When `as_of` is specified, evidence after that instant remains in the immutable
batch but is excluded from the timeline and agent packet. This prevents repair
outcomes or later contacts from leaking into an earlier recommendation.

## Scenario materialization

Materialization writes a child reference under:

```text
RUN-.../external_evidence/IMPORT-.../scenario.json
```

It does not update `catalog.json`, canonical JSONL datasets, incident state, or
source systems. The scenario record explicitly carries:

```text
canonical_run_unchanged = true
production_writes = false
action_execution = false
```

## Security and data handling

- Use pseudonymous customer and service identifiers.
- Do not upload full Genesys transcripts, payment data, credentials, secrets, or
  authentication answers.
- Raw files are retained with SHA-256 lineage.
- Invalid records are quarantined with source file and row number.
- Spreadsheet formula prefixes are flagged.
- Paths and import IDs are validated against traversal.
- A replacement upload creates another immutable raw-file revision rather than
  deleting the previous bytes.

## Command-line import

A local batch can also be created without Streamlit:

```powershell
python scripts/import_external_evidence.py `
  --data-root .\data\digital-twin `
  --mode install_watch `
  --identity reference\external_evidence_examples\identity_map.csv `
  --nxt-telemetry reference\external_evidence_examples\nxt_telemetry.csv `
  --nxt-alarms reference\external_evidence_examples\nxt_alarms.csv `
  --dvsum-dalli reference\external_evidence_examples\dvsum_dalli_insights.csv `
  --genesys reference\external_evidence_examples\genesys_interactions.csv `
  --jtrack reference\external_evidence_examples\jtrack_events.csv `
  --install-cohort reference\external_evidence_examples\install_cohort.csv `
  --provider fake
```

Use `--provider openai --model <model>` or `--provider anthropic --model <model>`
only when the corresponding API key is available in the environment.
