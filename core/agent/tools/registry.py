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

        A tool that raises, a name that isn't registered, or a call missing
        one of the tool's required arguments is turned into an error string
        rather than propagated or run with incomplete data — the model can
        react to (e.g. ask the user for the missing piece) instead of the
        whole turn failing or the tool running on guessed input.

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

        missing = self._missing_required_arguments(tool, arguments)
        if missing:
            logger.warning(
                "Model called %r missing required argument(s): %s", name, missing
            )
            return (
                f"Error: missing required argument(s) for '{name}': "
                f"{', '.join(missing)}. Ask the user for the missing information."
            )

        try:
            return tool.execute(**arguments)
        except Exception as exc:
            logger.exception("Tool %r failed with arguments %r", name, arguments)
            return f"Error: tool '{name}' failed: {exc}"

    @staticmethod
    def _missing_required_arguments(tool: BaseTool, arguments: Dict[str, Any]) -> List[str]:
        """Required parameter names from the tool's schema absent from ``arguments``."""
        required = tool.parameters.get("required", [])
        return [param_name for param_name in required if param_name not in arguments]
