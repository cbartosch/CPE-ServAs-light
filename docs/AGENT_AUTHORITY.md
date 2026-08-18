# Agents decide, rules check

## The inversion

Until v1.16.0 the deterministic classifier set `approved_rca` and the model could
only lower confidence or force a gate. The operator has chosen the opposite: the
agent decides, and policy and the approval gates are the only guard.

The rules did not go away. They changed job, from deciding to checking, and they
now do three things:

1. **Baseline.** Every `AgentDecision` carries the deterministic answer, and
   `agrees_with_baseline` is what the RCA gate reads. Disagreement routes to a
   human, exactly as before, with the roles swapped.
2. **Fallback.** An unreachable provider, unparsable output, an unknown domain or
   a confidence outside 0 to 1 all fall back to the rules rather than stalling the
   incident. `source` records which happened.
3. **Floor.** The agent cannot be worse than the rules on an incident where it
   fails, because on that incident it *is* the rules.

## What the inversion actually changed

Measured on the 18-case benchmark, retrieval standing in for the agent:

| | |
|---|---|
| Deterministic correct | 14 / 18 |
| **Agent correct** | **16 / 18** |
| They disagree | 6 cases, all gated |
| When they disagree: agent right | 4 |
| When they disagree: rules right | 2 |
| Agent wrong **and** rules agree, so nothing gates | **0** |

Two things follow.

**Accuracy is now a real outcome.** Under the old arrangement the approved domain
was always deterministic, so accuracy was identical across arms by construction —
which is why the old measurement had to be about dissent quality instead. Now the
agent's answer is the answer, and 16 of 18 is a number about the system rather
than about the harness.

**The gate load is 33%.** Six of eighteen incidents reach a human on disagreement
alone, at about $19.67 each in review time. That is the price of the arrangement.
It is cheap against a misdispatch at $354 to $1,071, but it is not free and it
scales with volume.

## The new exposure, and why it is the one to watch

The old failure mode was the rules being confidently wrong with nothing to catch
them. The new one is different: **the agent wrong and the rules agreeing with it**,
because then nothing gates and the wrong crew is dispatched unreviewed.

On this benchmark that count is zero. That is a small sample and should not be
read as a property. It is the number to track, and it is the reason the rules must
keep running even though they no longer decide: delete them and this failure mode
becomes silent.

## Policy is now load-bearing

`_policy` previously checked that an action existed and that evidence existed.
That was adequate while a deterministic ranker chose the action, because it could
only ever choose a sane one. With an agent choosing, `agents/guards.py` blocks
five things a schema-valid decision could otherwise do:

- a remote action against a physical fault, which interrupts a customer and
  repairs nothing
- a clean-boots visit to a plant fault affecting hundreds of households
- an attempt past the remote or field budget
- a dispatch to a base lacking the required skill or part
- any action with no evidence behind it

`BLOCKED` beats `REQUIRES_APPROVAL`, so a human cannot approve something that must
never happen. Everything merely consequential asks for approval instead, because a
human refusing is cheap and a wrongly blocked incident is not.

## What has not been executed

No live provider call has been made from this environment: it has no network. The
seam is exercised against canned responses covering 4xx without retry, 5xx with
retry, transport failure, missing text block, unparsable output, schema violation
and provider absence. Set `ANTHROPIC_API_KEY` to switch from the fake; the default
stays fake so a missing key degrades to a working demo rather than a stack trace.
