# Changelog

## 1.5.0 - dispatch hubs revised from a practitioner assessment

### Changed
- The hub set now follows a practitioner assessment rather than a flat guess, and
  each hub records a `likelihood` and a `rationale`:

  | Likelihood | Hub | Rationale |
  |---|---|---|
  | Very high | Bayamon | Central access to San Juan metro west, dense HFC footprint, assessed as a major operations centre |
  | Very high | Caguas | Covers central and eastern Puerto Rico; common utility and telecom operations base |
  | Very high | Ponce | South region hub |
  | Very high | Mayaguez | Western Puerto Rico hub |
  | High | Aguadilla / Aguada corridor | West to north-west coverage with significant presence |
  | High | Carolina | East metro and airport corridor coverage |

- **San Juan is now a core site, not a dispatch hub.** The externally supported
  reference is to a core platform site, which is a headend and NOC function.
  Metro-west field dispatch is attributed to Bayamon.
- **Fajardo is now a ferry terminal, not a hub.** Island work is staged from a
  mainland hub, driven to the terminal, then ferried.
- Removed the previously assumed Arecibo and Humacao bases, which the assessment
  does not support. North-coast and east-coast work now routes to Bayamon,
  Caguas or the Aguadilla corridor.
- `basis` on every hub states that the location is judgement, not a published
  facility address. A test asserts it.

### Effect on the scenarios
- **Both islands are now outside a single shift.** Vieques moves from 155 minutes
  and marginally feasible to 214 minutes and infeasible; Culebra from 210 to 269.
  Modelling Fajardo as a terminal rather than a base is what changed this, and it
  is the more defensible reading.
- Utuado moves from Arecibo at 58 minutes to Ponce at 75.
- Arecibo itself is now served from the Aguadilla corridor at 84 minutes.
- The parts-over-proximity demonstration moved to the north-west: a fibre splice
  at Aguadilla routes to Mayaguez, because no splice kit is assumed at corridor
  level.

### Notes
- 38 geography tests pass, up from 33. The A/B matrix is unchanged, since
  location does not enter the RCA gate.
- Still assumed and still flagged: precise facility addresses, crew rosters, van
  stock, road speeds and ferry timetables.

## 1.4.0 - location-specific use cases and the service footprint

### Added
- `src/lpr_cpe_demo/geography.py`: 23 in-footprint sites across the four planning
  archetypes, 7 dispatch bases, haversine distance, an archetype-aware road
  travel model, and ferry legs from Fajardo to Vieques and Culebra.
  `select_base` filters on crew type, skills and van stock before ordering by
  travel time, so a nearer base without a splice kit is not a candidate.
- `scripts/generate_footprint_map.py` and
  `src/lpr_cpe_demo/ui/assets/footprint_map.svg`: schematic map generated from
  the same data the dispatch model uses, so the two cannot drift apart.
- `src/lpr_cpe_demo/ui/pages/footprint.py`: map, base table, and a per-site
  travel calculator showing staging base, legs, ferry dependency and whether the
  work fits one shift.
- `tests/test_geography.py`: 33 tests, including one that fails if the map was
  not regenerated after the site or base data changed.
- `site_id`, `municipio`, `region` and a computed `dirty_boots_base` on all nine
  workflow scenarios; `site_id`, `municipio` and `archetype` on all 18 benchmark
  cases.

### Scope, verified
- The fixed HFC and PON footprint is Puerto Rico: 78 municipios, including the
  island municipios of Vieques and Culebra. U.S. Virgin Islands sites are
  modelled but flagged `in_cpe_footprint=False`, because LPR serves USVI for
  mobile while USVI fixed broadband sits with a separate entity following the
  Broadband VI acquisition.

### Assumed, and labelled as such
- **Every dispatch base is an assumption.** Liberty does not publish
  operations-centre locations. Each base carries `assumed=True`, the map says
  ASSUMED in its subtitle, the Streamlit page opens with a warning, and a test
  asserts the flag. The only externally supported anchor is a core platform site
  in San Juan. Replace `DISPATCH_BASES` with real facility data, crew rosters and
  van stock before any operational use.
- Municipio coordinates are approximate centroids and the coastline is a
  simplified polygon. Adequate for orientation and relative travel time, not for
  survey use.

### Effect on the scenarios
- Vieques is staged from Fajardo at 155 minutes one way and is marginally
  same-day feasible. Culebra at 210 minutes is **not**, so `pon_reverse_handover`
  now carries an explicit overnight or pre-positioned-crew constraint.
- Maricao needs a base 109 minutes away when a splice kit is required, against
  43 minutes when it is not, which is the parts constraint visibly outranking
  proximity.

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
