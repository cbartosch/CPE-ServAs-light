from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

SCENARIOS = {
    "slow_wifi",
    "no_service",
    "intermittent_service",
    "iptv_degradation",
    "fiber_cut",
    "hfc_ingress",
    "congestion",
    "power_outage",
    "storm",
    "flooding",
    "hurricane",
    "provisioning_error",
    "cpe_failure",
}

SIDE_EFFECT_ACTIONS = {"remote_repair", "dispatch_clean", "create_mr", "plant_repair", "cpe_swap"}


class GenerationConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    run_date: date = date(2026, 8, 21)
    profile: Literal["smoke", "preview", "board", "full"] = "smoke"
    homes: int = Field(default=500, ge=1, le=500_000)
    scenarios: tuple[str, ...] = ("slow_wifi", "fiber_cut", "power_outage")
    seed: int = 2400
    output_format: Literal["jsonl_gz", "parquet"] = "jsonl_gz"
    schema_version: str = "2.4.0"
    generator_version: str = "2.4.0-r3-py314-hotfix4"
    batch_size: int = Field(default=10_000, ge=1, le=100_000)
    enable_llm: bool = False
    llm_provider: Literal["fake", "openai", "anthropic", "disabled"] = "fake"
    llm_model: str = ""

    @field_validator("scenarios")
    @classmethod
    def validate_scenarios(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        unknown = sorted(set(value) - SCENARIOS)
        if unknown:
            raise ValueError(f"unknown scenarios: {', '.join(unknown)}")
        if not value:
            raise ValueError("at least one scenario is required")
        return tuple(dict.fromkeys(value))


class AgentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["llm", "fake", "disabled", "unavailable", "invalid"]
    provider_status: Literal["ok", "fake", "disabled", "unavailable", "invalid"]
    recommended_domain: Literal[
        "cpe", "wifi_or_home", "premise_wiring", "drop", "hfc_tap", "pon_odp",
        "shared_network", "plant", "provisioning", "unknown"
    ]
    best_action: str
    next_best_action: str
    confidence: float = Field(ge=0.0, le=1.0)
    safe_to_automate: StrictBool
    evidence_ids: list[str]
    concise_rationale: str


class Reconciliation(BaseModel):
    independent_model: bool
    domain_agreement: bool
    action_agreement: bool
    evidence_valid: bool
    human_review_required: bool
    reason: str


class HumanDecision(BaseModel):
    case_id: str
    revision: int = Field(ge=1)
    response: Literal["approve", "reject", "request_evidence", "escalate"]
    actor: str = Field(min_length=1, max_length=80)
    rationale: str = Field(min_length=1, max_length=1000)
