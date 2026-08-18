# Changelog

## 1.16.1 - audit: the agent layer was never reachable

Report: `docs/AUDIT_v1.16.1.md`. Six findings, all against my own work.

### The serious one
**v1.16.0 shipped five agent modules and 55 tests that the running system never
called.** `WorkflowEngine` still set `approved_rca = deterministic` and imported
nothing from `agents`; the predictive pipeline used its own gate logic. The claim
"agents decide, rules check" was true of the modules and false of the system.

Second occurrence. v1.11.0 shipped a router the page never invoked, and I wrote the
lesson down then. Fifty-five passing tests gave no signal, because every test
constructed its own agent.

Fixed for the predictive branch, which is standard library and testable here: the
triage agent and `guards.evaluate` are wired into `process`. A new test scans
application sources outside the `agents` package and fails if nothing constructs an
agent; verified by reverting the wiring and watching it fail. `WorkflowEngine`
remains unwired and is listed as open rather than done.

### Also fixed
- **The predictive branch could not refuse anything.** `Verdict` declared
  `"blocked"` and no code path returned it, in a branch that deliberately bypasses
  the main engine's gate. It now consults the policy guard before a truck roll.
- **Two provider switches disagreed.** `MODEL_PROVIDER=fake` with a key present
  sent the RCA assistant to the fake and the agents live, so a demo meant to stay
  offline would have made real API calls. Either switch now forces the fake.
- **The committed A/B harness measured a configuration the bundle no longer used.**
  An `agent_decides` arm was added. Wrong answers fall from 4 to 2 because the
  approved domain is now the agent's; gate precision falls from 0.571 to 0.286 for
  the same reason, since a larger share of gates are the rules objecting to a
  correct answer. Reporting one without the other would flatter the change.
- **`HIGH_BLAST_RADIUS` had no stated basis.** Now documented and exposed through
  `guards.assumptions()`.

### Not fixed, deliberately
Thirteen settings are declared and read nowhere. Most are pre-existing v1.2 fields,
and removing settings that compose or the UI may reference by string is a change I
cannot verify without running the stack.

### New standing check
A module no application code imports is a claim, not a capability. Unit tests
cannot detect it, because each test supplies its own caller.

512 stdlib tests pass.

## 1.16.0 - agents decide, rules check

The operator chose that agents decide and that policy and the gates are the only
guard. That inverts the bundle's central property, so it is implemented as an
inversion rather than as an addition, and the claim it invalidates has been
re-measured rather than left standing.

### Added
`src/lpr_cpe_demo/agents/`, standard library only:
- `provider.py` real Anthropic API calls over `urllib`, with a fake fallback
- `base.py` schema validation, second-best parsing, deterministic fallback
- `decisions.py` four agents: RCA, recommendation, routing, predictive triage
- `guards.py` the policy that is now the only guard
- `tests/test_agents.py`, 55 tests
- `docs/AGENT_AUTHORITY.md`

### What the rules do now
They stopped deciding and started checking. Every `AgentDecision` carries the
deterministic answer as its **baseline** (disagreement gates), its **fallback**
(unreachable provider, unparsable output, unknown value, confidence outside 0 to 1)
and its **floor** (on an incident where the agent fails, it *is* the rules).

### The measurement that replaces the old one
The A/B harness's headline finding — the model can never change an outcome — was
true and is now false. Re-measured on the same 18 cases:

| | |
|---|---|
| Deterministic correct | 14 / 18 |
| Agent correct | **16 / 18** |
| Disagreements, all gated | 6 |
| Agent right when they disagree | 4 |
| Rules right when they disagree | 2 |
| Agent wrong **and** rules agree, nothing gates | **0** |

Accuracy is now a real outcome rather than identical across arms by construction.
Gate load is 33% of incidents at about $19.67 each, which is cheap against a
misdispatch at $354 to $1,071 but is not free.

**The new exposure is the agent wrong and the rules agreeing**, because then
nothing gates. It is zero on this benchmark, which is a small sample and not a
property. It is why the rules must keep running: delete them and that failure mode
becomes silent.

### Policy became load-bearing, so it was made strong
`_policy` checked two things. `guards.evaluate` now blocks a remote action against
a physical fault, clean boots on a plant fault, an attempt past budget, a dispatch
to a base without the skill or part, and any action with no evidence. `BLOCKED`
beats `REQUIRES_APPROVAL`, so a human cannot approve what must never happen.

