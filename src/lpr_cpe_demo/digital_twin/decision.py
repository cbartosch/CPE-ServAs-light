# ruff: noqa: E501
from __future__ import annotations

from .models import SIDE_EFFECT_ACTIONS, AgentDecision, Reconciliation

ALL_TECHNOLOGIES = frozenset({"HFC", "GPON", "XGS-PON"})

# Synthetic truth table. Every allowed scenario has an explicit fault domain,
# action branch and technology constraint so generated labels cannot silently
# fall through to "unknown".
SCENARIO_POLICIES: dict[str, dict] = {
    "slow_wifi": {
        "domain": "wifi_or_home",
        "best_action": "remote_repair",
        "next_best_action": "dispatch_clean",
        "technologies": ALL_TECHNOLOGIES,
        "restores_on_best_action": True,
    },
    "no_service": {
        "domain": "drop",
        "best_action": "dispatch_clean",
        "next_best_action": "create_mr",
        "technologies": ALL_TECHNOLOGIES,
        "restores_on_best_action": True,
    },
    "intermittent_service": {
        "domain": "drop",
        "best_action": "dispatch_clean",
        "next_best_action": "create_mr",
        "technologies": ALL_TECHNOLOGIES,
        "restores_on_best_action": True,
    },
    "iptv_degradation": {
        "domain": "wifi_or_home",
        "best_action": "remote_repair",
        "next_best_action": "dispatch_clean",
        "technologies": ALL_TECHNOLOGIES,
        "restores_on_best_action": True,
    },
    "fiber_cut": {
        "domain": "plant",
        "best_action": "create_mr",
        "next_best_action": "plant_repair",
        "technologies": ALL_TECHNOLOGIES,
        "restores_on_best_action": True,
    },
    "hfc_ingress": {
        "domain": "hfc_tap",
        "best_action": "create_mr",
        "next_best_action": "plant_repair",
        "technologies": frozenset({"HFC"}),
        "restores_on_best_action": True,
    },
    "congestion": {
        "domain": "shared_network",
        "best_action": "collect_evidence",
        "next_best_action": "plant_repair",
        "technologies": ALL_TECHNOLOGIES,
        "restores_on_best_action": False,
    },
    "power_outage": {
        "domain": "shared_network",
        "best_action": "collect_evidence",
        "next_best_action": "plant_repair",
        "technologies": ALL_TECHNOLOGIES,
        "restores_on_best_action": False,
    },
    "storm": {
        "domain": "plant",
        "best_action": "create_mr",
        "next_best_action": "plant_repair",
        "technologies": ALL_TECHNOLOGIES,
        "restores_on_best_action": True,
    },
    "flooding": {
        "domain": "plant",
        "best_action": "create_mr",
        "next_best_action": "plant_repair",
        "technologies": ALL_TECHNOLOGIES,
        "restores_on_best_action": True,
    },
    "hurricane": {
        "domain": "plant",
        "best_action": "create_mr",
        "next_best_action": "plant_repair",
        "technologies": ALL_TECHNOLOGIES,
        "restores_on_best_action": True,
    },
    "provisioning_error": {
        "domain": "provisioning",
        "best_action": "remote_repair",
        "next_best_action": "dispatch_clean",
        "technologies": ALL_TECHNOLOGIES,
        "restores_on_best_action": True,
    },
    "cpe_failure": {
        "domain": "cpe",
        "best_action": "cpe_swap",
        "next_best_action": "dispatch_clean",
        "technologies": ALL_TECHNOLOGIES,
        "restores_on_best_action": True,
    },
}


def deterministic_decision(scenario: str, evidence_ids: list[str]) -> dict:
    policy = SCENARIO_POLICIES[scenario]
    actions = [policy["best_action"], policy["next_best_action"], "collect_evidence"]
    return {
        "recommended_domain": policy["domain"],
        "best_action": policy["best_action"],
        "next_best_action": policy["next_best_action"],
        "evidence_ids": list(evidence_ids),
        "eligible_actions": list(dict.fromkeys(actions)),
    }


def fake_agent_decision(deterministic: dict) -> AgentDecision:
    return AgentDecision(
        source="fake",
        provider_status="fake",
        recommended_domain=deterministic["recommended_domain"],
        best_action=deterministic["best_action"],
        next_best_action=deterministic["next_best_action"],
        confidence=0.5,
        safe_to_automate=False,
        evidence_ids=list(deterministic["evidence_ids"]),
        concise_rationale="Offline fake assistant mirrors evidence for display only; it is not independent corroboration.",
    )


def unavailable_agent_decision(deterministic: dict) -> AgentDecision:
    return AgentDecision(
        source="unavailable",
        provider_status="unavailable",
        recommended_domain="unknown",
        best_action="collect_evidence",
        next_best_action=deterministic["next_best_action"],
        confidence=0.0,
        safe_to_automate=False,
        evidence_ids=list(deterministic["evidence_ids"]),
        concise_rationale="Model unavailable; route to human review.",
    )


def disabled_agent_decision(deterministic: dict) -> AgentDecision:
    return AgentDecision(
        source="disabled",
        provider_status="disabled",
        recommended_domain="unknown",
        best_action="collect_evidence",
        next_best_action=deterministic["next_best_action"],
        confidence=0.0,
        safe_to_automate=False,
        evidence_ids=list(deterministic["evidence_ids"]),
        concise_rationale="External model disabled; route consequential decisions to human review.",
    )


def reconcile(deterministic: dict, agent: AgentDecision, valid_evidence: set[str]) -> Reconciliation:
    independent = agent.source == "llm" and agent.provider_status == "ok"
    domain_agreement = agent.recommended_domain == deterministic["recommended_domain"]
    action_agreement = agent.best_action == deterministic["best_action"]
    evidence_valid = bool(agent.evidence_ids) and set(agent.evidence_ids).issubset(valid_evidence)
    side_effect = deterministic["best_action"] in SIDE_EFFECT_ACTIONS
    automation_safe = agent.safe_to_automate and agent.confidence >= 0.80
    needs_human = (
        (not independent)
        or (not domain_agreement)
        or (not action_agreement)
        or (not evidence_valid)
        or side_effect
        or (not automation_safe)
    )
    reasons = []
    if not independent:
        reasons.append("model_not_independent")
    if not domain_agreement:
        reasons.append("domain_disagreement")
    if not action_agreement:
        reasons.append("action_disagreement")
    if not evidence_valid:
        reasons.append("invalid_evidence")
    if side_effect:
        reasons.append("side_effect_requires_human")
    if not automation_safe:
        reasons.append("automation_not_safe_or_low_confidence")
    return Reconciliation(
        independent_model=independent,
        domain_agreement=domain_agreement,
        action_agreement=action_agreement,
        evidence_valid=evidence_valid,
        human_review_required=needs_human,
        reason=",".join(reasons) if reasons else "read_only_agreement",
    )


def reconcile_with_operating_controls(
    deterministic: dict,
    agent: AgentDecision,
    valid_evidence: set[str],
    *,
    repeat: bool = False,
) -> Reconciliation:
    """Recompute policy from source facts and apply non-bypassable operating controls."""
    base = reconcile(deterministic, agent, valid_evidence)
    if not repeat:
        return base
    reasons = [r for r in base.reason.split(",") if r and r != "read_only_agreement"]
    if "repeat_requires_supervisor" not in reasons:
        reasons.append("repeat_requires_supervisor")
    return base.model_copy(
        update={
            "human_review_required": True,
            "reason": ",".join(reasons),
        }
    )
