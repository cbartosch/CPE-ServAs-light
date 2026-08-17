"""Metrics for the RCA-gate A/B comparison.

The question this answers is not "is the model more accurate". The model cannot
set the domain, so accuracy is identical across arms by construction. The
question is whether the model is a useful *dissent detector*: when the rules are
confidently wrong, does it force a human to look, and how often does it cry wolf?

Definitions, stated so the numbers cannot be quietly redefined later:

dissent precision
    Of the gates raised by disagreement, the share where the deterministic
    classifier was in fact wrong. Low precision means operators are interrupted
    for nothing and will start rubber-stamping.

dissent recall
    Of the cases where the deterministic classifier was wrong, the share caught
    by any gate. Low recall means the gate is false comfort.

avoided misdispatch
    Cases where the rules were wrong, the wrong domain implies a different crew
    type, and a gate was raised. Each one is a wasted visit not taken.

interruption cost
    Gates raised per hundred incidents. The counterweight to precision: an arm
    that gates everything scores perfect recall and is worthless.

citation validity
    Share of cited evidence references that resolve to a real retrieved
    document. Meaningless unless retrieval is real, which is why the
    no-retrieval arms report None rather than 1.0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

# Which crew a domain sends. Used to decide whether a rules error would have
# produced the wrong crew, which is what makes a misdispatch expensive.
CREW_FOR_DOMAIN = {
    "cpe": "clean", "wifi_or_home": "clean", "premise_wiring": "clean",
    "drop": "clean", "provisioning": "remote", "unknown": "remote",
    "hfc_tap": "dirty", "pon_odp": "dirty", "plant": "dirty",
    "shared_network": "dirty",
}


@dataclass(slots=True)
class CaseResult:
    case_id: str
    deterministic_domain: str
    true_domain: str
    gate_raised: bool
    gate_reason: str
    model_domain: str | None = None
    model_correct: bool | None = None
    cited_refs: tuple[str, ...] = ()
    valid_refs: tuple[str, ...] = ()

    @property
    def rules_wrong(self) -> bool:
        return self.deterministic_domain != self.true_domain

    @property
    def crew_would_differ(self) -> bool:
        return (CREW_FOR_DOMAIN.get(self.deterministic_domain)
                != CREW_FOR_DOMAIN.get(self.true_domain))


@dataclass(slots=True)
class ArmReport:
    arm: str
    cases: list[CaseResult] = field(default_factory=list)

    # -------------------------------------------------------------- counts
    @property
    def n(self) -> int:
        return len(self.cases)

    @property
    def gates(self) -> int:
        return sum(1 for c in self.cases if c.gate_raised)

    @property
    def rules_wrong(self) -> int:
        return sum(1 for c in self.cases if c.rules_wrong)

    # ------------------------------------------------------------- metrics
    @property
    def dissent_precision(self) -> float | None:
        """Restricted to gates raised BY disagreement, not by low confidence."""
        raised = [c for c in self.cases if c.gate_reason == "domain_disagreement"]
        if not raised:
            return None
        return round(sum(1 for c in raised if c.rules_wrong) / len(raised), 3)

    @property
    def gate_precision(self) -> float | None:
        """Of ALL gates raised, the share where the rules were in fact wrong.

        Broader and less flattering than dissent_precision, which counts only
        disagreement gates and therefore hides low-confidence false alarms.
        This is the number an operations manager cares about: how often being
        interrupted was justified.
        """
        raised = [c for c in self.cases if c.gate_raised]
        if not raised:
            return None
        return round(sum(1 for c in raised if c.rules_wrong) / len(raised), 3)

    @property
    def false_alarms(self) -> int:
        return sum(1 for c in self.cases if c.gate_raised and not c.rules_wrong)

    @property
    def dissent_recall(self) -> float | None:
        wrong = [c for c in self.cases if c.rules_wrong]
        if not wrong:
            return None
        return round(sum(1 for c in wrong if c.gate_raised) / len(wrong), 3)

    @property
    def avoided_misdispatch(self) -> int:
        return sum(1 for c in self.cases
                   if c.rules_wrong and c.crew_would_differ and c.gate_raised)

    @property
    def missed_misdispatch(self) -> int:
        return sum(1 for c in self.cases
                   if c.rules_wrong and c.crew_would_differ and not c.gate_raised)

    @property
    def interruption_cost(self) -> float:
        return round(100.0 * self.gates / self.n, 1) if self.n else 0.0

    @property
    def model_domain_accuracy(self) -> float | None:
        scored = [c for c in self.cases if c.model_domain is not None]
        if not scored:
            return None
        return round(sum(1 for c in scored if c.model_domain == c.true_domain) / len(scored), 3)

    @property
    def citation_validity(self) -> float | None:
        cited = sum(len(c.cited_refs) for c in self.cases)
        if not cited:
            return None
        return round(sum(len(c.valid_refs) for c in self.cases) / cited, 3)

    def as_row(self) -> dict[str, object]:
        return {
            "arm": self.arm,
            "cases": self.n,
            "rules_wrong": self.rules_wrong,
            "gates": self.gates,
            "interruption_per_100": self.interruption_cost,
            "dissent_precision": self.dissent_precision,
            "gate_precision": self.gate_precision,
            "false_alarms": self.false_alarms,
            "dissent_recall": self.dissent_recall,
            "avoided_misdispatch": self.avoided_misdispatch,
            "missed_misdispatch": self.missed_misdispatch,
            "model_domain_accuracy": self.model_domain_accuracy,
            "citation_validity": self.citation_validity,
        }


def format_table(reports: Iterable[ArmReport]) -> str:
    rows = [r.as_row() for r in reports]
    cols = ["arm", "cases", "rules_wrong", "gates", "interruption_per_100",
            "gate_precision", "false_alarms", "dissent_precision", "dissent_recall",
            "avoided_misdispatch", "missed_misdispatch", "model_domain_accuracy",
            "citation_validity"]
    head = {"arm": "arm", "cases": "n", "rules_wrong": "wrong", "gates": "gates",
            "interruption_per_100": "gates/100", "gate_precision": "gate.prec",
            "false_alarms": "false", "dissent_precision": "dis.prec",
            "dissent_recall": "dis.rec", "avoided_misdispatch": "avoided",
            "missed_misdispatch": "missed", "model_domain_accuracy": "model.acc",
            "citation_validity": "cite.valid"}
    widths = {c: max(len(head[c]), *(len(_fmt(r[c])) for r in rows)) for c in cols}
    out = ["  ".join(head[c].ljust(widths[c]) for c in cols),
           "  ".join("-" * widths[c] for c in cols)]
    for r in rows:
        out.append("  ".join(_fmt(r[c]).ljust(widths[c]) for c in cols))
    return "\n".join(out)


def _fmt(value: object) -> str:
    if value is None:
        return "n/a"
    return str(value)