### Second-best is enforced, not optional
A recommendation with no alternative, or an alternative with no `why_not_chosen`,
is rejected and falls back. An approver at a gate needs something to overturn to;
a list entry without a reason it lost is not that.

### Notes
- Every agent prompt carries the untrusted-data notice, asserted by test.
- No live provider call has been made here: no network. The seam is exercised
  against canned responses for 4xx without retry, 5xx with retry, transport
  failure, missing text block, unparsable output, schema violation and provider
  absence.
- The default stays the fake, so a missing key degrades to a working demo.

501 stdlib tests pass.

## 1.15.0 - predictive modem scanning as a scheduled branch

A daily scan that flags poorly performing modems, auto-remediates, and hands the
rest to the main flow with a human gate. Six design choices were taken by the
operator and are asserted by test rather than inferred.

### Added
`src/lpr_cpe_demo/predictive/`, standard library only so the branch runs and is
testable independently of the pydantic-bound engine:

- `config.py` every threshold, rate, window and cap, with a `basis` string
- `signals.py` synthetic PNM telemetry with degradation trajectories
- `scanner.py` classification into two ticket classes, dedup, repeat detection
- `pipeline.py` auto-remediate then gate, activating `PolicyVerdict.ALLOWED`
- `handoff.py` the merge into the main flow
- `service.py` the daily run, with flag history persisted across restarts
- `scripts/run_predictive_scan.py`
- `tests/test_predictive.py`, 64 tests

### What makes the simulation realistic rather than random
Each modem carries a latent root cause and a trajectory consistent with it.
Physical causes degrade monotonically, configuration and firmware causes step,
and CPE-state and Wi-Fi causes are erratic. Measured over 40 modems: a degrading
tap trends at r-squared 0.54 to 0.67, while an erratic cause reaches 0.09 and is
correctly rejected by the `min_trend_r2` gate. **No modem whose true cause is
`stable` was ever flagged.**

Each modem also has an onset day spread over 60 days, and a modem whose ticket was
closed relapses after a cause-specific interval unless the fix was permanent. Both
are necessary: without onset the first scan flags everything and every later scan
finds nothing; without relapse the network heals permanently by day three and the
repeat-offender trigger can never fire.

That produces two distinct numbers, which differ by more than an order of
magnitude and answer different questions:

| | tickets | auto-closed | to a human |
|---|---|---|---|
| Launch backlog (`--backlog`) | 400, capped, 79 suppressed | 29% | 285 |
| Steady state, per day | 4 to 11 | 30 to 60% | 2 to 8 |

### Three defects found and fixed while building it
**The hard-failure trigger was vacuous.** The scanner only raises a forecast ticket
when the breach falls inside the horizon, so "notify when a hard failure is
forecast inside the horizon" fired on every forecast ticket: 399 of 400 gated.
`HARD_FAILURE_KPIS` now names the three KPIs whose alarm means loss of service
rather than degradation. This was a definition I had to make concrete, and it is
flagged as such in the code.

**Notification was assessed on stale risk.** A forecast failure that remediation
had already averted still demanded a customer notification. Triggers are now
evaluated on residual risk; repeat offender is deliberately exempt, because a modem
flagged three times in a month is worth mentioning even when tonight's reboot
worked.

**An open ticket counted as a repeat.** Re-flagging a modem nightly while its
ticket was still open made every modem a repeat offender by day two, the
notification trigger fired on the whole population, and the auto-close rate fell to
zero. Only a closed ticket now enters the repeat history, and an open ticket
suppresses a duplicate finding.

### The consequence of two choices, stated rather than buried
The operator chose that the forecast class auto-remediates including a reboot, and
that a service-affecting remediation alone does **not** require notification.
Together: a working modem can be rebooted with no notice. The maintenance window
is the only control on that, so it is a first-class parameter and
`execute_allowed` refuses a service-affecting action outside it. A deferred reboot
gates rather than being silently dropped.

### The merge rule and what it implies
The predictive incident stays parent, a later customer call attaches, and the SLA
runs from when the scan opened it. A customer calling 30 hours later inherits a
clock that is already breached, so `sla_breached_at_attach` and
`hours_of_clock_already_spent` are surfaced on the merge decision rather than left
for an agent to discover.

