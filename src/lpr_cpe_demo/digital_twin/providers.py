# ruff: noqa: E501
from __future__ import annotations

from typing import Any

from .models import AgentDecision

SYSTEM_PROMPT = (
    "You are an LPR fixed-access RCA challenger. Use only supplied evidence IDs. "
    "Return the strict AgentDecision schema. Never claim authority to execute a change."
)


def build_structured_client(provider: str, model: str, api_key: str | None = None) -> Any:
    if provider == "openai":
        from langchain_openai import ChatOpenAI
        client = ChatOpenAI(model=model, api_key=api_key, timeout=20, max_retries=2, temperature=0)
    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        client = ChatAnthropic(model=model, api_key=api_key, timeout=20, max_retries=2, temperature=0)
    else:
        raise ValueError("provider must be openai or anthropic")
    return client.with_structured_output(AgentDecision)


def invoke_structured(client: Any, evidence_packet: dict) -> AgentDecision:
    result = client.invoke([
        ("system", SYSTEM_PROMPT),
        ("human", f"Evidence packet: {evidence_packet!r}"),
    ])
    return result if isinstance(result, AgentDecision) else AgentDecision.model_validate(result)
