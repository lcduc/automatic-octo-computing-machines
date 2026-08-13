"""
Holds the tools available to a :class:`ToolCallingAgent` and dispatches calls by name.
"""

# Standard library imports
import logging
from typing import Any, Dict, List

# Local imports
from .base import BaseTool

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Looks up and executes tools by the name the model called."""

    def __init__(self, tools: List[BaseTool]):
        """
        Args:
            tools: Tools available to the model. May be empty.
        """
        self._tools: Dict[str, BaseTool] = {tool.name: tool for tool in tools}

    def schemas(self) -> List[Dict[str, Any]]:
        """OpenAI ``tools=`` schema list for every registered tool."""
        return [tool.to_openai_schema() for tool in self._tools.values()]

    def execute(self, name: str, arguments: Dict[str, Any]) -> str:
        """
        Run the named tool and return its result as text.

        A tool that raises, or a name that isn't registered, is turned into
        an error string rather than propagated — the model can react to a
        failed tool call instead of the whole turn failing.

        Args:
            name: Tool name as called by the model.
            arguments: Parsed JSON arguments the model supplied.

        Returns:
            The tool's result, or an error message describing what went wrong.
        """
        tool = self._tools.get(name)
        if tool is None:
            logger.warning("Model called unknown tool %r", name)
            return f"Error: no tool named '{name}' is available."

        try:
            return tool.execute(**arguments)
        except Exception as exc:
            logger.exception("Tool %r failed with arguments %r", name, arguments)
            return f"Error: tool '{name}' failed: {exc}"