446 stdlib tests pass. The branch has not been run in a container, and it does not
schedule itself: cron, a CronJob or a compose loop calls `run_once`.

## 1.14.1 - fix zero-minute travel, and price the journey to where the work is

You spotted a one-way travel time of 0 minutes. Two defects behind it.

### Fixed: a hub serving its own municipio billed nothing
A `DispatchBase` carries the coordinates of its host `Site`, and `travel_plan`
measured base to **site centroid**. When a fault's municipio hosts the hub those
are the same point, so haversine returned exactly 0 and the ledger billed 0 minutes
and no vehicle cost. Six of the 23 modelled sites host a hub, so this affected a
large share of metro volume.

`MIN_ONE_WAY_MINUTES` per archetype now applies a floor: metro 22, mountain 20,
coastal 16, island 14. No dispatch takes zero travel — the crew still leaves the
depot, crosses the municipio, finds the address and parks. Metro is highest because
congestion rather than distance dominates a short journey there. The leg
description states when the floor was applied, so an operator can see why it reads
22 minutes.

### Fixed: travel ignored the actual work location
`fault_generator` jitters a household, delimiter and intervention point several
kilometres from the centroid — that is what spreads the pins on the map — but
`travel_plan` and `select_base` used the centroid regardless. A fault 4.67 km
outside Aguadilla was priced as if it were at the town hall.

`travel_plan`, `select_base`, `simulate_resolution` and `false_negative_cost` now
accept a `destination`, and the generator passes the intervention point to all of
them, so the map, the ledger and the false-negative cost price the same journey.

### This closes a gap I recorded and failed to trace
The v1.9.0 benchmark reconciliation put metro at **0.6x** the published band and I
wrote it off as "a hub is co-located and the bottom-up model bills almost no
travel". That was the symptom of this bug, not an explanation of it. After the fix:

| site | bottom-up | benchmark | ratio | was |
|---|---|---|---|---|
| Bayamon | $185 | $212 | **0.87x** | 0.6x |
| Arecibo | $354 | $212 | 1.67x | 1.7x |
| Utuado | $330 | $255 | 1.29x | 1.3x |
| Culebra | $1,071 | $655 | 1.63x | 1.6x |

Metro moved into a defensible range. The other archetypes barely moved, which is
the expected result: their journeys were already real.

### Added
Ten tests in `tests/test_geography.py`: no site reports zero travel, every hub
serving its own municipio clears the floor, the floor does not mask a genuinely
long journey, a supplied destination changes the answer, the island road leg to the
terminal clears the floor, and no generated fault has zero travel or zero vehicle
cost.

Fixtures, the footprint map and `docs/control_tower.html` regenerated. The v1.4.0
fixture-drift guard caught the stale travel numbers, as it did for the plant
identifiers in v1.13.2.

382 stdlib tests pass.

## 1.14.0 - the control tower as a standalone drill-down HTML page

### Added
- `scripts/generate_control_tower_html.py` and `docs/control_tower.html`: the
  control tower as **one self-contained file**. No Docker, no Streamlit, no pip, no
  server. It opens from a USB stick.
- `src/lpr_cpe_demo/html_charts.py`: donut, stacked bars, grouped bars, lines and
  an inline meter, all computed as SVG markup.
- `tests/test_html_report.py`: 22 tests.
- A download button on the Streamlit Control Tower page.

### Zero external requests, asserted not assumed
A CDN script tag is the normal way to get charts and is exactly what fails on a
network that blocks outbound traffic — the failure mode that has cost this project
the most time. So every chart is hand-computed SVG, styles are inline, and a test
asserts there is no `script src`, `link href`, `img src`, `@import` or `@font-face`
pointing outward. Verified: **0 external resource references.**

### Drill levels
    overview            KPI tiles, one card per panel
    #/panel/<key>       the panel in full plus its data-contract requirements
    #/incident/<id>     plant chain, dispatch facts, and the effort ledger
    #/contract          all 31 fields, each with its source system and status

Routing is hash-based, so browser back and forward work and any level can be
linked or bookmarked. Rows are keyboard reachable with `tabindex` and `role="link"`,
and Enter drills.

### Provenance travels with the data
Every drill level shows the same computed, assumed or synthetic chip as the
overview, and a test asserts it. A number that loses its caveat on the way down is
worse than one that never carried it: the deeper view is the one someone
screenshots. The synthetic panel still says SHAPE ONLY at drill level, and every
incident body repeats that the rates are assumed.

