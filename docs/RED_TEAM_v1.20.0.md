# Red team — where the workflow breaks

**Approach:** adversarial. Not "is this tidy" but "can I make it do something
harmful". Every attack below was executed against the running code.
**Result:** 6 findings. 4 were live breaks and are fixed. 2 are design weaknesses
recorded rather than fixed, with the reasoning.
**Position:** all six are against my own work.

---

## Broken and fixed

### 1. The guard did not validate its own domain — CRITICAL

```
ActionRequest(domain="totally_made_up", action="remote_reboot",
              agent_agrees_with_baseline=True, agent_confidence=0.99)
  -> ALLOWED
```

An unrecognised domain is not in `PHYSICAL_DOMAINS`, so the rule forbidding a
remote action against physical plant **could not fire**, and the request reached
`allowed` — meaning execution with no human.

`guards.evaluate` is the only guard in a design where agents decide. It trusted its
caller to supply a valid domain. A guard that assumes clean input is not a guard.

Not reachable through the agent layer today, because `decisions.py` validates the
domain against `DOMAINS` first. That is defence in depth working by luck rather than
by design: the second layer was load-bearing and empty.

**Fixed.** `KNOWN_DOMAINS` and `KNOWN_ACTIONS` are validated before any other rule,
and validation returns immediately so a bad domain never reaches `blast_radius`,
which would otherwise guess at it. A test asserts every domain and action the agents
can emit is recognised, so the fix cannot block legitimate traffic.

### 2. The thing being guarded supplied its own ceiling — CRITICAL

```
ActionRequest(remote_attempts=99, max_remote_attempts=1000)  -> ALLOWED
ActionRequest(remote_attempts=-5)                            -> ALLOWED
```

Budgets arrived **inside the request**. A caller could raise its own limit, or send
a negative count and pass every comparison.

**Fixed.** `HARD_MAX_REMOTE_ATTEMPTS` and `HARD_MAX_FIELD_VISITS` live in the guard.
The effective ceiling is `min(requested, hard)`, so a caller may **tighten** a
budget — which is safe and useful — and can never loosen one. Negative counts are
blocked outright.

### 3. Skills and parts were only checked if the caller declared them — HIGH

```
ActionRequest(domain="pon_odp", action="dirty_boots_mr",
              base_id="BASE-CAR", required_parts=())   -> requires_approval
```

BASE-CAR carries no splice kit. A `pon_odp` fault always needs one, so a caller that
simply omitted `required_parts` got a dispatch approved to a crew that would arrive
unable to work. The check could be evaded by forgetting it.

**Fixed.** `IMPLIED_SKILLS` and `IMPLIED_PARTS` derive the requirement from the
domain and union it with whatever the caller declared. Omission no longer weakens
the check.

### 4. A valid approval token authorised any action — CRITICAL

`verify_approval_token` returns `incident_id`, `action_type` and `idempotency_key`.
**No caller compared them to the action being performed.** A grep for any such
comparison returned nothing.

So a token legitimately issued for `INC-A` / `clean_boots` would verify while
`dirty_boots_mr` was performed on `INC-B`. Signature verification answers *was this
issued by us*. It does not answer *was this issued for what I am about to do*, and
only the second question stops a crew arriving to do something nobody approved.

The effect store limits the damage to one action per approval, but does not prevent
the substitution.

**Fixed.** `verify_approval_for(token, secret, incident_id=..., action_type=...,
idempotency_key=...)` raises `ApprovalMismatch` on any divergence.
`ApprovalMismatch` subclasses `ApprovalTokenError`, so an existing caller catching
the base class does not miss it.

### 5. An injected suppression erased the dispatch and the notification — HIGH

A prompt-injected `suppress` on a **critical, already-breached** ticket returned
from `process` *before* `evaluate_policy` was reached:

```
before:  verdict=requires_approval  needs_truck_roll=False  notify=()
```

The ticket still reached a human, so no action was silently taken. But the
suppression cleared `needs_truck_roll` and every notification reason — including the
customer notification the un-suppressed path would have produced. An attacker who
could influence the evidence text could not cause a wrong action, but could cause a
customer not to be told.

**Fixed.** Suppression is refused outright when a threshold has already been
crossed, returning `blocked` with the breached measurement named, and
`needs_truck_roll` preserved. A forecast with no breach can still legitimately be
dismissed as noise, and still goes to a human.

---

## Held under attack

The effect store took the heaviest attack and did not move:

- a replayed key does not overwrite the first effect
- one approval cannot authorise a second action
- an approval cannot be reused on another incident
- **20 concurrent commits of one approval produced exactly 1 effect and 19 refusals**

`BLOCKED` still beats `REQUIRES_APPROVAL`, so a human cannot approve something that
must never happen. `manual_review` and `monitor` reaching `allowed` is correct: they
touch nothing.

---

## Recorded, not fixed

### 6. The merge rule lets a case be born already breached

The operator chose that a predictive ticket stays parent and the SLA runs from when
the scan opened it. A customer calling a month later therefore inherits an SLA that
expired weeks ago:

```
customer calls next day       spent   24.0h   breached=False
customer calls a month later  spent  720.0h   breached=True
```

The case can never be met, so the metric is meaningless for it, and nothing
re-baselines or escalates beyond a boolean.

**Not fixed, because the rule was chosen deliberately** and I was asked not to make
assumptions. `sla_breached_at_attach` and `hours_of_clock_already_spent` are already
surfaced. What is missing is a policy decision: does a stale predictive parent
expire, and after how long? That is a question, not a bug.

### 7. `attach_customer_call` has no registry

It is a pure function, so nothing prevents one reactive incident being attached to
several predictive parents. Enforcing uniqueness needs a store the branch does not
have, and inventing one would duplicate state the main engine already owns through
`parent_incident_id`. The correct fix is to enforce it in the engine at merge time,
which is in the untestable region, so it is recorded rather than half-built.

---

## What the exercise says about the design

The four live breaks share one shape: **a check that trusted its caller.** The
guard trusted the domain, the budget, the declared parts; the token verifier trusted
that someone downstream would compare the claims. Each was one layer deep, and each
looked correct in isolation.

That is the failure mode to expect from here, because the operator's choice to let
agents decide moved the load onto exactly these checks. A guard reached only through
a validating caller is not a second layer; it is the same layer twice.

## Standing checks, updated

- A setting no code reads is a claim, not a control.
- A module no application code imports is a claim, not a capability.
- A synthetic identifier must be unique at the scale it will be generated at.
- An exception handler that discards the exception makes two failures look alike.
- A caveat a scanner cannot find cannot be enforced by a test.
- **New: a guard that trusts its caller is not a guard. Validate inputs at the
  boundary that enforces, not only at the boundary that produces.**
- **New: a token that says what it authorises must be compared to what is being
  done. Signature verification alone answers the wrong question.**
