"""
Provider-agnostic contract for chat-completion backends.

``ChatbotService``, ``QueryRewriter`` and ``IntentRouter`` depend on this
abstraction instead of a concrete SDK client, so the active LLM backend
(OpenAI, Anthropic, Gemini, ...) can be swapped via configuration without
touching any of their code. Tool-calling and transcription are intentionally
excluded: those remain OpenAI-specific capabilities used only by
``ToolCallingAgent`` and ``ChatbotService.transcribe_audio`` respectively.
"""

# Standard library imports
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, List, Optional


class BaseLLMProvider(ABC):
    """
    Shared interface every chat-completion provider must implement.

    Method signatures mirror the OpenAI-format message list
    (``[{"role": ..., "content": ...}, ...]``) used throughout the codebase,
    so callers never need to know which concrete provider is active.
    """

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
    def complete(self, messages: List[Dict[str, Any]], model: Optional[str] = None) -> str:
        """Run a blocking chat completion and return the assistant text."""
        raise NotImplementedError

    @abstractmethod
    async def complete_async(
        self, messages: List[Dict[str, Any]], model: Optional[str] = None
    ) -> str:
        """Run a non-blocking chat completion and return the assistant text."""
        raise NotImplementedError

    @abstractmethod
    def stream(
        self, messages: List[Dict[str, Any]], model: Optional[str] = None
    ) -> AsyncIterator[str]:
        """Stream a chat completion, yielding text deltas as they arrive."""
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        """Release any pooled connections held by this provider."""
        raise NotImplementedError
