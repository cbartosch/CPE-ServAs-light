# Changelog

## 1.3.0 - make the model and retrieval contribution measurable

### Added
- `src/lpr_cpe_demo/retrieval.py`: BM25 retrieval over a prior-case knowledge
  base, standard library only. `vote_domain` derives a domain and a confidence
  from a score-weighted vote of retrieved neighbours.
- `src/lpr_cpe_demo/kb/prior_cases.json`: 24 resolved prior cases and 6
  responsibility-boundary procedures.
- `src/lpr_cpe_demo/kb/benchmark.json`: 18 RCA cases with ground truth. Four are
  cases where the deterministic classifier is wrong.
- `src/lpr_cpe_demo/ab_metrics.py`: gate precision, dissent precision and recall,
  avoided and missed misdispatch, interruption cost, citation validity.
- `scripts/run_ab_matrix.py`: three-arm comparison across deterministic,
  deterministic plus scripted model, and deterministic plus retrieval.
- `true_domain` and `true_domain_basis` on the workflow fixtures, derived from
  each scenario's own expected outcome. Left null for `bounded_remote_failure`,
  which escalates without resolving.
- `docs/AB_MEASUREMENT.md`.
- `tests/test_retrieval_ab.py`: 32 tests, including three that guard against a
  benchmark rigged to flatter retrieval.

### Changed
- `controls.fuse_and_gate` now holds the RCA fusion and gating rule.
  `WorkflowEngine._fusion` delegates to it, so the engine and the harness
  evaluate one implementation rather than two. Behaviour is unchanged: the
  approved domain is always deterministic, fused confidence is the minimum, and
  either low confidence or domain disagreement raises a human review.

### Findings
- **The shipped default contributes nothing measurable.** With
  `MODEL_PROVIDER=fake` the model echoes the deterministic domain, so the
  disagreement gate never fires. The scripted arm is identical to the
  deterministic arm on every operational metric: zero gates, four missed
  misdispatches out of eighteen cases.
- **Retrieval catches all four rules errors, at a cost.** Recall 1.0 and four
  avoided misdispatches, against three false alarms. Gate precision is 0.571, so
  about two in five interruptions were justified.
- Retrieval confuses `cpe` with `provisioning` on two cases; those domains are
  lexically close in the corpus.

### Notes
- The harness measures the fusion and gating decision only, not the full
  workflow. It has been executed; the numbers above are real output.
- Still not executed anywhere: the Docker build and the runtime services.

## 1.2.1 - build resilience on intercepted and restricted networks

### Fixed
- `docker/app.Dockerfile` and `docker/mcp.Dockerfile` now install dependencies in
  four tiers: vendored wheels, then `PIP_INDEX_URL`, then verified PyPI, then
  trusted-host. Previously a network that re-signs HTTPS failed the build with
  `CERTIFICATE_VERIFY_FAILED` and no recovery path existed.
- Removed `pip install --no-deps -e .` from the app image. It triggered build
  isolation, which fetched `setuptools>=75` from the index before any dependency
  was resolved, and was redundant because `PYTHONPATH=/app/src` is already set
  and no console scripts are declared.
- Removed `pip install --upgrade pip`, an extra unguarded network call.

### Added
- `scripts/capture-ca.ps1` and `scripts/capture-ca.sh` capture the CA chain the
  network presents and stage it into `docker/certs/`. `stage-ca.*` and
  `install-host-ca.*` both require a `.crt` the operator must already have
  exported by hand; these do not.
- `scripts/vendor-wheels.ps1` and `scripts/vendor-wheels.sh` populate `vendor/`
  with linux wheels matching the Docker architecture.
- `vendor/` directory, empty by default.
- `PIP_STRICT_TLS` build argument. Set to `1` to refuse the trusted-host tier and
  fail the build instead.

### Notes
- Tier 4 stops verifying the chain for PyPI only. The proxy performing the
  interception already inspects that traffic, so it changes who validates the
  chain rather than who can read it. Prefer `capture-ca.*` or `PIP_INDEX_URL`.
- Not executed: no Docker Engine was available in the environment where this
  change was authored. The tier-selection shell logic was tested against a stub
  pip across five branches; the image build itself was not run.

## 1.2.0 — comparison and laptop-hardening revision

### Added

- Corporate proxy and CA staging for Bash and PowerShell without disabling TLS verification.
- Purpose-specific application and MCP Docker images.
- Exact split requirement sets and target-laptop installed-version checks.
- Strict MCP compatibility profile with fail-fast profile/version/statelessness validation.
- MCP service runtime-version reporting and exact image-pin verification.
- Restart-stable action and approval identifiers derived from durable case state.
- Replay-safe evidence, action, timeline, work-order and MR histories.
- Parent/child SLA authority while preserving the child clock.
- Safe next-best-action override that returns through policy for a fresh approval.
- Configurable Streamlit fragment refresh.
- PostgreSQL workflow-service recreation and same-thread resume test.
- `hfc_failed_plant_action_rerca` scenario demonstrating re-RCA and same-MR update after a failed plant action.
- Expanded comparison, test, runbook and workflow documentation.

### Preserved

- Six-page Streamlit operations console.
- FastAPI query and command API.
- Portable workflow plus LangGraph wrapper.
- Network HTTP MCP path for live execution.
- Fake, OpenAI and Anthropic assistant adapters.
- Signed human approvals and persistent effect idempotency.
- Clean Boots, Dirty Boots, HFC tap, PON ODP, jTrack MR and reverse-handover behavior.

### Verification performed during packaging

- 35 automated tests passed.
- 84.63% measured source coverage.
- Nine-scenario matrix passed.
- Compose structural validation passed.
- Python and Bash syntax validation passed.
- Separate-process FastAPI-to-HTTP-MCP workflow passed using the portable engine.

Docker, pinned LangGraph/Streamlit runtime and PostgreSQL checkpoint recreation must be verified on the target laptop with `scripts/verify_docker.sh` or `scripts/verify_docker.ps1`.
