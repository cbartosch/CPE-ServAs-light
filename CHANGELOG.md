# Changelog

## 1.10.0 - OpenStreetMap actually renders, hubs read as depots, routes split into legs

### Fixed
- **The map never rendered.** Both pages called `pdk.Deck.from_json`, which the
  installed pydeck does not provide, so every load failed with
  `type object 'Deck' has no attribute 'from_json'` and dropped to the offline
  schematic. Layers are now built with `pdk.Layer(...)` in a new
  `ui/deck.py`, which is the supported API. Each layer is constructed
  defensively: if one raises it is skipped and the rest still draw.
- **Dollar signs were being eaten.** Streamlit renders markdown, and markdown
  reads `$...$` as inline LaTeX, so "Headline range \$150 to \$300" rendered as
  "Headline range 150 to 300" with the currency symbols gone and the numbers in a
  maths font. New `ui/fmt.py` provides `usd()` for markdown contexts and
  `usd_plain()` for `st.metric`, which does not render markdown.

### Changed
- **Hubs read as depots rather than blotches.** Three layers instead of one: a
  white-filled ring with a dark edge, a filled core on very-high-likelihood hubs
  only, and a `TextLayer` carrying the hub code above the marker.
- **Dispatch routes are split by mode.** Road legs draw as `PathLayer` lines,
  ferry legs as `ArcLayer` arcs over water, so the crossing is visually distinct
  from the drive to the terminal.

### Honest limit on "actual" routes
Route legs are straight lines between hub, ferry terminal and intervention point.
They are **not road geometry** — road-accurate routing needs a routing service
this deployment does not call. `ROUTE_CAVEAT` states this on both pages. The
travel *minutes* are not straight-line, though: they come from the archetype
road-speed model with a detour factor, so the number is a better estimate than the
drawn line implies.

### Added
- `tests/test_ui_widgets.py` grew to 23 tests, including a stub-pydeck harness
  that exercises the real construction path: layer types, accessor names, draw
  order, and that `map_provider` and `map_style` are None so deck.gl adds no
  second basemap over OSM. One test asserts every `get_*` accessor names a field
  that actually exists in its data, because a misnamed accessor renders nothing
  and raises no error. Another asserts a failing layer is skipped rather than
  killing the map.
- Guards for both fixed bugs, verified by reintroducing each and confirming the
  matching test fails with the file and line named.

## 1.9.1 - fix the seed input bound, and guard the whole widget class

### Fixed
- `ui/pages/simulator.py` raised `StreamlitValueAboveMaxError` on render: the
  seed input was declared `max_value=10_000_000` with a default of `20260817`.
  A date-shaped seed is the natural thing to type, so the bound is now
  `2_147_483_647`, the signed 32-bit maximum, which `random.Random` accepts.

### Added
- `tests/test_ui_widgets.py`: 9 tests that parse every page and validate bounded
  widgets statically. Asserts min is not above max, the default sits inside the
  range, the step fits, and specifically that a seed input accepts a date-shaped
  value. Verified by reintroducing the bug and watching two tests fail with the
  offending file, line and values named.
- The same file also asserts every page module exposes `render()` and is
  registered in `app.py`.

### Note
This was the first render of the Streamlit runtime in this project. `compileall`
and import checks cannot catch an out-of-range widget default, because the
constraint is only evaluated when the widget renders. AST inspection catches it in
about a second with no Streamlit installed, which is why the guard is static
rather than a runtime smoke test.

## 1.9.0 - anchor truck roll cost on a third-party benchmark

### Added
- `src/lpr_cpe_demo/benchmarks.py`: the AEX published bands for fully loaded
  truck roll cost, with the source URL, retrieval date, and the inclusion and
  exclusion lists the source states. Low $125-175, mid $175-250, high $250-350,
  each with the operational profile behind it. Rural uplift 15-25%, midpoint
  taken. `band_for_profile` infers a band from an operator's own first-visit
  completion rate.
- `tests/test_benchmarks.py`: 22 tests.
- Benchmark figures on every generated fault, and a benchmark cross-check panel
  on the Fault Simulator page with the citation.

### Why
`effort.RATES` built cost from assumed labour rates, producing figures nobody
could check. The bands are published and attributable, so a number can now be
defended or disputed on its source rather than on my arithmetic.

### What the reconciliation showed
The bottom-up model was wrong in both directions:

| site | domain | bottom-up | benchmark | ratio |
|---|---|---|---|---|
| Bayamon | hfc_tap | $125 | $212 | 0.6x |
| Arecibo | hfc_tap | $354 | $212 | 1.7x |
| Utuado | hfc_tap | $330 | $255 | 1.3x |
| Vieques | pon_odp | $970 | $655 | 1.5x |
| Culebra | pon_odp | $1,071 | $655 | 1.6x |

Too high on coastal, mountain and island work; too low in metro, where a hub is
co-located and the bottom-up model bills almost no travel. The household-weighted
blend now lands at about $219 per wasted dispatch, inside the published $150-300
range.

