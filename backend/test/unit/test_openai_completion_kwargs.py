"""Token-limit/temperature kwargs per OpenAI model family."""

import types

import pytest

from app.core.agent.openai_client import OpenAIClientProvider

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


class _RecordingCompletions:
    """Stands in for ``chat.completions``; records the kwargs of each call."""

    def __init__(self) -> None:
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        message = types.SimpleNamespace(content="", tool_calls=None)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)], usage=None)


def _recording_provider() -> tuple:
    provider = OpenAIClientProvider(api_key="test-key")
    completions = _RecordingCompletions()
    provider._async_client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=completions))
    return provider, completions


TOOLS = [{"type": "function", "function": {"name": "get_current_time", "parameters": {"type": "object"}}}]


@pytest.mark.asyncio
async def test_a_call_offering_tools_uses_the_tool_reasoning_effort(monkeypatch) -> None:
    """TOOL-12: gpt-6-luna refuses tools unless reasoning_effort is `none`, while answers keep `low`."""
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "low")
    monkeypatch.setenv("OPENAI_TOOL_REASONING_EFFORT", "none")
    provider, completions = _recording_provider()

    await provider.complete_with_tools_async([], tools=TOOLS, model="gpt-6-luna")
    await provider.complete_with_tools_async([], tools=None, model="gpt-6-luna")

    assert [call["extra_body"] for call in completions.calls] == [{"reasoning_effort": "none"}, {"reasoning_effort": "low"}]


@pytest.mark.asyncio
async def test_an_empty_tool_reasoning_effort_falls_back_to_the_answer_one(monkeypatch) -> None:
    """gpt-5-mini refuses `none`, so leaving the tool setting empty must keep the answer's effort."""
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "low")
    monkeypatch.setenv("OPENAI_TOOL_REASONING_EFFORT", "")
    provider, completions = _recording_provider()

    await provider.complete_with_tools_async([], tools=TOOLS, model="gpt-5-mini")

    assert completions.calls[0]["extra_body"] == {"reasoning_effort": "low"}
