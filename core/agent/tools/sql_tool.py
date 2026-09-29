"""
A predefined, parameterized query the model can call (TOOL-01..06).

The model supplies only the declared arguments, validated before anything
runs; ``:user_id`` is bound from the verified caller (Invariant 1). Results
keep only the allowed columns, mask sensitive ones, are capped in rows and
characters, and are returned as data for a ``role: tool`` message.
"""

# Standard library imports
import json
import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Dict, List

# Third-party imports
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

# Local imports
from models.tool_context import ToolContext
from .base import BaseTool
from .sql_tool_executor import SqlToolExecutor, SqlToolTimeoutError
from .tool_arguments import ToolArguments, ToolArgumentsError

logger = logging.getLogger(__name__)

USER_PARAMETER = "user_id"
#: Characters of a masked value left visible.
MASK_VISIBLE_CHARS = 4
MASK = "•••"
_READ_ONLY_START = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)


class SqlToolDefinitionError(ValueError):
    """A tool definition is unsafe or inconsistent (it is skipped, never run)."""


@dataclass(frozen=True)
class SqlToolSpec:
    """What a stored tool definition says."""

    name: str
    description: str
    args_schema: Dict[str, Any]
    required_tier_level: int
    sql_template: str
    allowed_columns: List[str]
    masked_columns: List[str]
    row_limit: int


def _mask(value: Any) -> str:
    """Show only the last characters of a sensitive value."""
    raw = str(value)
    return MASK + raw[-MASK_VISIBLE_CHARS:] if len(raw) > MASK_VISIBLE_CHARS else MASK


class SqlTool(BaseTool):
    """One SQL tool, compiled from its spec."""

    def __init__(self, spec: SqlToolSpec, executor: SqlToolExecutor, today: Callable[[], date], max_result_chars: int):
        """
        Args:
            spec: The definition.
            executor: Runs the template on the business database.
            today: Current local date (for periods like "tháng trước").
            max_result_chars: Longest result text handed to the model.

        Raises:
            SqlToolDefinitionError: Not a SELECT, undeclared parameters, or no allowed columns.
        """
        self._spec = spec
        self._executor = executor
        self._today = today
        self._max_result_chars = max_result_chars
        try:
            self._arguments = ToolArguments(spec.args_schema)
        except ToolArgumentsError as exc:
            raise SqlToolDefinitionError(f"{spec.name}: {exc}") from exc
        if not _READ_ONLY_START.match(spec.sql_template):
            raise SqlToolDefinitionError(f"{spec.name}: the template must be a SELECT (or WITH … SELECT)")
        bound = set(text(spec.sql_template).compile(dialect=postgresql.dialect()).params)
        undeclared = bound - set(self._arguments.parameter_names) - {USER_PARAMETER}
        if undeclared:
            raise SqlToolDefinitionError(f"{spec.name}: template binds undeclared parameters {sorted(undeclared)}")
        if not spec.allowed_columns or not set(spec.masked_columns) <= set(spec.allowed_columns):
            raise SqlToolDefinitionError(f"{spec.name}: allowed_columns must be set and include every masked column")
        self._uses_user = USER_PARAMETER in bound

    @property
    def name(self) -> str:
        return self._spec.name

    @property
    def description(self) -> str:
        return self._spec.description

    @property
    def parameters(self) -> Dict[str, Any]:
        return self._spec.args_schema

    @property
    def required_tier_level(self) -> int:
        return self._spec.required_tier_level

    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> str:
        """Validate, run and shape the result (errors come back as text the model can act on)."""
        try:
            parameters = self._arguments.parse(arguments, self._today)
        except ToolArgumentsError as exc:
            logger.info("Tool %s: invalid arguments", self.name)
            return f"Error: invalid arguments for '{self.name}': {exc}"
        if self._uses_user:
            if not context.logged_in:
                return f"Error: '{self.name}' needs a signed-in user."
            parameters[USER_PARAMETER] = context.user_id
        try:
            rows, truncated = await self._executor.fetch(self._spec.sql_template, parameters, context.user_id, self._spec.row_limit)
        except SqlToolTimeoutError:
            logger.exception("Tool %s timed out", self.name)
            return f"Error: '{self.name}' took too long. Ask the user to narrow the request (e.g. a shorter period)."
        shaped = [self._shape(row) for row in rows]
        logger.info("Tool %s returned %d row(s)%s", self.name, len(shaped), " (truncated)" if truncated else "")
        return self._render(shaped, truncated)

    def _shape(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Keep allowed columns only (TOOL-06), masking sensitive ones."""
        return {
            column: (_mask(row[column]) if column in self._spec.masked_columns and row[column] is not None else row[column])
            for column in self._spec.allowed_columns
            if column in row
        }

    def _render(self, rows: List[Dict[str, Any]], truncated: bool) -> str:
        """JSON result for the model, cut to the character budget by dropping trailing rows."""
        while True:
            payload = json.dumps({"tool": self.name, "rows": rows, "row_count": len(rows), "truncated": truncated},
                                 ensure_ascii=False, default=str)
            if len(payload) <= self._max_result_chars or not rows:
                return payload
            rows, truncated = rows[:-1], True
