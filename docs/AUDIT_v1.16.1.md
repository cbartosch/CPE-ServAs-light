# Audit — v1.16.1

**Scope:** the twelve modules and roughly 120 tests added since the last audit —
the HTML report, the travel fix, the predictive branch and the agent layer.
**Method:** the four standing checks the previous audit left behind, plus a
reachability pass. Everything was executed.
**Position:** a self-audit. All six findings are against my own work.

---

## Finding 1 — the agent layer was unreachable. **This is the serious one.**

v1.16.0 shipped five modules and 55 tests. The running system called **none of
them**.

```
rca_agent                0 app references   3 test references
recommendation_agent     0                  5
route_agent              0                  3
triage_agent             0                  2
provider_from_env        0                  4
ActionRequest            0                  2
```

`WorkflowEngine` still sets `approved_rca = deterministic` at line 330 and imports
nothing from `agents`. The predictive pipeline had its own gate logic and did not
import the agents either.

So the v1.16.0 claim — *agents decide, rules check* — was true of the modules I
wrote and false of the system. I reported a governance inversion that had not
happened.

**This is the second occurrence.** v1.11.0 shipped a router the simulator page
never invoked. I wrote the lesson down at the time: *a feature tested in isolation
and never called from the page is indistinguishable from a feature that does not
exist.* Four versions later I repeated it at ten times the scale, and 55 passing
tests gave no signal, because every one of them constructed its own agent.

**Fixed.** The triage agent and the policy guard are wired into
`predictive/pipeline.process`, which is standard library and therefore testable
here. `test_a_decision_agent_is_constructed_somewhere_in_the_application` now
scans application sources outside the `agents` package and fails if none
constructs an agent. Verified by reverting the wiring and watching it fail.

**Still open:** `WorkflowEngine` is unwired. It needs pydantic, so wiring it here
would produce untested code in an untestable module — the same mistake in a
different shape. It is listed under open items rather than done.

---

## Finding 2 — the predictive branch could not refuse anything

`Verdict` declared `"blocked"` and **no code path returned it**. The only
occurrence was the type alias on line 32. Every unsafe predictive action could
therefore be approved by a human, never refused outright — in a branch that
deliberately bypasses the main engine's gate-everything policy.

**Fixed.** The pipeline consults `guards.evaluate` before a truck roll and returns
`blocked` with reasons. `test_a_blocked_verdict_is_now_reachable` covers it.

---

## Finding 3 — two provider switches that disagreed

`MODEL_PROVIDER` governed the RCA assistant, `LLM_PROVIDER` governed the agents.
`MODEL_PROVIDER=fake` with a key present sent the assistant to the fake and the
agents **live**. A demo intended to stay offline would have made real API calls.

**Fixed.** Either switch set to `fake` now forces the fake for both. That is the
safe direction. `.env.example` documents both.

---

## Finding 4 — the committed A/B harness measured a configuration the bundle no longer used

`docs/AB_MEASUREMENT.md` was marked superseded, but `scripts/run_ab_matrix.py`
still printed three arms in which the model can never change an outcome. Anyone
running the script got the old answer.

**Fixed.** An `agent_decides` arm was added, and it shows the actual change:

| arm | wrong | gates | gate.prec | model.acc |
|---|---|---|---|---|
| deterministic | 4 | 0 | n/a | n/a |
| plus_scripted_model | 4 | 0 | n/a | 0.778 |
| plus_retrieval | 4 | 7 | 0.571 | 0.889 |
| **agent_decides** | **2** | 7 | 0.286 | 0.889 |

`wrong` falls from 4 to 2 because the approved domain is now the agent's. Gate
precision falls to 0.286 for the same reason: the agent is right more often, so a
larger share of gates are the rules objecting to a correct answer. Both numbers
move for the same underlying reason, and reporting one without the other would
flatter the change.

---

## Finding 5 — a policy threshold with no stated basis

`HIGH_BLAST_RADIUS = 24` governed when any action needs a second pair of eyes, and
carried no justification. Every other assumed parameter in the bundle has a
`basis` string.

**Fixed.** Stated as three times the largest modelled tap, so it clears any single
delimiter and sits below a node, and exposed through `guards.assumptions()`.

---

## Finding 6 — thirteen settings no code reads

Standing check from the previous audit. `anthropic_api_key`, `model_api_key`,
`openai_api_key`, `demo_auth_enabled`, `demo_default_role`, `api_port`, `ui_port`
and six others are declared in `Settings` and read nowhere outside `config.py`.

Most are pre-existing v1.2 fields. **Not fixed**, deliberately: removing settings
the UI or compose may reference by string is a change I cannot verify without
running the stack. Recorded so the next person does not assume they are wired.

---

## What passed

The three remaining standing checks came back clean on the new code.

- **Silent exception handlers.** Four flagged, all four legitimate: a provider
  retry loop that records `last`, and three in `FlagHistory` that fall back to an
  empty structure so a corrupt file cannot stop a scan.
- **Machine-detectable caveats.** `predictive.config.assumptions()` exposes three
  `basis` strings; `guards.assumptions()` now exposes a fourth.
- **Identifier uniqueness.** No new synthetic identifier scheme was introduced.

---

## Open, carried forward

1. **`WorkflowEngine` does not call the agents.** The inversion is real in the
   predictive branch and not in the main flow.
2. Eight of ten Streamlit pages have never rendered.
3. No live provider call has been made; there is no network here.
4. The Docker build has never completed here.
5. Sixteen of 55 modules are reachable by the runnable suite.

## Standing checks, updated

- A setting no code reads is a claim, not a control.
- A synthetic identifier must be unique at the scale it will be generated at.
- An exception handler that discards the exception makes two failures look alike.
- A caveat a scanner cannot find cannot be enforced by a test.
- **New: a module no application code imports is a claim, not a capability. Unit
  tests cannot detect it, because each test supplies its own caller.**