### Two limits kept explicit
- The bands are for **fiber operators** and the source frames first-visit
  completion around installs. LPR CPE fault work is repair, so the bands are an
  analogue rather than like-for-like.
- The benchmark does not contemplate a ferry crossing or an overnight stay.
  `island_adder_usd` holds that separately and `within_benchmark_scope` is False
  for island work, so the cited range is never silently inflated. A test asserts
  it.

### Avoided wasted truck rolls, per 1,000 incidents
Using the archetype model's own truck-roll and no-fault-found rates
(45 wasted rolls per 1,000) and the benchmark blend of $219:

| attributable to misclassification | recall 100% | 75% | 50% |
|---|---|---|---|
| 25% | 11 rolls, $2,480 | 9, $1,860 | 6, $1,240 |
| 40% | 18 rolls, $3,968 | 14, $2,976 | 9, $1,984 |
| 50% | 23 rolls, $4,960 | 17, $3,720 | 11, $2,480 |
| 60% | 27 rolls, $5,953 | 20, $4,464 | 14, $2,976 |

Both parameters are unknown. The 100% recall column comes from a harness scoring
1.0 on 18 cases I wrote myself and should not be planned against.

## 1.8.0 - fault simulator: cost and location of intervention in the GUI

### Added
- `src/lpr_cpe_demo/fault_generator.py`: seeded synthetic fault generation with
  jittered coordinates for the household, the delimiter and the intervention
  point, plus a full effort ledger and misdispatch exposure per fault.
- `src/lpr_cpe_demo/ui/pages/simulator.py`: new **Fault Simulator & Cost** page.
  Cost metrics, a map with pins at the intervention point, a cost-ranked table and
  a per-fault effort ledger. Controls for fault count, seed, dispatch routes and a
  plant-interventions-only filter.
- Fault layers in `geo_layers.py`: pins coloured and sized by cost, grey links
  from a household to its tap or ODP when the work happens elsewhere, and dispatch
  routes from the hub through the ferry terminal where applicable.
- `tests/test_fault_generator.py`: 31 tests.

### Two modelling points this makes visible
- **The intervention location is not the customer address.** A CPE or in-home
  fault is worked at the premise; a tap or ODP fault is worked at the tap or ODP,
  which is a different place, a different crew, and several households. The grey
  link on the map is that distinction drawn.
- **Fault density follows households, not municipios.** Sampling sites uniformly
  would give Culebra as many faults as San Juan. Weighting by modelled household
  count puts about 89 of 400 faults in San Juan and 1 in Culebra, so the metro
  dominates volume while the islands dominate unit cost.

### Reproducibility
- Everything derives from an explicit seed, verified to survive a process restart,
  so a figure quoted in a demo can be reproduced afterwards.
- Coordinate jitter is hashed from the element identifier rather than drawn from
  the RNG, so a given tap sits in the same place across every seed and sample
  size. A test asserts this across five seeds and 300 faults.

### Notes
- All costs remain assumed. The page opens with a warning and exposes
  `effort.assumptions()` in an expander.
- The page falls back to the offline SVG schematic if pydeck is unavailable,
  without fault pins.

## 1.7.0 - plant topology, dispatch effort, and the cost of gate errors

Answers "show the time and effort expended if remote fix does not work, and the
cost of false positives and negatives" by putting technician minutes and money on
each outcome. Every rate, duration and plant ratio is ASSUMED and stated as such.

### Added
- `src/lpr_cpe_demo/plant.py`: households, drops, taps, ODPs, HFC nodes and PON
  ports, with deterministic synthetic identifiers so `TAP-ARE-0530` is stable
  across runs and can be referenced by a scenario, a work order and an MR.
  `blast_radius` returns the households affected per responsibility domain, which
  is what separates a drop fault (1 household) from a tap fault (4 to 8) from a
  node event (450).
- `src/lpr_cpe_demo/effort.py`: an `EffortLedger` that walks an incident to
  closure and bills each step, plus `false_positive_cost` and
  `false_negative_cost`.
- `scripts/run_dispatch_simulation.py`: per-scenario table of resolved cost, the
  cost of two failed remote attempts, and the cost of a misdispatch.
- `tests/test_plant_effort.py`: 30 tests.
- `plant` block and a stable `incident_id` on all nine located scenarios.

### Changed
- `scripts/run_ab_matrix.py` now reports a cost table per arm, so the A/B result
  is expressed in hours and dollars rather than only in precision and recall.
- `ab_metrics.CaseResult` carries `site_id`, so the cost model can price the
  wasted visit at the right location.

### What the numbers say
Across the 18 benchmark cases:

| arm | FP | FN | wasted minutes | wasted USD |
|---|---|---|---|---|
| `deterministic` | 0 | 4 | 1,266 | 1,734.63 |
| `plus_scripted_model` | 0 | 4 | 1,266 | 1,734.63 |
| `plus_retrieval` | 3 | 0 | 60 | 59.01 |

