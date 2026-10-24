"""The load-test stub streams fixed tokens on schedule, is chosen only by LLM_PROVIDER=stub, and production refuses it."""

import time

import pytest

from config.settings import Config
from core.agent.provider_factory import LLMProviderFactory
from core.agent.stub_client import STUB_WORDS, StubClientProvider

TTFT_MS = 60
TOKEN_DELAY_MS = 10
TOKENS = 4
#: Slack for timer resolution on Windows (~15 ms) when checking the schedule.
TIMER_SLACK_S = 0.02


async def _timed_stream(provider):
    started = time.perf_counter()
    events = []
    async for delta in provider.stream([{"role": "user", "content": "x" * 400}]):
        events.append((time.perf_counter() - started, delta))
    return events


@pytest.mark.asyncio
async def test_stream_is_deterministic_and_keeps_the_configured_schedule():
    provider = StubClientProvider(ttft_ms=TTFT_MS, token_delay_ms=TOKEN_DELAY_MS, token_count=TOKENS)

    first, second = await _timed_stream(provider), await _timed_stream(provider)

    texts = [delta.text for _, delta in first if delta.text]
    assert texts == [f"{word} " for word in STUB_WORDS[:TOKENS]]
    assert texts == [delta.text for _, delta in second if delta.text]
    first_token_at = first[0][0]
    last_token_at = first[TOKENS - 1][0]
    assert first_token_at >= TTFT_MS / 1000 - TIMER_SLACK_S
    assert last_token_at - first_token_at >= (TOKENS - 1) * TOKEN_DELAY_MS / 1000 - TIMER_SLACK_S
    usage = first[-1][1].usage
    assert (usage.provider, usage.prompt_tokens, usage.completion_tokens) == ("stub", 100, TOKENS)


def test_only_an_explicit_llm_provider_selects_the_stub(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert Config.LLM.LLM_PROVIDER() != "stub"

    monkeypatch.setenv("LLM_PROVIDER", "stub")
    assert isinstance(LLMProviderFactory.create(), StubClientProvider)
    assert Config.LLM.ACTIVE_MODEL() == "stub"


def test_production_refuses_to_start_with_the_stub(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.setenv("APP_ENV", "development")
    Config.validate()  # development only warns

    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError, match="LLM_PROVIDER=stub"):
        Config.validate()
