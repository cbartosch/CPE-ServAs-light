# Deep audit — code, logic and output — v1.13.2

**Scope:** the whole bundle. Five audit passes: mathematics against independent
references, silent-failure paths, cross-artifact output consistency, boundary and
adversarial inputs, and metric-definition soundness.

**Method:** every check was executed. Where a check produced a false result
because of how I wrote it, that is recorded as a finding against the audit rather
than quietly dropped.

**Position:** most of this bundle is my work, so this is a self-audit. Findings
against my own code are marked **(mine)**.

---

## Summary

| | |
|---|---|
| Real defects found | **3** |
| Defects fixed in this pass | **3** |
| False findings produced by my own audit code | **5** |
| Tests added | 7 (349 → 351 net of prunes) |
| Mathematics verified against external references | 16 checks, all correct |
| Cross-artifact output consistency | 13 checks, all agree |

The most serious defect had a 34% incidence at realistic scale and would have put
the wrong plant element on a work order.

---

## Pass A — mathematics against independent references

16 checks. **All the code was correct.** Two apparent failures were my reference
values.

| Check | Result |
|---|---|
| Haversine, pole to pole | 20,015 km, correct |
| Haversine, identity | exactly 0 |
| WCAG black on white | 21.0, exact |
| WCAG `#777777` on white | 4.48, matches WebAIM |
| sRGB luminance of primaries | 0.2126 / 0.7152 / 0.0722, exact |
| Contrast symmetry | holds |
| BM25 term isolation | correct |
| BM25 tf saturation | 1.148 for 3× tf, hand-verified correct |
| Gate at exactly the threshold | proceeds; one ULP below gates |
| Fused confidence is the minimum | holds |

### Audit errors, recorded

**A1 (audit error).** I expected the quarter-equator at 10,018 km, using the
*equatorial* radius. The code uses the mean radius, 6371.0088 km, giving 10,007.6
km — which is the convention for haversine on a sphere. The code is right.

**A1 (audit error).** I expected San Juan to Mayagüez at 110.4 km from memory. An
independent equirectangular calculation gives 113.2 km against the code's 113.0.
The code is right and my expectation was a guess dressed as a reference.

That distinction matters. An audit that reports a false failure costs as much trust
as one that misses a real one.

---

## Pass B — silent-failure paths

This was targeted, because three UI defects have now reached you and all three
shared a shape: something failed and said nothing.

Six broad exception handlers found. **Two were false findings** — my detector
looked for `raise`, `log`, a counter or a `return`, and missed two legitimate
idioms:

- `engine.py:268` sets `state.last_error` on LLM degradation. Handled.
- `service.py:248` sets `mcp_status = f"error: {exc}"`, surfaced on the System
  Monitor. Handled.

Two are legitimate and documented: the OSRM disk-cache write, and the pydeck and
folium availability probes.

### Finding B1 — the router failed silently **(mine)**

`geo_layers.road_leg_records` had `except Exception: pass`. A leg that failed to
route fell back to a straight line and the exception was discarded entirely.

The consequence is precisely the failure mode that has cost the most time on this
project: with `ROUTING_PROVIDER=osrm` set and a blocked endpoint, the map showed
straight lines — **indistinguishable from no router being configured**. I told you
setting two variables would snap legs to roads; if your proxy blocked OSRM you
would have seen no difference and no explanation.

Fixed. `road_leg_records` collects the first error, `routing_summary` returns
`router_error` and `failed_legs`, and the page now shows a warning naming the
exception and pointing at `OSRM_URL`. Verified: a broken router now reports
`failed_legs=20, ConnectionError: connection refused` where before it reported
nothing.

Zero-division reachability was probed across seven aggregation paths on empty
input. All safe.

---

## Pass C — output consistency

13 cross-checks between the simulator, the dashboard, the effort model and the A/B
harness. **All agree.**

- Total cost: simulator `$15,126.02` vs dashboard `$15,126`
- A stored fault's cost reproduces exactly when the ledger is re-run
- Misdispatch premium equals the independently computed false-negative cost to the
  cent
- The dashboard's `6–27 / 1k` matches the documented sensitivity range
- The scripted-model arm is identical to deterministic on gates, as claimed
- Modelled households are 48% of the FCC anchor, consistent with 23 of 78
  municipios; HFC and PON split sums exactly to the total

### Observation C4 — cosmetic

The root-cause mix sums to **100.1%**, because each slice is rounded to one decimal
before summing. Harmless arithmetically, but a pie chart labelled 100.1% invites a
question you do not want in that meeting. Left as-is deliberately: forcing the
largest slice to absorb the residue would make one number wrong to make a total
right, which is worse.

