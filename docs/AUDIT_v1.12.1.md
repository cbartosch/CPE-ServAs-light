# Bundle audit — v1.12.1

**Scope:** the whole bundle as of commit `v1.12.1`, 43 application modules and
12 test modules.
**Method:** checks were executed, not asserted. Where a check produced a false
result because of how I wrote it, that is recorded rather than quietly corrected.
**Auditor's position:** most of this bundle is my own work, so this is a
self-audit. Findings against my own code are marked **(mine)**.

---

## 1. Verdict

The audit-control core is sound and well covered. The gap is coverage breadth:
**16 of 43 modules are reachable by the 297 tests that actually run.** The other
27 need packages this environment cannot install, and six of them are covered
only by test modules that have never been executed anywhere.

Two genuine defects were found and fixed during the audit. Six orphaned symbols
were removed. One control I had reported to you as verified turned out to have no
committed test at all.

---

## 2. Integrity and static correctness

| Check | Result |
|---|---|
| Manifest verification | 167/167, 0 mismatched, 0 missing, 0 untracked |
| Git working tree | clean, 16 commits |
| `compileall` over src, tests, scripts | pass |
| Unresolvable intra-package imports | 0 |
| Secrets scan (provider keys, AWS, GitHub, private keys, bearer) | none found |
| `.env` in tree | absent, and gitignored |

---

## 3. Defects found and fixed

### 3.1 Malformed approval token escaped as the wrong exception type

`mcp_server/security.py` decoded the token payload without guarding
`base64.urlsafe_b64decode`. A malformed token such as `"a.b.c"` raised
`binascii.Error`, which is **not** an `ApprovalTokenError`. Any caller catching
the typed error would not catch it, so untrusted input became an unhandled
exception rather than a clean refusal.

Fixed: `_b64decode` and the JSON parse now raise
`ApprovalTokenError("APPROVAL_TOKEN_MALFORMED")`, and a non-dict payload is
rejected. Five malformed inputs are now asserted.

### 3.2 No prompt-injection guidance on the real-provider path **(mine to have missed)**

`_rca_prompt` interpolates `state.topology` and every evidence `summary` directly
into the prompt. Those fields carry text from NXT, topology records and prior
tickets — untrusted data. The prompt said "use only the supplied evidence" but
never said the evidence is data rather than instruction.

The exposure is bounded: side-effecting tools are never bound to the model, so it
cannot execute anything. But a crafted `summary` could steer the recommended
domain, which is precisely what the RCA gate then has to catch.

Fixed: `UNTRUSTED_DATA_NOTICE` is emitted immediately before the payload,
instructing the model to treat every value as data, ignore embedded directives,
and record them in `missing_evidence`.

---

## 4. The most serious finding: a control reported as verified but never committed

Earlier in this project I reported the HMAC approval token as verified with "ten
forgery attempts rejected". That was true, and it was **run at a prompt and never
committed as a test**. The same applied to the effect store's idempotency
guarantee, which I never tested at all — I only read the SQL.

Both modules are standard-library only. There was no reason for the gap.

`tests/test_security_store.py` now commits 19 tests covering:

- token round-trip, mandatory expiry, expired token, wrong secret, five malformed
  forms
- four forgeries that keep the original signature while mutating the payload:
  escalated `action_type`, swapped `incident_id`, swapped `idempotency_key`,
  extended `exp`
- a check that the signature is not a plain digest of the payload
- effect store: first-write-wins on replay, `APPROVAL_ALREADY_CONSUMED` on reuse
  with a different key, no partial effect after a refused reuse, persistence
  across a reopen, and **six concurrent commits of one approval yielding exactly
  one effect**

The last one is the guarantee that matters and it had never been exercised.

---

## 5. Dead code removed

Six orphaned symbols, all left behind by the v1.10.0 move from deck.gl JSON
specifications to the real `pdk.Layer` API:

| Symbol | Why it was orphaned |
|---|---|
| `geo_layers.layer_specs` | replaced by `ui/deck.footprint_layers` |
| `geo_layers.fault_layer_specs` | replaced by `ui/deck.fault_layers` |
| `geo_layers.HUB_TOOLTIP` | superseded by `SITE_TOOLTIP` and `FAULT_TOOLTIP` |
| `geo_layers.HUB_TOOLTIP_HTML` | never referenced |
| `theme.ACCENT_WARM` | never referenced |
| `retrieval.DEFAULT_CORPUS` | never referenced |

The first two were **tested but unused by the application** — 12 assertions
covering a code path no page could reach. Equivalent coverage was added against
the real pydeck API instead, so the assertions now test what ships.

**A process note.** My first removal used regular expressions and deleted the
hub-record builders as collateral, breaking 15 tests. I reverted and redid it with
AST line spans. Regex surgery on source is how you turn a tidy-up into an outage.

---

## 6. Test coverage: the honest picture

```
297 tests run, 0 failures
  6 errors: test_api, test_controls, test_llm_boundary, test_mcp_controls,
            test_mcp_http, test_workflow — all fail to LOAD, needing
            pytest, fastapi or pydantic
```

Modules imported when the runnable suite executes: **16 of 43**.