Retrieval converts about 21 hours of wasted field time into 1 hour of review
time. The asymmetry is the reason: a false positive costs 20 minutes and about
$20, while a missed gate costs 306 minutes and $354 at Arecibo and 676 minutes
and $1,071 at Culebra, which is 18x and 54x respectively. An arm can be wrong
about a gate often and still pay for itself.

Across the nine located scenarios: two failed remote attempts add $776, about 10%.
A missed gate on every one would add $4,712, about 62%.

### Notes
- Only the *avoidable* portion of a false negative is counted: the wasted visit
  plus the handover. The correct visit still has to happen either way, so
  including it would overstate the saving.
- A wrong domain that keeps the same crew type is not billed as a false negative.
  Confusing `cpe` with `wifi_or_home` is both clean boots, so no visit is wasted.
- 143 tests collected; the 6 that fail to load need pytest, fastapi or pydantic
  and are the pre-existing v1.2 suite. The stdlib subset is
  `test_plant_effort`, `test_geography`, `test_geo_layers`, `test_retrieval_ab`
  and `test_bundle_integrity`.

## 1.6.1 - integrity verification and version consistency

### Added
- `scripts/verify_manifest.py`: compares the working tree against
  `MANIFEST.sha256` and names every mismatched or missing file. Standard library
  only, so it runs on Windows without an install. Run it before rebuilding an
  image when an import error looks inexplicable.
- `tests/test_bundle_integrity.py`: 9 tests that catch a mangled tree before it
  becomes a confusing traceback.
  - The top-level `__init__.py` must contain no imports. A relative import there
    is the signature of a subpackage `__init__` having been copied over the
    parent, which surfaces as `ModuleNotFoundError: No module named
    'lpr_cpe_demo.client'` raised from `lpr_cpe_demo/__init__.py`.
  - Every relative import in every `__init__.py` must resolve to a file or
    package that actually sits beside it.
  - Two tests prove the verifier works by tampering with a file and deleting
    another, then restoring both.

### Fixed
- `src/lpr_cpe_demo/mcp_server/__init__.py` was missing, so that subpackage was an
  implicit namespace package while every sibling declared itself. Five modules
  import from it. Namespace packages are searched across every `sys.path` entry
  rather than bound to one directory, which makes import behaviour depend on path
  ordering. Present in the original v1.2 bundle; found by the new
  `test_every_package_directory_has_an_init`.
- `lpr_cpe_demo.__version__` said `1.2.0` while `pyproject.toml` said `1.6.0`. It
  now tracks the project version, and a test asserts the two agree along with the
  newest CHANGELOG heading, so the drift cannot recur silently.

### Note on the reported import error
- `src/lpr_cpe_demo/__init__.py` hashes to `773d3e52…` identically in the original
  v1.2 upload, this repository, and every bundle shipped from it. The file has
  never contained the `mcp_client` import, so a container reporting that line is
  building from a locally modified tree. `verify_manifest.py` identifies which
  files differ.

## 1.6.0 - OpenStreetMap basemap in Streamlit

### Added
- `src/lpr_cpe_demo/geo_layers.py`: deck.gl layer specifications over an
  OpenStreetMap raster basemap. Sites coloured by archetype, dispatch hubs sized
  by likelihood, core site and ferry terminal as outlined markers, ferry arcs, and
  the selected dispatch route as a path that passes through the terminal when the
  site is islanded.
- `tests/test_geo_layers.py`: 28 tests covering layer structure, draw order, JSON
  serialisability, and coordinate bounds.
- Optional `[map]` extra and `requirements-map.txt` for folium rendering.

### Changed
- `ui/pages/footprint.py` renders in three tiers and degrades rather than
  breaking:
  1. **pydeck with an OSM TileLayer.** pydeck already ships as a Streamlit
     dependency, so the default map installs nothing new. This matters on a
     network where adding packages is the hard part.
  2. **folium via streamlit-folium**, if the optional `[map]` extra is installed.
  3. **The generated SVG schematic**, which needs no network at all.
  The active renderer is selectable, and the page falls through automatically if
  pydeck raises.

### Notes on the basemap
- Tiles are fetched by the **browser**, not the container, so a restricted
  container network does not prevent this from working. A browser that cannot
  reach `tile.openstreetmap.org` shows markers over an empty basemap, which is
  why the SVG fallback is retained rather than removed.
- Attribution is rendered on the page. The public OSM tile service has a usage
  policy that discourages heavy or commercial use; `TILE_URL` is a parameter so an
  internal or commercial tile service can be substituted.
- A real basemap makes wrong coordinates visible, so the tests now bound every
  site and hub to the footprint, assert hub coordinates match their site, and
  check relative geography: islands east of Fajardo, west-coast sites west of San
  Juan, south-coast sites south of the metro. One test specifically guards
  `[lon, lat]` ordering, because deck.gl expects that order and reversing it
  places Puerto Rico off the Horn of Africa without any error.

### Not executed
- No Streamlit or pydeck in the authoring environment, so the layer specs are
  validated structurally and by serialisation but **have not been rendered**.
  Expect to adjust the pydeck `Layer` construction on first run: that API varies
  across versions, which is why a raw-JSON fallback path exists.

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
