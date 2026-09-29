"""
Abstract base for a model-invocable tool.

A tool is a named, schema-described capability the LLM can choose to call via
OpenAI function/tool calling. Concrete tools live in their own files; this
just fixes the shape every one of them must have.
"""

# Standard library imports
from abc import ABC, abstractmethod
from typing import Any, Dict

# Local imports
from models.caller import ANONYMOUS_LEVEL
from models.tool_context import ToolContext


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

    @property
    def required_tier_level(self) -> int:
        """Lowest caller tier allowed to use this tool (0 = anonymous visitors too)."""
        return ANONYMOUS_LEVEL

    @abstractmethod
    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> str:
        """
        Run the tool and return its result as text for the model to read.

        Args:
            arguments: Parsed arguments the model supplied (untrusted).
            context: The verified caller (never derived from ``arguments``).

        Returns:
            The tool's result, as the content of a ``role: tool`` message.
        """

    def permits(self, context: ToolContext) -> bool:
        """Whether ``context``'s tier may use this tool."""
        return context.tier_level >= self.required_tier_level

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