### Chart edge cases handled, because SVG fails silently
- A single 100% slice renders as a ring, since an arc path cannot express 360
  degrees.
- A zero slice is skipped rather than emitting a degenerate path.
- A `None` value renders as "no observation" rather than as zero.
- A test asserts nothing is drawn outside the viewBox across four chart types with
  long labels and six series, because an off-canvas label produces no error.
- Labels and table cells are escaped; inline SVG passes through deliberately.

### Reproducibility
The footer records the seed and incident count. A test regenerates the page twice
and asserts byte equality apart from the timestamp, and a second test fails if the
committed page has drifted from the current model.

353 stdlib tests pass. The page has not been opened in a browser here: structure,
payload, drill-target resolution and geometry are verified programmatically, but no
rendering engine has laid it out.

## 1.13.2 - deep audit of code, logic and output: three defects fixed

Report: `docs/AUDIT_DEEP_v1.13.2.md`. Five passes: mathematics against external
references, silent-failure paths, cross-artifact output consistency, boundary and
adversarial inputs, metric soundness.

### Fixed: plant identifiers collided at realistic scale
`plant._seq` computed `int(sha256(...)[:6], 16) % 10000` — a four-digit space.
Measured across the modelled footprint: **2,929 of San Juan's 8,709 taps shared an
identifier, 33.6%**. Ponce 22.3%, Bayamon 20.1%. By the birthday bound a 50% chance
of one collision arrives at about 118 elements, so it was reachable at any real
scale.

The consequence is operational: `TAP-SJU-4C00117` was not unique, so a work order or
an MR could name the wrong plant element, which defeats the purpose of a delimiter.

Uniqueness now comes from the index, injective by construction, with a
site-and-kind hash prefix so the id still reads as plant. Verified zero collisions
across every site and both technologies at full scale, 20,000 distinct for one
site, byte-identical across a fresh process. Five tests added. The nine scenario
fixtures carried old identifiers and were regenerated; the v1.4.0 drift guard
caught that immediately.

### Fixed: the router failed silently
`geo_layers.road_leg_records` had `except Exception: pass`. A leg that failed to
route fell back to a straight line and discarded the exception, so a blocked OSRM
endpoint was **indistinguishable from no router being configured**. Given that
setting `ROUTING_PROVIDER=osrm` was supposed to snap legs to roads, a blocked proxy
would have produced no visible difference and no explanation.

`routing_summary` now returns `router_error` and `failed_legs`, and the page warns
with the exception and points at `OSRM_URL`.

### Fixed: a configured ceiling that no code read
`Settings.max_remote_attempts` was declared, defaulted to 2 and set in the test
fixtures. **Nothing read it.** `_failure_review` enforced `max_field_visits` and
`max_mr_attempts` and skipped remote attempts, so remote retries were bounded only
by the global `graph_max_steps`. Now enforced alongside the other two.

Second unenforced guard across two audits, after `writes_permitted`. A setting no
code reads is a claim, not a control.

### Changed
Two dashboard blocks caveated themselves as "stated positions" and "illustrative" —
honest but invisible to a keyword scan, so no test could enforce it. Both now say
ASSUMED, and a test asserts every non-computed block carries a machine-detectable
caveat.

### Verified sound, with no changes needed
- 16 mathematical checks against external references: haversine, WCAG contrast and
  luminance, BM25 term-frequency saturation, gate behaviour at the exact threshold.
  All correct.
- 13 cross-artifact consistency checks. The simulator, dashboard, effort model and
  A/B harness agree to the cent.
- Metric definitions do not double count: a case both gated and rules-wrong counts
  as a catch and costs nothing; a wasted visit is priced per-dispatch, not
  per-completed.
- No collisions in the full-SHA-256 idempotency key across 8,100 inputs.
- Seven aggregation paths safe on empty input.

### Audit errors, recorded
Five of my own audit checks produced false findings: two haversine reference values
taken from memory rather than a source, two exception-handler idioms my detector
did not recognise, and five probes that called a keyword-only function
positionally. An audit that reports a false failure costs as much trust as one that
misses a real defect.

351 stdlib tests pass. The `max_remote_attempts` fix lands in the engine, which
this environment cannot execute: statically correct, unexercised.

