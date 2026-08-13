"""
Abstract base for a model-invocable tool.

A tool is a named, schema-described capability the LLM can choose to call via
OpenAI function/tool calling. Concrete tools live in their own files; this
just fixes the shape every one of them must have.
"""

# Standard library imports
from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseTool(ABC):
    """A single tool the model can call by name with JSON-schema-typed arguments."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable identifier the model uses to call this tool."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Natural-language description the model uses to decide when to call this tool."""

    @property
    @abstractmethod
    def parameters(self) -> Dict[str, Any]:
        """JSON schema (OpenAI function-parameters format) for this tool's arguments."""

    @abstractmethod
    def execute(self, **kwargs: Any) -> str:
        """
        Run the tool and return its result as text for the model to read.

        Args:
            **kwargs: Arguments matching :attr:`parameters`.

        Returns:
            The tool's result, as the content of a ``role: tool`` message.
        """

    def to_openai_schema(self) -> Dict[str, Any]:
        """Build the ``{"type": "function", "function": {...}}`` block for the ``tools=`` param."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
