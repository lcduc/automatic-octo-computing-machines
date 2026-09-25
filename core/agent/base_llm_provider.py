"""
Provider-agnostic contract for chat-completion backends.

The chat pipeline, ``QueryRewriter`` and ``IntentRouter`` depend on this
abstraction instead of a concrete SDK client, so the active LLM backend
(OpenAI, Anthropic, Gemini) is swapped via configuration only. Every call
reports its token usage so the platform can track and budget consumption.
Tool-calling and transcription remain OpenAI-specific extras.
"""

# Standard library imports
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, List, Optional

# Local imports
from models.llm import LLMResult, StreamDelta


class BaseLLMProvider(ABC):
    """
    Shared interface every chat-completion provider must implement.

    Messages use the OpenAI format (``[{"role": ..., "content": ...}, ...]``)
    throughout the codebase; each provider translates as needed.
    """

    #: Short provider id recorded with token usage (``openai``, ``anthropic``, ``gemini``).
    name: str = "unknown"

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """True when an API key is present for this provider."""
        raise NotImplementedError

    @abstractmethod
    def check_availability(self) -> bool:
        """Probe the provider's API and report whether it is reachable."""
        raise NotImplementedError

    @abstractmethod
    def complete(self, messages: List[Dict[str, Any]], model: Optional[str] = None) -> LLMResult:
        """Run a blocking chat completion."""
        raise NotImplementedError

    @abstractmethod
    async def complete_async(self, messages: List[Dict[str, Any]], model: Optional[str] = None) -> LLMResult:
        """Run a non-blocking chat completion."""
        raise NotImplementedError

    @abstractmethod
    def stream(self, messages: List[Dict[str, Any]], model: Optional[str] = None) -> AsyncIterator[StreamDelta]:
        """Stream a chat completion: text deltas, then one delta carrying usage."""
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        """Release any pooled connections held by this provider."""
        raise NotImplementedError