## 1.13.1 - fix a use-before-assignment, and guard the class of bug

### Fixed
`NameError: name 'router' is not defined` on the Fault Simulator page.

The cause is worse than the crash. A v1.11.0 patch was meant to insert
`router = router_from_env()` and to pass the router to `_render_map`, but it
targeted the wrong indentation and **silently applied nothing**. So the name was
never bound, and the routing feature shipped, was tested, and was never reached by
the page at all. I reported it as wired; it was not.

`router` is now assigned once near the top of `render()` and passed to both
`_render_map` and `road_leg_records`.

### Added
Two guards in `tests/test_ui_widgets.py`, bringing the file to 30 tests.

**Use-before-assignment checker.** `compileall` cannot catch this: the code is
valid and Python resolves the name at runtime, which for a Streamlit page means
when a person opens it. The checker combines `symtable`, for which names are
genuinely local to a scope, with AST line ordering. A companion test plants a
fault and asserts the checker fires, because a checker that never fires is
worthless.

Getting it correct took two passes, both false positives worth recording:
- Comprehension targets looked like use-before-assignment in the enclosing
  function, because `ast.walk` descends into comprehension scopes. Fixed by
  walking scope-aware.
- Nested `def`s inside `with` or `if` blocks looked unbound, because the first fix
  skipped scope-opening nodes entirely. A `def` binds a name in the enclosing
  scope even though its body is a separate scope, so the node is now yielded
  without descending into it.

**Wiring test.** Asserts the page builds a router, passes it to `_render_map` as a
keyword, and passes it to `road_leg_records`. A feature that is tested in isolation
and never called from the page is indistinguishable from a feature that does not
exist.

### Note
This is the third UI defect found by rendering rather than by testing. The first
two were a widget bound and an unsupported pydeck call, both now guarded. The
pattern is consistent: string-replace patches that fail to match do nothing and say
nothing.

## 1.13.0 - a data contract for the dashboard, and instrumentation in the flow

The control tower was populated by `fault_generator`, which invents incidents.
Fine for a mockup, useless as an operational view. This release defines what the
dashboard needs, wires the workflow to supply what it can, and names the source
system for everything it cannot.

### Added
- `src/lpr_cpe_demo/telemetry.py`
  - `DATA_CONTRACT`: 31 fields across 8 panels, each naming its source system,
    grain, refresh interval and whether the flow can supply it today.
  - `IncidentRecord` and `project`: the flat row every panel is computed from.
    The projector reads a duck-typed state, so it is fully tested with a stub even
    though the real `IncidentState` needs pydantic.
  - `Aggregator`: rolls records into panel shapes, replacing rather than
    duplicating a record for an incident already present, because the engine emits
    on every stage transition.
- `dashboard.build_from_flow(records)`: builds from workflow telemetry instead of
  the generator.
- A **Data contract** panel on the control tower, showing per panel how many
  fields are in-flow, modelled or missing, and which systems are blocking.
- `tests/test_telemetry.py`: 42 tests.

### Changed
- `WorkflowEngine` takes an optional `telemetry_sink`, called from `run_one` —
  the single choke point every stage transition passes through. A sink failure is
  counted in `telemetry_failures`, never raised: instrumentation must not fail an
  incident.

### What the contract says
| | fields |
|---|---|
| available from the workflow today | 15 |
| computable on modelled inputs | 5 |
| needing a source system not wired | 11 |

Ten distinct systems would close the gap: CMTS or PNM collector, OLT EMS, IP core
telemetry, TR-369 or CPE telemetry, OSS work-order history, OSS reclassification
history, OSS reconciliation, alarm ingest, a learning feedback loop, and a
time-and-motion baseline.

### The useful finding
Instrumenting what already exists moves the autonomy funnel from **one** measurable
stage to **four**. Correlate, Diagnose, Act and Validate are all inferable from
durable state: a `gate_reason` means Diagnose asked a person, an `approval_result`
means Act did, a parent attachment means Correlate resolved autonomously.

Detect and Learn remain unmeasurable and now report `None` with an observation
count of zero, rather than a percentage. A zero would be a claim; `None` is the
truth. Closed-loop confidence also gains three real counters — replayed effects,
rejected approval tokens, delimiter-resolved share — replacing three judgement
scores.

