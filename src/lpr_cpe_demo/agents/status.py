"""Agent runtime status, so an inactive agent layer is visible rather than silent.

The gap this closes
-------------------
With no API key every agent falls back to the deterministic rules, and nothing
anywhere reported it. The Control Tower, the effort ledger and the dashboards all
looked identical to a fully agentic run: same numbers, same layout, no indication
that not one model call had succeeded. Given that every other figure in this bundle
carries a provenance label, that was the one place a reader could be misled without
any way to tell.

`describe_provider` answers "what is configured" even before anything has run, and
`StatusRecorder` answers "what actually happened". Both matter: a panel that only
counts runs says nothing on a freshly started system, which is exactly when someone
is checking whether their key took effect.

The key is never read into the snapshot. Only whether one is present.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Mapping

from .provider import DEFAULT_MODEL, Provider

# Sources an agent decision can carry, and what each means for a reader.
SOURCE_MEANING = {
    "anthropic": "a live model produced this decision",
    "scripted": "a canned response produced this decision, for a test or an "
                "offline demonstration",
    "deterministic_fallback": "no usable model decision, so the deterministic "
                              "rules stand",
}


@dataclass(frozen=True, slots=True)
class ProviderDescription:
    kind: str                 # anthropic | null
    model: str | None
    active: bool
    reason: str
    key_present: bool

    @property
    def headline(self) -> str:
        if self.active:
            return f"Live model: {self.model}"
        return "No model active: every decision is the deterministic rules"


def describe_provider(env: Mapping[str, str] | None = None) -> ProviderDescription:
    """What is configured, without reading the key itself."""
    source = env if env is not None else os.environ
    key = (source.get("ANTHROPIC_API_KEY") or "").strip()
    forced = "fake" in {(source.get("LLM_PROVIDER") or "").strip().lower(),
                        (source.get("MODEL_PROVIDER") or "").strip().lower()}
    if not key:
        return ProviderDescription(
            "null", None, False,
            "ANTHROPIC_API_KEY is not set, so no model is reachable and every "
            "agent falls back to the deterministic rules", False)
    if forced:
        return ProviderDescription(
            "null", None, False,
            "a key is present but MODEL_PROVIDER or LLM_PROVIDER is set to fake, "
            "so the model is deliberately bypassed", True)
    return ProviderDescription(
        "anthropic", source.get("ANTHROPIC_MODEL", DEFAULT_MODEL), True,
        "a key is present and no switch forces the fake", True)


@dataclass(frozen=True, slots=True)
class AgentRun:
    agent: str
    source: str
    accepted: bool            # False when the deterministic fallback was used
    fallback_reason: str | None = None
    agreed_with_baseline: bool | None = None


@dataclass(slots=True)
class StatusRecorder:
    runs: list[AgentRun] = field(default_factory=list)
    limit: int = 2000

    def record(self, run: AgentRun) -> None:
        self.runs.append(run)
        if len(self.runs) > self.limit:
            del self.runs[:len(self.runs) - self.limit]

    def reset(self) -> None:
        self.runs.clear()

    # ------------------------------------------------------------ readings
    @property
    def attempted(self) -> int:
        return len(self.runs)

    @property
    def accepted(self) -> int:
        return sum(1 for r in self.runs if r.accepted)

    @property
    def fell_back(self) -> int:
        return sum(1 for r in self.runs if not r.accepted)

    @property
    def fallback_rate(self) -> float | None:
        """None rather than 0.0 when nothing has run.

        Zero would read as "no fallbacks, all healthy", which is the opposite of
        what an empty recorder means.
        """
        if not self.runs:
            return None
        return round(self.fell_back / len(self.runs), 4)

    def by_agent(self) -> list[dict[str, Any]]:
        names: dict[str, dict[str, Any]] = {}
        for run in self.runs:
            row = names.setdefault(run.agent, {"agent": run.agent, "attempted": 0,
                                               "accepted": 0, "fell_back": 0,
                                               "disagreed": 0})
            row["attempted"] += 1
            row["accepted" if run.accepted else "fell_back"] += 1
            if run.agreed_with_baseline is False:
                row["disagreed"] += 1
        return sorted(names.values(), key=lambda r: -r["attempted"])

    def fallback_reasons(self) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for run in self.runs:
            if run.fallback_reason:
                counts[run.fallback_reason] = counts.get(run.fallback_reason, 0) + 1
        return sorted(({"reason": k, "count": v} for k, v in counts.items()),
                      key=lambda r: -r["count"])

    def snapshot(self, env: Mapping[str, str] | None = None) -> dict[str, Any]:
        provider = describe_provider(env)
        return {
            "provider_kind": provider.kind,
            "provider_model": provider.model,
            "provider_active": provider.active,
            "provider_reason": provider.reason,
            "key_present": provider.key_present,
            "headline": provider.headline,
            "attempted": self.attempted,
            "accepted": self.accepted,
            "fell_back": self.fell_back,
            "fallback_rate": self.fallback_rate,
            "by_agent": self.by_agent(),
            "fallback_reasons": self.fallback_reasons(),
            "verdict": self._verdict(provider),
        }

    def _verdict(self, provider: ProviderDescription) -> str:
        if not provider.active:
            return ("INACTIVE: no agent decision can be produced. Every number "
                    "downstream is the deterministic rules, whatever the panels "
                    "look like.")
        if not self.runs:
            return ("CONFIGURED but nothing has run yet, so no decision has been "
                    "attempted.")
        if self.fell_back == len(self.runs):
            return ("CONFIGURED but every attempt fell back. The key is set and "
                    "no decision has survived validation; check the reasons below.")
        if self.fell_back:
            return (f"ACTIVE with {self.fell_back} of {len(self.runs)} attempts "
                    f"falling back.")
        return "ACTIVE, every attempt accepted."


# Module default so an agent records without every caller threading a recorder.
RECORDER = StatusRecorder()
