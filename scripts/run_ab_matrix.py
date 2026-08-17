#!/usr/bin/env python3
"""Run the RCA-gate A/B matrix across three arms.

    PYTHONPATH=src python3 scripts/run_ab_matrix.py
    PYTHONPATH=src python3 scripts/run_ab_matrix.py --json out.json --detail

Arms
    deterministic          rules only. No model, so only the confidence
                           threshold can raise a gate.
    plus_scripted_model    rules plus a scripted model proposal, which is what
                           the demo ships with MODEL_PROVIDER=fake. The proposal
                           echoes the rules with a small confidence haircut.
    plus_retrieval         rules plus a proposal derived from BM25 retrieval over
                           the prior-case knowledge base. The domain comes from a
                           score-weighted vote of retrieved neighbours, and the
                           cited references are the retrieved document ids.

Scope: this measures the fusion and gating decision only, not the full
workflow. It uses the same `controls.fuse_and_gate` the engine calls, so the
rule under test is the shipped one, not a reimplementation.

Runs with the standard library alone: no pydantic, no LangGraph, no database.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpr_cpe_demo.ab_metrics import ArmReport, CaseResult, format_table  # noqa: E402
from lpr_cpe_demo.controls import GATE_HUMAN_REVIEW, fuse_and_gate  # noqa: E402
from lpr_cpe_demo.effort import assumptions, cost_arm  # noqa: E402
from lpr_cpe_demo.retrieval import build_index, vote_domain  # noqa: E402

KB = ROOT / "src/lpr_cpe_demo/kb/prior_cases.json"
BENCH = ROOT / "src/lpr_cpe_demo/kb/benchmark.json"
THRESHOLD = 0.70

# The scripted fake shipped in llm/service.py echoes the deterministic domain
# with a small confidence haircut when no explicit llm_rca is supplied. Modelled
# here so the middle arm reflects what the demo actually does today.
SCRIPTED_HAIRCUT = 0.02


def load_cases() -> list[dict]:
    return json.loads(BENCH.read_text(encoding="utf-8"))["cases"]


def arm_deterministic(cases: list[dict]) -> ArmReport:
    report = ArmReport("deterministic")
    for case in cases:
        det = case["deterministic"]
        outcome = fuse_and_gate(deterministic_domain=det["domain"],
                                deterministic_confidence=det["confidence"],
                                threshold=THRESHOLD)
        report.cases.append(CaseResult(
            case_id=case["case_id"], deterministic_domain=det["domain"],
            true_domain=case["true_domain"], site_id=case.get("site_id", ""),
            gate_raised=outcome.route == GATE_HUMAN_REVIEW,
            gate_reason=outcome.gate_reason))
    return report


def arm_scripted(cases: list[dict]) -> ArmReport:
    report = ArmReport("plus_scripted_model")
    for case in cases:
        det = case["deterministic"]
        model_domain = det["domain"]                      # echoes the rules
        model_conf = max(0.0, det["confidence"] - SCRIPTED_HAIRCUT)
        outcome = fuse_and_gate(deterministic_domain=det["domain"],
                                deterministic_confidence=det["confidence"],
                                model_domain=model_domain,
                                model_confidence=model_conf,
                                threshold=THRESHOLD)
        report.cases.append(CaseResult(
            case_id=case["case_id"], deterministic_domain=det["domain"],
            true_domain=case["true_domain"], site_id=case.get("site_id", ""),
            gate_raised=outcome.route == GATE_HUMAN_REVIEW,
            gate_reason=outcome.gate_reason,
            model_domain=model_domain,
            model_correct=model_domain == case["true_domain"]))
    return report


def arm_retrieval(cases: list[dict], *, k: int = 5) -> ArmReport:
    index = build_index(KB)
    known = {doc.doc_id for doc in index.docs}
    report = ArmReport("plus_retrieval")
    for case in cases:
        det = case["deterministic"]
        hits = index.search(case["signature"], k=k, technology=case["technology"])
        vote = vote_domain(hits)
        model_domain = vote.domain or det["domain"]
        model_conf = vote.confidence if vote.domain else det["confidence"]
        outcome = fuse_and_gate(deterministic_domain=det["domain"],
                                deterministic_confidence=det["confidence"],
                                model_domain=model_domain,
                                model_confidence=model_conf,
                                threshold=THRESHOLD)
        cited = tuple(h.doc_id for h in hits)
        report.cases.append(CaseResult(
            case_id=case["case_id"], deterministic_domain=det["domain"],
            true_domain=case["true_domain"], site_id=case.get("site_id", ""),
            gate_raised=outcome.route == GATE_HUMAN_REVIEW,
            gate_reason=outcome.gate_reason,
            model_domain=model_domain,
            model_correct=model_domain == case["true_domain"],
            cited_refs=cited,
            valid_refs=tuple(r for r in cited if r in known)))
    return report


def detail(report: ArmReport) -> str:
    lines = [f"\n  {report.arm}"]
    for c in report.cases:
        marks = []
        if c.rules_wrong:
            marks.append("RULES-WRONG")
        if c.gate_raised:
            marks.append(f"gate:{c.gate_reason}")
        if c.rules_wrong and c.crew_would_differ:
            marks.append("crew-differs")
        verdict = "caught" if (c.rules_wrong and c.gate_raised) else \
                  "MISSED" if c.rules_wrong else \
                  "false-alarm" if c.gate_reason == "domain_disagreement" else "ok"
        lines.append(f"    {c.case_id}  det={c.deterministic_domain:15s} "
                     f"model={str(c.model_domain):15s} true={c.true_domain:15s} "
                     f"{verdict:12s} {' '.join(marks)}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", metavar="PATH", help="write the full result as JSON")
    ap.add_argument("--detail", action="store_true", help="per-case breakdown")
    ap.add_argument("-k", type=int, default=5, help="retrieved neighbours (default 5)")
    args = ap.parse_args()

    cases = load_cases()
    reports = [arm_deterministic(cases), arm_scripted(cases), arm_retrieval(cases, k=args.k)]

    print(f"RCA gate A/B matrix — {len(cases)} benchmark cases, "
          f"confidence threshold {THRESHOLD}\n")
    print(format_table(reports))
    if args.detail:
        for r in reports:
            print(detail(r))

    # ------------------------------------------------------------ cost of errors
    costs = [cost_arm(r.arm, r.cost_cases()) for r in reports]
    baseline = max(c.total_cost for c in costs)
    print("\nCost of getting the gate wrong")
    print(f"{'arm':20s} {'FP':>3} {'FN':>3} {'FP min':>7} {'FP $':>9} "
          f"{'FN min':>7} {'FN $':>10} {'total min':>10} {'total $':>10} {'vs worst':>9}")
    print("-" * 104)
    for c in costs:
        saved = baseline - c.total_cost
        print(f"{c.arm:20s} {c.false_positives:>3} {c.false_negatives:>3} "
              f"{c.fp_minutes:>7} {c.fp_cost:>9.2f} {c.fn_minutes:>7} {c.fn_cost:>10.2f} "
              f"{c.total_minutes:>10} {c.total_cost:>10.2f} "
              f"{('-' if saved == 0 else f'-{saved:,.0f}'):>9}")
    print("\n  FP = a gate fired and the rules were right: an L2 review and a delay.")
    print("  FN = the rules were wrong, nothing gated, and the wrong crew went out.")
    print("  Only the avoidable portion of an FN is counted: the wasted visit plus")
    print("  the handover. The correct visit still has to happen either way.")
    print(f"  All rates are assumed. {assumptions()['basis']}.")

    print("\nReading the table")
    print("  The approved domain is always the deterministic one, so model.acc is")
    print("  diagnostic only: it says how good a dissent signal the arm could be,")
    print("  not what was dispatched. dis.prec and gates/100 must be read together.")

    if args.json:
        payload = {"threshold": THRESHOLD, "cases": len(cases),
                   "arms": [r.as_row() for r in reports],
                   "error_cost": [dataclasses.asdict(c)
                                  | {"total_minutes": c.total_minutes,
                                     "total_cost": c.total_cost}
                                  for c in costs],
                   "cost_assumptions": assumptions(),
                   "detail": {r.arm: [dataclasses.asdict(c)
                                      | {"rules_wrong": c.rules_wrong,
                                         "crew_would_differ": c.crew_would_differ}
                                      for c in r.cases] for r in reports}}
        pathlib.Path(args.json).write_text(json.dumps(payload, indent=2, default=list) + "\n")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
