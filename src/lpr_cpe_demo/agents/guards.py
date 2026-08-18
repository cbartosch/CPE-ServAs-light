"""Policy: the only thing standing between an agent decision and an action.

The operator chose that agents decide and that policy and the gates are the only
guard. The existing `_policy` checked two things: that an action was selected and
that some evidence existed. That was adequate while a deterministic ranker chose
the action and could only ever choose a sane one. It is not adequate now.

Every rule below exists because an agent can produce an output that is
schema-valid and still wrong:

* a remote action against a corroded tap, which interrupts a customer and repairs
  nothing
* a clean-boots visit for a fault affecting four hundred households
* a dispatch to a base that has neither the skill nor the part
* a third remote attempt after two have already failed
* a plant action on a single-household drop fault

`BLOCKED` is reserved for what must never happen. Everything else that is merely
consequential is `REQUIRES_APPROVAL`, because a human refusing is cheap and a
blocked incident that should have proceeded is not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Sequence

from ..geography import BASE_BY_ID
from ..plant import blast_radius

Verdict = Literal["allowed", "requires_approval", "blocked"]

REMOTE_ACTIONS = frozenset({"remote_reboot", "remote_reprovision", "self_help"})
FIELD_ACTIONS = frozenset({"clean_boots", "dirty_boots_mr", "joint_dispatch",
                           "plant_action"})
# Domains no remote action can repair.
PHYSICAL_DOMAINS = frozenset({"drop", "hfc_tap", "pon_odp", "plant",
                              "shared_network"})
# Domains a clean-boots technician cannot resolve alone.
PLANT_DOMAINS = frozenset({"hfc_tap", "pon_odp", "plant", "shared_network"})
# Above this many households, any action is a plant event and gets a second pair
# of eyes regardless of what it is.
HIGH_BLAST_RADIUS = 24


@dataclass(frozen=True, slots=True)
class PolicyResult:
    verdict: Verdict
    reasons: tuple[str, ...]
    approval_kind: str | None

    @property
    def permitted(self) -> bool:
        return self.verdict != "blocked"


@dataclass(slots=True)
class ActionRequest:
    domain: str
    action: str
    technology: str
    site_id: str
    remote_attempts: int = 0
    field_visits: int = 0
    max_remote_attempts: int = 2
    max_field_visits: int = 3
    base_id: str | None = None
    required_skills: Sequence[str] = ()
    required_parts: Sequence[str] = ()
    evidence_count: int = 0
    agent_agrees_with_baseline: bool | None = None
    agent_confidence: float = 1.0
    agent_is_fallback: bool = False
    confidence_threshold: float = 0.70


def evaluate(request: ActionRequest) -> PolicyResult:
    """Decide whether the agent's plan may proceed, needs a human, or must not run."""
    blocked: list[str] = []
    approvals: list[str] = []
    kind: str | None = None

    households = blast_radius(request.domain, request.site_id, request.technology)

    # ------------------------------------------------------------ hard stops
    if request.action in REMOTE_ACTIONS and request.domain in PHYSICAL_DOMAINS:
        blocked.append(
            f"{request.action} cannot repair a {request.domain} fault; it would "
            f"interrupt service and change nothing")
    if request.action == "clean_boots" and request.domain in PLANT_DOMAINS:
        blocked.append(
            f"a clean-boots technician cannot resolve a {request.domain} fault "
            f"affecting {households} households; it needs plant work")
    if request.action in REMOTE_ACTIONS and \
            request.remote_attempts >= request.max_remote_attempts:
        blocked.append(
            f"remote attempt budget exhausted at {request.remote_attempts}")
    if request.action in FIELD_ACTIONS and \
            request.field_visits >= request.max_field_visits:
        blocked.append(f"field visit budget exhausted at {request.field_visits}")
    if request.action in FIELD_ACTIONS and request.base_id:
        base = BASE_BY_ID.get(request.base_id)
        if base is None:
            blocked.append(f"unknown dispatch base {request.base_id}")
        else:
            missing_skills = set(request.required_skills) - set(base.skills)
            missing_parts = set(request.required_parts) - set(base.van_stock)
            if missing_skills:
                blocked.append(f"{request.base_id} lacks required skills "
                               f"{sorted(missing_skills)}")
            if missing_parts:
                blocked.append(f"{request.base_id} lacks required parts "
                               f"{sorted(missing_parts)}; the crew would arrive "
                               f"unable to work")
    if request.evidence_count == 0:
        blocked.append("no evidence was gathered, so nothing supports any action")

    if blocked:
        return PolicyResult("blocked", tuple(blocked), None)

    # -------------------------------------------------------- human required
    if request.agent_agrees_with_baseline is False:
        approvals.append("the agent and the deterministic classifier disagree")
        kind = "rca_review"
    if request.agent_confidence < request.confidence_threshold:
        approvals.append(f"agent confidence {request.agent_confidence:.2f} is "
                         f"below {request.confidence_threshold:.2f}")
        kind = kind or "rca_review"
    if request.agent_is_fallback:
        approvals.append("the agent was unavailable and the rules-based answer "
                         "is standing in")
        kind = kind or "rca_review"
    if households >= HIGH_BLAST_RADIUS:
        approvals.append(f"{households} households sit behind this element")
        kind = "high_blast_radius"
    if request.action in FIELD_ACTIONS:
        approvals.append(f"{request.action} sends a crew and incurs cost")
        kind = kind or "dispatch"

    if approvals:
        return PolicyResult("requires_approval", tuple(approvals), kind)
    return PolicyResult("allowed", ("no policy rule was triggered",), None)
