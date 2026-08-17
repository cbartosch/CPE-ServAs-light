# Measuring what the model and retrieval actually buy you

## The question

"How do I see the advantage of using an LLM with RAG on top?"

Through v1.2 the answer was: **you couldn't**, for three reasons that were
properties of the design rather than bugs.

1. **The model cannot change any outcome.** `WorkflowEngine._fusion` always sets
   `approved_rca = deterministic`. The model can lower the fused confidence, via
   `min(deterministic, model)`, and it can force a human review by naming a
   different domain. It can never set the domain, choose the action or dispatch a
   crew. So running with and without it produces identical dispatches, and there
   is no accuracy delta to measure.
2. **There was no retrieval.** No embeddings, no vector store, no retriever, no
   knowledge base. The MCP tool registry contained only execution tools.
3. **The model was a scripted fake.** `MODEL_PROVIDER=fake` is the default, and
   when a scenario supplies no explicit `llm_rca` the fake derives its proposal
   from `deterministic_rca`. The "model" was the rules engine wearing a hat.

The demo therefore demonstrated **governance** — that a dissenting model cannot
route past a human — and nothing about model value. That is worth showing to a
risk audience and worthless to someone asking why they should pay for an LLM.

## The reframe

The measurable claim is not accuracy. It is **dissent quality**: when the rules
are confidently wrong, does the model force someone to look, and how often does
it cry wolf?

That needs ground truth, which the fixtures did not carry. v1.3 adds:

- `true_domain` on each workflow fixture, derived from that scenario's own
  `expected_outcome` and action sequence. `bounded_remote_failure` is left
  `null`: it escalates without ever resolving, so no true domain is knowable and
  inventing one would corrupt the measurement.
- `src/lpr_cpe_demo/kb/benchmark.json` — 18 RCA cases carrying an evidence
  signature, the deterministic classifier's result, and the domain that turned
  out to be true. Four of the eighteen are cases where the rules are wrong.

## Scope, stated plainly

The harness measures **the fusion and gating decision only**, not the whole
workflow. It calls the same `controls.fuse_and_gate` the engine calls, so the
rule under test is the shipped one rather than a reimplementation. It does not
exercise dispatch, execution, verification or closure.

## Metrics

| Metric | Definition | Why it matters |
|---|---|---|
| `gate.prec` | Of **all** gates raised, the share where the rules were in fact wrong | The number an operations manager cares about: how often being interrupted was justified |
| `dis.prec` | Of gates raised **by disagreement only**, the share where the rules were wrong | Narrower and more flattering; it hides low-confidence false alarms |
| `dis.rec` | Of cases where the rules were wrong, the share caught by any gate | Low recall means the gate is false comfort |
| `avoided` | Rules wrong, wrong domain implies a different crew, gate raised | Each one is a wasted visit not taken |
| `missed` | Same, but no gate raised | Each one is a wasted visit taken |
| `gates/100` | Gates raised per hundred incidents | The counterweight. An arm that gates everything scores perfect recall and is worthless |
| `model.acc` | Model domain versus true domain | Diagnostic only. It says how good a dissent signal the arm could be, not what was dispatched |
| `cite.valid` | Share of cited references resolving to a real retrieved document | Reported as `n/a` without real retrieval, because a scripted model's citations are meaningless |

Read `gate.prec` and `gates/100` together. Either alone can be gamed.

## Results

```
PYTHONPATH=src python3 scripts/run_ab_matrix.py --detail
```

18 benchmark cases, confidence threshold 0.70, four cases where the rules are wrong:

| arm | gates | gates/100 | gate.prec | false | dis.rec | avoided | missed | model.acc | cite.valid |
|---|---|---|---|---|---|---|---|---|---|
| `deterministic` | 0 | 0.0 | n/a | 0 | 0.0 | 0 | 4 | n/a | n/a |
| `plus_scripted_model` | 0 | 0.0 | n/a | 0 | 0.0 | 0 | 4 | 0.778 | n/a |
| `plus_retrieval` | 7 | 38.9 | 0.571 | 3 | 1.0 | 4 | 0 | 0.889 | 1.0 |

### What this says

**The shipped default adds nothing measurable.** `plus_scripted_model` is
identical to `deterministic` on every operational metric: zero gates, four missed
misdispatches. Because the fake echoes the rules, it cannot disagree, so the
disagreement gate never fires. Anyone demonstrating v1.2 with `MODEL_PROVIDER=fake`
and claiming the model is contributing is mistaken. `tests/test_retrieval_ab.py`
locks this in — if a future change gives the fake an independent opinion, the
test fails and this document must be revisited.

**Retrieval catches every rules error, and it is not free.** Four of four caught,
four misdispatches avoided, zero missed. The cost is three unnecessary
interruptions across eighteen cases: `gate.prec` is 0.571, so **roughly two in
five gates were justified**. On a real queue that tradeoff needs a decision, not
a slide.

**Where retrieval failed.** Cases B-01 and B-10 voted `cpe` where the truth was
`provisioning`; those two domains are lexically close in the knowledge base and
BM25 cannot separate them. B-14 gated on low confidence despite agreeing
correctly. These are honest weaknesses of lexical retrieval at this corpus size,
and they are exactly what the false-alarm column is for.

**Citation validity is 1.0 but only just became meaningful.** Every cited id
resolves because the ids come from real retrieved documents. Under the scripted
model it was reported as `n/a` rather than 1.0, because fabricated references
that happen to name real evidence prove nothing.

## Why BM25 rather than embeddings

Deliberate, and reversible:

- it runs on the standard library, so the retrieval layer is unit testable
  offline and in the same container as the rest of the core;
- at tens of documents, lexical retrieval is competitive with dense retrieval,
  and fault signatures are strongly lexical — "codeword errors", "optical Rx",
  "ingress", "LOS";
- swapping in embeddings means replacing `BM25Index` and keeping the `search()`
  signature. Nothing above `retrieval.py` changes.

If you move to embeddings, re-run this harness before and after. The point of
v1.3 is that the claim becomes a number someone can argue with.

## Guarding against a rigged benchmark

Three tests exist specifically to stop the measurement flattering itself:

- `test_benchmark_signatures_are_not_copied_from_the_kb` — verbatim reuse would
  let retrieval memorise rather than generalise;
- `test_corpus_contains_correct_hard_boundary_cases` — without `drop` cases the
  rules get right, an arm that always dissents would score perfectly;
- `test_retrieval_advantage_is_not_free` — asserts interruption cost above zero
  and `gate.prec` below 1.0, because zero false alarms across a realistic corpus
  is a sign the corpus is wrong.

## What is still not measured

- End-to-end outcomes. Truck rolls, MTTR and first-time-fix would need the full
  engine, a database and simulated field results.
- Real provider behaviour. Every number here comes from BM25 over a fixed corpus.
  A hosted model will have different, and more variable, dissent characteristics.
- Human response. The harness counts gates raised, not whether the operator
  agreed with them. Precision measured against ground truth is an upper bound on
  the value an operator actually realises.