### Note
`build_from_flow` deliberately omits `service_health_by_layer`. Switching to live
data must not fabricate a panel whose four fields all need collectors that are not
wired. A test asserts the omission.

## 1.12.1 - full bundle audit, with two defects fixed and a coverage gap closed

Report: `docs/AUDIT_v1.12.1.md`. Checks were executed, not asserted.

### Fixed
- `mcp_server/security.py` leaked `binascii.Error` for a malformed approval token
  instead of `ApprovalTokenError`. A caller catching the typed error would not
  catch it, so untrusted input became an unhandled exception rather than a clean
  refusal. `_b64decode` and the JSON parse now raise
  `APPROVAL_TOKEN_MALFORMED`, and a non-dict payload is rejected.
- `llm/service.py` had no prompt-injection guidance. `_rca_prompt` interpolates
  `state.topology` and every evidence `summary` straight into the prompt, and
  those carry text from NXT, topology records and prior tickets. The model cannot
  execute anything, but a crafted summary could steer the recommended domain.
  `UNTRUSTED_DATA_NOTICE` now precedes the payload.

### Closed a gap I had reported as covered
The HMAC approval token was reported earlier as verified with ten forgery attempts
rejected. That was run at a prompt and never committed. The effect store's
idempotency guarantee had never been tested at all — only read.
`tests/test_security_store.py` adds 19 tests, including six concurrent commits of
one approval yielding exactly one effect, which is the guarantee that matters and
had never been exercised. Both modules are standard-library only, so there was no
reason for the gap.

### Removed
Six orphaned symbols left behind by the v1.10.0 move to the real pydeck API:
`layer_specs`, `fault_layer_specs`, `HUB_TOOLTIP`, `HUB_TOOLTIP_HTML`,
`ACCENT_WARM`, `DEFAULT_CORPUS`. The first two were tested but unreachable from
any page — 12 assertions covering code that could not run. Equivalent coverage was
added against the real pydeck API.

My first attempt at the removal used regular expressions, took the hub-record
builders as collateral and broke 15 tests. Reverted and redone with AST line spans.

### The headline finding
**16 of 43 modules are reachable by the 297 tests that run.** The other 27 need
packages this environment cannot install; six are covered only by test modules
that have never executed anywhere, and those six cover the workflow engine —
including the `fuse_and_gate` refactor from v1.3.0, which was audited statically
but never run. `make test-integration` is the highest-value next step.

## 1.12.0 - control tower in the supplied dashboard format

Adopts the block structure, dark theme and accent palette of
`e2e_fixed_access_assurance_orchestration_dashboard.json` as a new **Control
Tower** page: hero with badges, control strip, KPI row, charts, hotspot table,
closed-loop confidence and playbook backlog.

### Added
- `src/lpr_cpe_demo/dashboard.py` builds the spec from the live model, with a
  `provenance` on every block.
- `src/lpr_cpe_demo/ui/theme_dark.py`: slate-to-indigo gradient, `bg-white/8`
  glass cards, the six neon accents, transparent Plotly layout.
- `src/lpr_cpe_demo/ui/pages/control_tower.py`.
- `tests/test_dashboard.py`: 32 tests.

### The palette was measured before it was adopted
Neon on dark is easy to get wrong. Against the glass-card composite `#222A3B`:
cyan 7.95, amber 8.60, green 7.47, blue 5.65, red 5.34, violet 5.28 — all clear
WCAG AA for body text. One rule falls out: `slate-500` reaches only 3.02, so it is
large-text-only and `MUTED` is `slate-400` at 5.60 instead. A test asserts that.
Tables are forced opaque, since transparent data over a gradient is unreadable.

### Two deliberate departures from the supplied file
**Areas are Puerto Rico, not Dubai.** The template's hotspots sit in Jumeirah,
Business Bay, DIFC, Marina and Palm. Hotspots are now generated from the footprint
model, so they land in real municipios with a real dispatch hub behind each, and
severity follows blast radius: a drop fault is one household, a tap four to eight,
a node several hundred. A test asserts no template area leaks through.

**Numbers are computed where a model exists, and labelled where not.** The
template asserts "Truck rolls avoided: 128, +18%". That figure is not supportable;
the KPI now reads `6-27 / 1k` with the two unmeasured parameters named. Every block
carries one of three provenance chips, shown in the UI:

