"""
Deterministic stand-in for a chat-completion API, for load tests only.

Selected with ``LLM_PROVIDER=stub``. It streams a fixed Vietnamese sentence
after a configurable time to first token and per-token delay, so a load test
measures this application's own pipeline (auth, quotas, routing, retrieval,
reranking, persistence) instead of a provider's latency and rate limits.
``Config.problems()`` reports the stub, so ``APP_ENV=production`` refuses to start with it.
"""

# Standard library imports
import asyncio
import itertools
import logging
import time
from typing import Any, AsyncIterator, Dict, List, Optional

# Local imports
from config.settings import Config
from models.llm import LLMResult, LLMUsage, StreamDelta
from .base_llm_provider import BaseLLMProvider

logger = logging.getLogger(__name__)

#: Words the stub cycles through; one word (plus a space) is one streamed token.
STUB_WORDS = "Đây là câu trả lời mẫu của mô hình giả lập dùng để đo tải hệ thống".split()
#: Rough characters per prompt token, to report a plausible prompt size in usage.
CHARS_PER_TOKEN = 4
MILLISECONDS_PER_SECOND = 1000


class StubClientProvider(BaseLLMProvider):
    """Answers every prompt with the same tokens on a fixed schedule; never calls the network."""

    name = "stub"

    def __init__(
        self,
        ttft_ms: Optional[int] = None,
        token_delay_ms: Optional[int] = None,
        token_count: Optional[int] = None,
    ):
        """
        Args:
            ttft_ms: Delay before the first token; defaults to ``STUB_LLM_TTFT_MS``.
            token_delay_ms: Delay between later tokens; defaults to ``STUB_LLM_TOKEN_DELAY_MS``.
            token_count: Tokens per answer; defaults to ``STUB_LLM_TOKENS``.
        """
        self._ttft_ms = ttft_ms if ttft_ms is not None else Config.LLM.STUB_LLM_TTFT_MS()
        self._token_delay_ms = token_delay_ms if token_delay_ms is not None else Config.LLM.STUB_LLM_TOKEN_DELAY_MS()
        self._token_count = token_count if token_count is not None else Config.LLM.STUB_LLM_TOKENS()

    @property
    def is_configured(self) -> bool:
        """Always true: the stub needs no key."""
        return True

    def check_availability(self) -> bool:
        """Always reachable."""
        return True

    def answer_tokens(self) -> List[str]:
        """The tokens of every answer, in order (their concatenation is the answer text)."""
        words = itertools.islice(itertools.cycle(STUB_WORDS), self._token_count)
        return [f"{word} " for word in words]

    def _usage(self, messages: List[Dict[str, Any]], model: Optional[str]) -> LLMUsage:
        """Usage sized like a real call: prompt characters / 4, one completion token per word."""
        prompt_chars = sum(len(str(message.get("content", ""))) for message in messages)
        return LLMUsage(self.name, model or Config.LLM.ACTIVE_MODEL(), prompt_chars // CHARS_PER_TOKEN, self._token_count)

    def complete(self, messages: List[Dict[str, Any]], model: Optional[str] = None) -> LLMResult:
        """Block for the time to first token, then return the whole answer."""
        time.sleep(self._ttft_ms / MILLISECONDS_PER_SECOND)
        return LLMResult("".join(self.answer_tokens()).strip(), self._usage(messages, model))

    async def complete_async(self, messages: List[Dict[str, Any]], model: Optional[str] = None) -> LLMResult:
        """Wait for the time to first token, then return the whole answer."""
        await asyncio.sleep(self._ttft_ms / MILLISECONDS_PER_SECOND)
        return LLMResult("".join(self.answer_tokens()).strip(), self._usage(messages, model))

    async def stream(self, messages: List[Dict[str, Any]], model: Optional[str] = None) -> AsyncIterator[StreamDelta]:
        """
        Yield the first token after the TTFT, each later one a token delay after the previous, then usage.

        Each token is due at a fixed time from the call, as from a remote stream: a busy event loop
        delays tokens without stretching the schedule, and sleep granularity (~15 ms on Windows) does
        not add up over the answer.
        """
        loop = asyncio.get_running_loop()
        started = loop.time()
        for index, token in enumerate(self.answer_tokens()):
            due = started + (self._ttft_ms + index * self._token_delay_ms) / MILLISECONDS_PER_SECOND
            await asyncio.sleep(max(0.0, due - loop.time()))
            yield StreamDelta(text=token)
        yield StreamDelta(usage=self._usage(messages, model))

    def close(self) -> None:
        """Nothing to release."""