| Layer | Covered by executed tests | Notes |
|---|---|---|
| Audit controls (`controls`, `plant`, `effort`, `benchmarks`, `geography`, `retrieval`, `ab_metrics`, `dashboard`, `routing`, `fault_generator`, `geo_layers`) | yes | the reasoning core |
| `mcp_server.security`, `mcp_server.store` | **yes, new in this audit** | previously uncovered |
| `ui.theme`, `ui.theme_dark`, `ui.deck`, `ui.fmt`, `ui.artwork` | yes | via stub pydeck and contrast arithmetic |
| `workflow.engine`, `workflow.service`, `domain`, `config` | **no** | need pydantic; covered only by the 6 unrunnable modules |
| `api.main`, `mcp_server.app`, `mcp_client.client`, `persistence.repository` | **no** | need fastapi, httpx, sqlalchemy |
| All 9 Streamlit pages | **structurally only** | widget bounds, `render()` presence, registration, deck construction. **None has been rendered except by you, once.** |
| `workflow.langgraph_runtime` | **no** | needs langgraph; never executed anywhere |

### The refactor I could not test

In v1.3.0 I replaced the inline fusion block in `WorkflowEngine._fusion` with
`controls.fuse_and_gate`. The tests covering it need pydantic. I audited it
statically instead:

- `_fusion` still assigns `approved_rca`, `domain_agreement`, `gate_reason`,
  `new_evidence_since_last_rca`, `stage`
- every field read elsewhere in the engine is still set — nothing orphaned
- no stale inline logic remains
- `test_workflow.py` references `domain_agreement` and `gate_reason`, both of
  which survive

That reduces the risk. It does not eliminate it. **Run `make test-integration`
before anyone relies on the engine.**

---

## 7. Provenance: what could be quoted, and what stands behind it

### Externally sourced and fetched during this project

| Claim | Source |
|---|---|
| Truck roll $150–300, bands, rural +15–25% | AEX, fetched 2026-08-17 |
| LangGraph re-runs a node from the top on resume | LangChain docs, fetched |
| MCP 2026-07-28 breaking changes | MCP blog, fetched |
| LPR fixed footprint is PR; USVI mobile only | Wikipedia, FCC, searched |
| ~1.22M locations across 78 municipios | FCC, searched |

### Asserted, with no external source

All labour rates and durations. All plant serving ratios. All six dispatch hub
locations. Domain mix by archetype. Five of six autonomy funnel stages. All
closed-loop guardrail scores. Service health curves.

Every one is reachable in a single place — `effort.RATES`, `effort.DURATIONS`,
`plant.PLANT_ASSUMPTIONS`, `geography.DISPATCH_BASES`,
`fault_generator.DOMAIN_MIX` — and each carries a `basis` string. The control
tower shows a provenance chip per panel: 4 computed, 3 assumed, 1 synthetic.

### The one number most likely to be misquoted

Truck rolls avoided. The supplied dashboard template asserted **128, +18%**. The
supportable figure is **6–27 per thousand incidents**, governed by two unmeasured
parameters. The KPI renders as a range with both named. If a single number appears
in a deck, it did not come from this bundle.

---

## 8. Dependency risk

19 pinned packages. **Every pin is past my training cutoff of May 2026 and I
cannot verify any of them resolves**, including `langgraph==1.2.11`,
`langchain==1.3.14`, `mcp==2.0.0`, `streamlit==1.61.1`, `fastapi==0.141.1`.

Partial evidence: your build log showed PyPI serving `mcp-2.0.0`,
`pydantic-2.13.4`, `pydantic_settings-2.14.1` and `fastapi==0.141.1`, so at least
four exist. Whether the full set resolves together is unproven.

`langchain-mcp-adapters` is deliberately absent — dropping it is what allows the
2026-07-28 stateless MCP profile.

---

## 9. Unresolved and carried forward

1. **The Docker build has never completed here.** No Docker in this environment.
2. **Eight of nine Streamlit pages have never rendered.** You rendered the
   simulator once, which found two bugs immediately. Expect more.
3. **`writes_permitted` is a guard nothing consults.** It is computed and
   displayed on the System Monitor but never gates a write. Not a live
   vulnerability, since no production write path exists — but it reads as a
   control and is not one. Left as-is deliberately; wiring a guard to nothing
   would be worse.
4. **OSRM has never contacted a live server.** Tested against a canned response.
5. **`ui.theme` and `ui.theme_dark` both inject CSS.** `app.py` applies the light
   theme globally; `control_tower` applies the dark theme on top. Later rules win
   for overlapping selectors, so it should work, but it is fragile. A single theme
   selected at the app level would be cleaner.
6. **Retrieval recall of 1.0 comes from 18 cases I wrote myself.** Not a
   real-world figure. Plan against the 50–75% columns.

---

## 10. What I would do next, in order

1. `make test-integration` against the running stack — the 6 unrunnable test
   modules are the largest unknown, and they cover the workflow engine.
2. Render the remaining eight pages and fix what breaks.
3. Replace `effort.RATES` and `effort.DURATIONS` with LPR figures. Every dollar
   in the bundle flows from those two dictionaries.
4. Replace `DISPATCH_BASES` with real facility locations.
5. Measure the two parameters behind the truck-roll claim from OSS history:
   the share of no-fault-found dispatch reclassified to a different domain, and
   retrieval recall over 200 historical incidents.
6. Resolve the dual-theme arrangement.