| provenance | blocks | meaning |
|---|---|---|
| computed | 4 | derived from this repository and reproducible |
| assumed | 3 | a stated parameter, replaceable in one place |
| synthetic | 1 | shape only, because no telemetry source exists |

`service_health_by_layer` is the synthetic one and says SHAPE ONLY in its note.
In the autonomy funnel only Diagnose is model-derived — the human share equals the
rate at which the RCA gate routes to a person — and the other five stages are
marked `assumed` per row.

Closed-loop confidence comes out at 77% against the template's asserted 86%,
because two guardrails score low honestly: inventory lineage at 58% (synthetic
plant identifiers, not OSS records) and rollback safe at 45% (no rollback path is
implemented).

### Fixed
- `cost_by_archetype` averaged wasted-visit cost over all incidents, so a small
  island sample drawing mostly remote-fixable faults read as `$0`, which looks
  free. It now averages over **dispatched** incidents and returns `None` rather
  than zero when nothing dispatched. The island separation is now visible: $655
  against $212 in metro.

### Note
- 279 stdlib tests pass. The page itself has not been rendered: no Streamlit or
  Plotly here, so the Plotly figures are unverified beyond layout construction.

## 1.11.0 - dispatches on real roads, and a Puerto Rico identity that stays readable

### Added: road routing
- `src/lpr_cpe_demo/routing.py`. `Router` protocol with `StraightLineRouter` (no
  network, the previous behaviour) and `OSRMRouter` (real road geometry). OSRM was
  chosen because the API is a plain GET with no key, GeoJSON geometry avoids
  polyline decoding, and it can be self-hosted, which matters on a network that
  will not reach a public service.
- Selected by `ROUTING_PROVIDER=straight|osrm` with `OSRM_URL`. Default stays
  `straight`, so the map works where nothing is reachable.
- `FallbackRouter` degrades **per leg**, not per map: one unroutable leg draws
  straight and the rest still follow roads. `Route.on_roads` carries which, and
  the page caption reports the split honestly rather than implying everything is
  routed.
- In-process and optional on-disk caching. The public OSRM demo server has a usage
  policy that discourages repeated identical requests.

**Ferry legs are never road-routed.** A driving profile asked to cross to Vieques
either fails or invents a land path, so only the land leg to the terminal is sent
to the router and the crossing stays an arc. A test asserts every island road leg
stops at the terminal.

### Added: visual identity with measured readability
- `scripts/generate_landmark_band.py` draws **original** line work: a garita and
  crenellated wall from the San Juan fortifications, the Cordillera ridgeline, a
  coastal lighthouse and palm forms. Nothing is fetched and no photograph is
  embedded, so there is no licensing question and no network dependency. A test
  asserts the SVGs contain no `<image>`, no `xlink:href` and no URL other than the
  SVG namespace.
- `src/lpr_cpe_demo/ui/theme.py` with the palette, CSS, and WCAG contrast
  arithmetic. `src/lpr_cpe_demo/ui/artwork.py` inlines the SVGs as data URIs.
- `UI_ARTWORK=off` disables the artwork without a code change.

### How readability is protected
Decoration is the usual way a dashboard becomes unreadable, so three rules are
enforced and tested rather than asserted:

1. Artwork appears **only** in the header band and as a fixed corner watermark. It
   never sits behind a table, a metric or body copy; those surfaces are forced
   opaque in CSS.
2. Contrast is measured against the **composite** of artwork over surface, not
   against a clean surface. Header band composites to `#DDE1DD`, watermark to
   `#F1F3F3`.
3. Every pairing must clear WCAG AA. All eight currently do, with the tightest at
   6.05:1 against a 4.5 requirement:

| pairing | ratio | required |
|---|---|---|
| body on surface | 14.21 | 4.5 |
| body over watermark | 13.19 | 4.5 |
| caption over watermark | 6.50 | 4.5 |
| heading over header artwork | 6.56 | 3.0 |
| danger on surface | 6.05 | 4.5 |

One test raises the overlay opacity past the cap and asserts contrast *fails*,
which shows the cap is doing work rather than being decorative.

### Notes
- 247 stdlib tests pass. The OSRM client is tested against a canned response,
  covering URL construction, lon/lat order, geometry parsing, both cache layers,
  fallback, and rejection of three malformed responses.
- Not executed: no network here, so the OSRM path has never contacted a live
  server. The client is exercised end to end against a stub instead.

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
