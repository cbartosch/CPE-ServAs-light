# Audit — v1.23.1

**Scope:** the commercial layer and the dispatch rule, plus the seven standing checks
accumulated across four previous audits.
**Result:** 5 findings, all against my own work. One of them is a **retraction of a
previous finding**.

---

## 1. RETRACTION: the v1.20.0 confused-deputy finding was wrong

The red-team report claimed:

> `verify_approval_token` returns `incident_id`, `action_type` and
> `idempotency_key`. **No caller compared them to the action being performed.**

**That was false.** `mcp_server/tools.py` already compared all of it:

```python
if claims.get("incident_id") != incident_id:  raise ToolRejection("APPROVAL_INCIDENT_MISMATCH")
if claims.get("action_type") != action_type:  raise ToolRejection("APPROVAL_ACTION_MISMATCH")
if claims.get("status") != "approved":        raise ToolRejection("APPROVAL_NOT_GRANTED")
consumed = self.store.get_consumed_approval(approval_id)
if consumed is not None and consumed != idempotency_key: raise ToolRejection("APPROVAL_ALREADY_CONSUMED")
```

My grep looked for `claims[...idempotency_key...]` and missed
`claims.get("incident_id") != incident_id`. **I reported a critical security break
that did not exist, and shipped a fix for a closed hole.**

`verify_approval_for` is retained and is now wired in, because consolidating four
inline comparisons into one reusable call is worth doing and it adds one comparison
the inline version lacked — the idempotency key itself. But it is a refactor, not a
fix. The `status` check was added to it before wiring, because a consolidation that
quietly dropped a check would be worse than the duplication it replaced.

**The lesson is about method, not about this bug.** A negative grep is not evidence
of absence, and I used one to make the strongest claim in that report.

---

## 2. The recommended dispatch rule was unreachable — third occurrence

`schedule_day`, `build_jobs`, `crew_hours`, `aged_value_at_risk`,
`deadline_hours_for` and `rule_description` had **zero application references**. I
recommended a rule, measured it at 2.2× the incumbent, and the running system kept
using the incumbent.

Three occurrences now:

| version | what shipped unwired |
|---|---|
| 1.11.0 | a router the simulator page never invoked |
| 1.16.0 | five agent modules the engine never called |
| 1.23.0 | a dispatch rule nothing called |

**And the v1.12.1 audit ran exactly the right check as a throwaway script.** It found
four orphans and was never committed. After the second occurrence I added a standing
check *and* a test — but the test was written for agents specifically, so it did not
generalise and the third occurrence went undetected.

The lesson is not "check reachability". It is that **a guard written for one instance
of a class of bug does not guard the class.**

`tests/test_reachability.py` now checks every public symbol in `src/` against
application code, with an allowlist where each exemption states its reason. It found
18 orphans on first run, including four the previous audits had already flagged and
nobody had removed.

**Also still unwired, and now fixed:** `recommendation_agent`, `route_agent` and
`route_options`. v1.16.1 wired only `triage_agent` and I reported the agent layer as
addressed. Three of four agents were still unreachable. All three now run in
`predictive.pipeline.process`, each returning a best and a second-best.
`rca_agent` remains exempted with a reason: it belongs in `WorkflowEngine`, which
needs pydantic and cannot be exercised here, and wiring it untested would repeat the
mistake in a different shape.

---

## 3. The deadline conversion broke the medical protection

Converting every protection to a deadline weakened the ones that matter most.
Measured:

| | score |
|---|---|
| Fresh medical case, island ODP | **139** |
| Routine metro job, 71 hours old | **1,174** |

The routine job wins by 8.4×, because it has more accumulated urgency and a fraction
of the crew-hours. **The medical protection is meant to be a floor and was not one.**

Fixed with two precedence tiers rather than one. `ABSOLUTE_PRECEDENCE` contains only
medical-or-safety and already-breached SLA — about 5% of arrivals, against 23% for
all protections, so it cannot starve the queue the way all-protections-first did.
Lifeline, vulnerability and repeat-unresolved stay as deadlines, because "within 24
hours" is a genuine and sufficient commitment for those.

Verified: the medical case is now scheduled first despite scoring 13× lower.

---

## 4. The value model trusted a CRM extract

Standing check 6, against a feed marked MODELLED, so bad data is likely rather than
hypothetical.

| input | before |
|---|---|
| `monthly_recurring_revenue = -5000` | value at risk **−$10,395** |
| `monthly_recurring_revenue = 1e9` | value at risk **$2.07bn** |
| negative tenure, negative contract months, negative households | all accepted |

A negative value at risk sorts to the bottom of every queue, so one bad extract row
**silently deprioritises that customer forever**. An absurd row dominates every
queue. Neither raised anything.

Fixed: `CustomerRecord.__post_init__` validates at the boundary and raises
`CustomerDataError`, with a plausible ceiling on revenue.

---

## 5. The fairness measurement measured the wrong rule

`disparate_impact` accepts `RankedDispatch`, which comes from `rank()` — the
per-visit rule. `schedule_day` returns `DaySchedule`, which it cannot accept. **The
island-skew figures I quoted while recommending the density rule were measured on the
rule it replaces.**

Fixed: `schedule_disparate_impact` measures the schedule the rule actually produces,
and reports worst-wait per archetype, which is the fairness measure, alongside
`overdue_deferred`, which is a capacity signal rather than a prioritisation one.

---

## What passed

- **Exception handlers** in the new code: none discards its exception.
- **Assumed constants**: `commercial.assumptions()` exposes eight groups with a
  basis that says ASSUMED.
- **Synthetic identifiers**: the commercial layer generates none.
- **Dead code**: `tile_layer` and `fault_route_records`, flagged in v1.12.1 and never
  removed, are now gone along with the tests that only covered them.

## Standing checks

Unchanged, plus one:

- A setting no code reads is a claim, not a control.
- A module no application code imports is a claim, not a capability.
- A synthetic identifier must be unique at the scale it will be generated at.
- An exception handler that discards the exception makes two failures look alike.
- A caveat a scanner cannot find cannot be enforced by a test.
- A guard that trusts its caller is not a guard.
- A token that says what it authorises must be compared to what is being done.
- **New: a guard written for one instance of a bug does not guard the class. And a
  negative grep is not evidence of absence — verify by reading the caller.**