---

## Pass D — boundary and adversarial inputs

### Finding D3 — plant identifier collisions **(mine, most serious)**

`plant._seq` computed `int(sha256(...)[:6], 16) % 10000` — a **four-digit space,
10,000 slots**. Measured across the modelled footprint:

| Site | Taps | Duplicate identifiers | Rate |
|---|---|---|---|
| San Juan | 8,709 | 2,929 | **33.6%** |
| Ponce | 5,497 | 1,225 | 22.3% |
| Bayamón | 4,711 | 946 | 20.1% |
| Arecibo | 3,491 | 572 | 16.4% |

By the birthday bound, a 50% chance of one collision arrives at about **118
elements**. This was reachable at any realistic scale.

The consequence is operational, not cosmetic. `TAP-SJU-4C00117` was not unique, so
a work order or an MR could name the wrong plant element — and the whole point of
the delimiter is that it identifies exactly which piece of plant a crew is being
sent to.

Fixed. Uniqueness now comes from the index, which is injective by construction,
with a two-character site-and-kind hash retained as a prefix so the identifier
still reads as plant rather than a counter. Verified: zero collisions across every
site and both technologies at full modelled scale, 20,000 identifiers distinct for
one site, still byte-identical across a fresh process, and distinct across sites at
the same index. Five tests added.

The nine scenario fixtures carried the old identifiers and were regenerated. The
drift guard written in v1.4.0 caught that immediately, which is the one part of
this episode that worked as intended.

### Other boundary probes

The full-SHA-256 idempotency key showed **no collisions across 8,100 inputs**. Keys
survive an empty incident id, unicode delimiters, a 10,000-character id and an
attempt index of 10⁹, and reject a negative index. Confidence above 1.0, below 0,
a threshold of 0 and a threshold above 1 all behave sensibly. One fault works, zero
faults is rejected, seed 0 works. Retrieval on an empty query and `k=0` return
empty rather than raising.

**Five probes in D1 initially failed** because I called a keyword-only function
positionally. My error, not the code's.

---

## Pass E — metric soundness

The A/B metrics were checked for the double-counting that would flatter retrieval.
A case that is both gated *and* rules-wrong counts as a catch, not a false alarm,
and costs nothing — correct on all four measures. `dissent_precision` reads 1.0
where `gate_precision` reads 0.5 on the same data, confirming that reporting only
the former would hide a false alarm. A wasted visit is priced per-dispatch, not
per-completed, so repeat visits are not double counted.

### Finding E4 — a configured ceiling that was never enforced **(pre-existing)**

`Settings.max_remote_attempts` was declared, defaulted to 2, and set explicitly in
`tests/conftest.py`. **No code read it.** `_failure_review` enforced
`max_field_visits` and `max_mr_attempts` and skipped remote attempts, so remote
retries were bounded only by the global `graph_max_steps`. A scenario could re-run
a remote action far past its configured ceiling.

Fixed: enforced alongside the other two, escalating with "Remote attempt budget
exhausted".

This is the second unenforced guard found across two audits — `writes_permitted`
was the first. Both read as controls and were not. Worth a standing check: a
setting that no code reads is a claim, not a control.

### Observation E5 — caveats a scanner could not find

Two blocks caveated themselves as "stated positions, not measurements" and
"illustrative". Honest, but invisible to a keyword check, so no test could enforce
it. Both now say ASSUMED explicitly, and a test asserts every non-computed block
carries a machine-detectable caveat.

---

## What remains open

Unchanged from the v1.12.1 audit and still true:

1. The Docker build has never completed in this environment.
2. Eight of nine Streamlit pages have never rendered. Three defects have been
   found by you rendering; each is now guarded.
3. OSRM has never contacted a live server.
4. Sixteen of 43 modules are reachable by the runnable suite; the workflow engine
   is covered only by six test modules that need pytest. **The `max_remote_attempts`
   fix lands in exactly that untested region** — it is statically correct and
   unexercised. `make test-integration` is the way to confirm it.
5. Both themes inject CSS and the later wins. Fragile, works.
6. Retrieval recall of 1.0 comes from 18 cases I wrote.

## Standing checks worth keeping

- A setting no code reads is a claim, not a control. Grep for unread settings.
- A synthetic identifier must be unique at the scale it will be generated at.
  Check the birthday bound, not a sample.
- An exception handler that discards the exception makes two different failures
  look the same.
- A caveat a scanner cannot find cannot be enforced by a test.
