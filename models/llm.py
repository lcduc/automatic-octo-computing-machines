"""
Provider-neutral results of LLM calls, carrying token usage for accounting.
"""

# Standard library imports
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class LLMUsage:
    """Tokens billed for one LLM call."""

    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """Prompt plus completion tokens."""
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class LLMResult:
    """Text and usage of a non-streaming completion."""

    text: str
    usage: Optional[LLMUsage] = None


@dataclass(frozen=True)
class StreamDelta:
    """
    One item of a streamed completion.

    Text deltas carry ``text``; the final item carries ``usage`` (and empty
    text) once the provider reports it.
    """

    text: str = ""
    usage: Optional[LLMUsage] = None
