"""Retrieval over the prior-case knowledge base.

Deliberately BM25 in pure Python rather than embeddings:

* it runs with no third-party package, so it is unit testable offline and in the
  same container as the rest of the core;
* at this corpus size (tens of documents) lexical retrieval is competitive with
  dense retrieval, and the fault signatures are highly lexical -- "codeword
  errors", "optical Rx", "ingress", "ONT LOS";
* every hit carries a real document id, so citation validity becomes a
  measurable property rather than a formality.

Swapping in embeddings later means replacing `BM25Index` and keeping the
`search()` signature. Nothing above this module needs to change.
"""

from __future__ import annotations

import json
import math
import pathlib
import re
from dataclasses import dataclass, field
from typing import Iterable, NamedTuple

_TOKEN = re.compile(r"[a-z0-9]+")

# Domain-generic words carry no discriminating signal for a fault signature.
_STOPWORDS = frozenset("""
a an the and or of to in on at for with from is was were be been being this that
these those it its as by not no than then so if but out up down over under after
before during customer service issue problem fault case ticket incident report
reported observed noted seen found shows showed indicates indicated
""".split())


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1]


@dataclass(frozen=True, slots=True)
class Document:
    doc_id: str
    kind: str                 # prior_case | procedure
    technology: str           # HFC | PON | ANY
    signature: str            # the searchable fault signature
    resolved_domain: str      # ground-truth domain for a prior case
    resolution: str
    delimiter_type: str = ""


class Hit(NamedTuple):
    doc_id: str
    score: float
    resolved_domain: str
    technology: str
    kind: str
    resolution: str


@dataclass
class BM25Index:
    """Okapi BM25. k1 and b are the conventional defaults."""

    k1: float = 1.5
    b: float = 0.75
    docs: list[Document] = field(default_factory=list)
    _tokens: list[list[str]] = field(default_factory=list, repr=False)
    _df: dict[str, int] = field(default_factory=dict, repr=False)
    _avgdl: float = 0.0

    def add(self, documents: Iterable[Document]) -> "BM25Index":
        for doc in documents:
            toks = tokenize(doc.signature + " " + doc.resolution)
            self.docs.append(doc)
            self._tokens.append(toks)
            for term in set(toks):
                self._df[term] = self._df.get(term, 0) + 1
        lengths = [len(t) for t in self._tokens]
        self._avgdl = (sum(lengths) / len(lengths)) if lengths else 0.0
        return self

    def _idf(self, term: str) -> float:
        n = len(self.docs)
        df = self._df.get(term, 0)
        # BM25+ style floor so a term present in every document still scores >= 0
        return max(math.log(1.0 + (n - df + 0.5) / (df + 0.5)), 0.0)

    def search(self, query: str, *, k: int = 5, technology: str | None = None) -> list[Hit]:
        q = tokenize(query)
        scored: list[Hit] = []
        for doc, toks in zip(self.docs, self._tokens):
            if technology and doc.technology not in {technology, "ANY"}:
                continue
            if not toks:
                continue
            dl = len(toks)
            score = 0.0
            for term in q:
                tf = toks.count(term)
                if not tf:
                    continue
                denom = tf + self.k1 * (1 - self.b + self.b * dl / (self._avgdl or 1.0))
                score += self._idf(term) * (tf * (self.k1 + 1)) / denom
            if score > 0:
                scored.append(Hit(doc.doc_id, round(score, 4), doc.resolved_domain,
                                  doc.technology, doc.kind, doc.resolution))
        scored.sort(key=lambda h: (-h.score, h.doc_id))
        return scored[:k]


class DomainVote(NamedTuple):
    domain: str | None
    confidence: float
    margin: float
    supporting: tuple[str, ...]


def vote_domain(hits: Iterable[Hit], *, min_score: float = 0.5) -> DomainVote:
    """Score-weighted vote over retrieved prior cases.

    Confidence is derived from the winning share, not asserted. A narrow margin
    produces low confidence, which is what should reach the gate.
    """
    weights: dict[str, float] = {}
    support: dict[str, list[str]] = {}
    for hit in hits:
        if hit.kind != "prior_case" or hit.score < min_score or not hit.resolved_domain:
            continue
        weights[hit.resolved_domain] = weights.get(hit.resolved_domain, 0.0) + hit.score
        support.setdefault(hit.resolved_domain, []).append(hit.doc_id)

    if not weights:
        return DomainVote(None, 0.0, 0.0, ())

    ranked = sorted(weights.items(), key=lambda kv: -kv[1])
    total = sum(weights.values())
    top_domain, top_weight = ranked[0]
    runner = ranked[1][1] if len(ranked) > 1 else 0.0
    share = top_weight / total
    margin = (top_weight - runner) / total
    # Map share onto a calibrated-looking band. Never claim more than 0.92 from
    # lexical retrieval alone; never less than 0.40 when there is any support.
    confidence = round(min(0.92, max(0.40, 0.40 + 0.52 * share)), 3)
    return DomainVote(top_domain, confidence, round(margin, 3),
                      tuple(support[top_domain]))


def load_corpus(path: str | pathlib.Path) -> list[Document]:
    raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    return [Document(**entry) for entry in raw["documents"]]


def build_index(path: str | pathlib.Path) -> BM25Index:
    return BM25Index().add(load_corpus(path))


DEFAULT_CORPUS = pathlib.Path(__file__).with_name("kb") / "prior_cases.json"
