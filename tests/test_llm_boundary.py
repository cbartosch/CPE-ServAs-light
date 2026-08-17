from __future__ import annotations

import pytest

from lpr_cpe_demo.config import Settings
from lpr_cpe_demo.llm.service import FakeRCAAssistant, LLMServiceError, build_rca_assistant


def test_external_provider_without_key_falls_back_only_when_allowed() -> None:
    settings = Settings(
        _env_file=None,
        model_provider="openai",
        model_name="account-model",
        model_fallback_allowed=True,
        openai_api_key="",
        model_api_key="",
    )
    assistant = build_rca_assistant(settings)
    assert isinstance(assistant, FakeRCAAssistant)
    assert assistant.active_model_name == "fake-fallback:openai:account-model"


def test_external_provider_without_key_fails_closed_when_fallback_disabled() -> None:
    settings = Settings(
        _env_file=None,
        model_provider="anthropic",
        model_name="account-model",
        model_fallback_allowed=False,
        anthropic_api_key="",
        model_api_key="",
    )
    with pytest.raises(LLMServiceError):
        build_rca_assistant(settings)
