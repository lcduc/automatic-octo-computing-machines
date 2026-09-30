"""Token-limit/temperature kwargs per OpenAI model family."""

import pytest

from core.agent.openai_client import OpenAIClientProvider

MAX_TOKENS = 512
TEMPERATURE = 0.3


@pytest.mark.parametrize("model", ["gpt-4o-mini", "gpt-4.1", "gpt-3.5-turbo"])
def test_legacy_models_keep_max_tokens_and_temperature(model: str) -> None:
    kwargs = OpenAIClientProvider._completion_kwargs(model, MAX_TOKENS, TEMPERATURE, "low")
    assert kwargs == {"model": model, "max_tokens": MAX_TOKENS, "temperature": TEMPERATURE}


@pytest.mark.parametrize("model", ["gpt-5-mini", "gpt-6-luna", "o4-mini"])
def test_newer_models_use_max_completion_tokens_without_temperature(model: str) -> None:
    kwargs = OpenAIClientProvider._completion_kwargs(model, MAX_TOKENS, TEMPERATURE, "low")
    assert kwargs == {"model": model, "max_completion_tokens": MAX_TOKENS, "extra_body": {"reasoning_effort": "low"}}
