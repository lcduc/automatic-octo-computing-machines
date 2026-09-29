"""
Holds the tools available to a :class:`ToolCallingAgent` and dispatches calls by name.

Tools a caller's tier may not use are never offered to the model (checklist
Invariant 3), and are refused again at execution in case a model names one anyway.
"""

# Standard library imports
import logging
from typing import Any, Dict, List, Optional, Protocol

# Local imports
from models.tool_context import ToolContext
from .base import BaseTool

logger = logging.getLogger(__name__)


class ToolSource(Protocol):
    """Provides tools that can change at runtime (e.g. SQL tools toggled in the admin web)."""

    def tools(self) -> List[BaseTool]:
        """The currently enabled tools."""


class ToolRegistry:
    """Looks up and executes tools by the name the model called."""

    def __init__(self, tools: List[BaseTool], source: Optional[ToolSource] = None):
        """
        Args:
            tools: Fixed tools. May be empty.
            source: Tools that change at runtime (read on every call).
        """
        self._tools = list(tools)
        self._source = source

    def _all(self) -> Dict[str, BaseTool]:
        """Every tool currently available, by name."""
        tools = list(self._tools) + (self._source.tools() if self._source is not None else [])
        return {tool.name: tool for tool in tools}

    def schemas(self, context: ToolContext) -> List[Dict[str, Any]]:
        """OpenAI ``tools=`` schemas of the tools ``context`` may use."""
        return [tool.to_openai_schema() for tool in self._all().values() if tool.permits(context)]

    def locked(self, context: ToolContext) -> List[BaseTool]:
        """Tools that exist but need a higher tier than ``context`` (described only, never offered)."""
        return [tool for tool in self._all().values() if not tool.permits(context)]

    async def execute(self, name: str, arguments: Dict[str, Any], context: ToolContext) -> str:
        """
        Run the named tool and return its result as text.

        A tool that raises, a name that isn't registered or permitted, or a
        call missing a required argument becomes an error string the model can
        react to (e.g. ask the user) instead of failing the turn.

        Args:
            name: Tool name as called by the model.
            arguments: Parsed JSON arguments the model supplied.
            context: The verified caller.
        """
        tool = self._all().get(name)
        if tool is None or not tool.permits(context):
            logger.warning("Model called unavailable tool %r", name)
            return f"Error: no tool named '{name}' is available."

        missing = [param for param in tool.parameters.get("required", []) if param not in arguments]
        if missing:
            logger.warning("Model called %r missing required argument(s): %s", name, missing)
            return (
                f"Error: missing required argument(s) for '{name}': "
                f"{', '.join(missing)}. Ask the user for the missing information."
            )

        try:
            return await tool.execute(arguments, context)
        except Exception as exc:
            # Arguments are not logged: they may carry what the user typed.
            logger.exception("Tool %r failed", name)
            return f"Error: tool '{name}' failed ({type(exc).__name__})."
