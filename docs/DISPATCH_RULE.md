# A recommended rule for prioritising truck rolls

## The rule

```
score = aged value at risk  ×  urgency(slack to deadline)  ÷  crew-hours consumed
```

Fill each day's crew-hours in descending score, with **overdue jobs taken first**,
**remote work batched into runs**, and **every protection expressed as a deadline
rather than as a place in the queue**.

That is a value-density scheduling rule with due dates. It is the standard answer to
this shape of problem, and each of the three terms fixes a measured failure in the
simpler "largest gap between value and cost" rule.

## Why not rank by the gap between value and cost

That was the stated goal and it has three problems, all measured on a
household-weighted population of 600 faults.

**The gap is negative almost everywhere.** 78 to 87% of commercially ranked faults
have a negative gap, because a single residential account is worth $20 to $150 at
risk while a visit costs $212 to $654. A difference cannot gate anything when it is
negative for the large majority.

**A visit is the wrong unit of capacity.** A Culebra visit consumes **11 crew-hours**
and a Bayamón visit **2.7**. Ranking per visit treats those as equal claims on the
crew. They are not: one island ticket costs the same crew time as four metro ones.
This is the single largest error in the per-visit rule, and correcting it is where
most of the improvement comes from.

**Protections-first starves the ranking.** 136 of 600 candidates were protected, so a
40-slot day filled with protections alone and no unprotected ticket was ever
scheduled. Lexicographic precedence for a fifth of the queue makes the commercial
ranking decorative.

## What the three terms do

**Divide by crew-hours.** Under a capacity constraint the quantity to maximise is
value per unit of the scarce resource, which makes this a ratio rather than a
difference. Crew-hours come from the same travel model the effort ledger uses:
round trip plus on-site work, and a trip that cannot return within a shift consumes
the whole shift because the crew is unavailable for anything else.

**Turn protections into deadlines.** A medical dependency does not mean "ahead of
everything else forever"; it means "within four hours". Expressed as a deadline it is
elevated by the urgency term as slack shrinks, and it stops consuming the whole day.
The deadlines are the policy dial an operator actually wants: they encode how long
each class may wait, which is a commitment rather than a calculation.

| protection | deadline |
|---|---|
| SLA already breached | 0 h, so immediately overdue |
| Medical or safety dependency | 4 h |
| Total loss of service | 12 h |
| Lifeline obligation | 24 h |
| Vulnerability flag | 24 h |
| Repeat unresolved fault | 36 h |
| everything else | 72 h |

**Age the value.** Churn propensity rises while a fault waits, so value at risk rises
with it, capped at 2.5×. This is what prevents starvation **through the model rather
than through a quota**: a low-value ticket repeatedly deferred rises until it
outranks a high-value one that has just arrived.

**Batch the remote runs.** One Culebra ticket cannot pay for a ferry; a run of four or
more can, at roughly a quarter of the cost each. Remote work is held until a batch
forms or the oldest ticket comes within 18 hours of its deadline. That converts a
structural exclusion into a scheduled cadence, which is what operators actually do.

## Measured against the per-visit rule

Same 600-fault queue, same 110 crew-hours.

| | per-visit gap | value density |
|---|---|---|
| Jobs scheduled | 40 | **50** |
| Crew-hours used | 96.7 | 109.7 |
| Value at risk addressed | $27,372 | **$67,125** |
| **Value per crew-hour** | **$283** | **$612** |
| Overdue left unscheduled | not tracked | **0** |

**2.2× the value per crew-hour**, and it uses the capacity it was given rather than
leaving 13 hours idle because the next job did not fit a slot.

## The fairness result, which is the important one

Over ten simulated days with 60 new faults a day and aging:

| archetype | served | mean wait | **max wait** | still waiting |
|---|---|---|---|---|
| metro | 240 | 1.0 d | **3.0 d** | 84 |
| coastal | 165 | 1.0 d | **3.0 d** | 43 |
| mountain | 44 | 1.3 d | **3.0 d** | 17 |
| remote island | 5 | 2.2 d | **3.0 d** | 2 |

**Nothing starves — provided capacity matches arrivals.** The maximum wait is three
days for every archetype including the islands, because the 72-hour default deadline
binds and the urgency term reaches 12× at that point.

**That precondition is not a footnote.** The run above has 60 arrivals a day against
110 crew-hours, which is roughly balanced. Run the same rule against a fixed backlog
of 600 faults with no arrivals — 1,500 crew-hours of work at 110 a day — and a job
waits **nine days**. That is not the rule starving, it is arithmetic: no priority rule
can hold a deadline under sustained overload. What the rule must do, and does, is
*report* the shortfall: `overdue_deferred` counts overdue work it could not reach, and
that number is the one to take to a resourcing conversation rather than a
prioritisation one.

I claimed the three-day figure before checking the precondition, and a test I wrote
afterwards caught it. Worth stating, because "nothing starves" is exactly the sort of
claim that gets repeated without its condition.

This reconciles something that looks contradictory. In a single day, value density
*does* defer distant work: mountain's share of jobs served falls from 7.5% under the
per-visit rule to 2%. But over ten days everything is served inside three days
regardless of where it is. **The single-day archetype mix is not the fairness
measure; the wait distribution is.** An operator asked whether the rule discriminates
should answer with the second table, not the first.

## Where this rule would still hurt you

- **The deadlines are assumed.** They are the whole fairness guarantee, so they are
  the first thing to agree with operations and, for the Lifeline class, with legal.
- **Churn and collectability are assumed.** They decide whose fault is worth more.
  Replace with LPR retention analytics before anyone quotes a ranking.
- **Batching rarely triggered at this island volume.** Roughly seven island tickets
  arose over ten days, below the batch threshold on most days, so the deadline forced
  the run first. Batching matters at higher island volume or a longer deadline; at
  this volume it is close to inert and should not be claimed as a benefit.
- **Aging assumes a fault stays open.** If a customer churns before the visit, the
  value at risk was never recoverable and the model will have over-ranked it. Feeding
  actual churn events back would correct that, and nothing does today.

## Two things not to do

**Do not use the gap as a go/no-go threshold.** It declines the majority of
residential repairs. `threshold_would_decline()` quantifies it on your own data so
the argument can be had with numbers.

**Do not let payment status deprioritise a repair on its own.** It enters through the
churn probability and the collectability factor, which is defensible: an account in
arrears is likelier to leave and worth less if it stays. Using arrears directly to
push a *fault repair* down the queue is a different act, and the deadline floor is
what keeps this rule on the right side of that line.
