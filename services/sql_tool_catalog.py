"""
The SQL tools of this deployment: loaded from the ``sql_tools`` table, toggled in the admin web (TOOL-08).

# ceiling: tools are cached per process and reloaded on this process's
# changes; reload on a timer if several API processes ever run.
"""

# Standard library imports
import logging
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Sequence
from zoneinfo import ZoneInfo

# Third-party imports
from sqlalchemy import select

# Local imports
from config.settings import Config
from config.tool_settings import BusinessDbConfig
from core.agent.tools.base import BaseTool
from core.agent.tools.sql_tool import SqlTool, SqlToolDefinitionError, SqlToolSpec
from core.agent.tools.sql_tool_executor import SqlToolExecutor
from core.storage.database import Database
from core.storage.tables.tool_tables import SqlToolDefinition
from models.caller import ANONYMOUS_LEVEL, TIER_ANONYMOUS
from .errors import InvalidRequestError, NotFoundError

logger = logging.getLogger(__name__)

#: Keys a definition file entry may have (``enabled`` is managed in the admin web).
DEFINITION_KEYS = ("name", "description", "args_schema", "required_tier", "sql_template",
                   "allowed_columns", "masked_columns", "row_limit")
MAX_ROW_LIMIT = 200


class SqlToolCatalog:
    """Enabled SQL tools, ready for the tool registry (a :class:`ToolSource`)."""

    def __init__(self, database: Database, executor: SqlToolExecutor, tier_level: Callable[[str], int]):
        """
        Args:
            database: The chatbot database (tool definitions).
            executor: Runs templates on the business database.
            tier_level: Tier name -> access level (0 = anonymous).
        """
        self._database = database
        self._executor = executor
        self._tier_level = tier_level
        self._zone = ZoneInfo(Config.Server.APP_TIMEZONE())
        self._tools: List[BaseTool] = []

    def _today(self) -> date:
        """The local date periods are relative to."""
        return datetime.now(self._zone).date()

    def tools(self) -> List[BaseTool]:
        """Currently enabled, valid tools."""
        return list(self._tools)

    async def load(self) -> None:
        """Compile every enabled definition; invalid ones are logged and skipped."""
        async with self._database.session() as session:
            rows = (await session.execute(select(SqlToolDefinition).where(SqlToolDefinition.enabled.is_(True)))).scalars().all()
        compiled: List[BaseTool] = []
        for row in rows:
            try:
                compiled.append(self._compile(row))
            except SqlToolDefinitionError:
                logger.exception("Skipping invalid SQL tool %s", row.name)
        self._tools = compiled
        logger.info("Loaded %d SQL tools", len(compiled))

    def _compile(self, row: SqlToolDefinition) -> SqlTool:
        """
        A runnable tool from a stored definition.

        Raises:
            SqlToolDefinitionError: Invalid definition, including an unknown tier
                (which must never fall back to "anonymous").
        """
        level = self._tier_level(row.required_tier)
        if row.required_tier != TIER_ANONYMOUS and level == ANONYMOUS_LEVEL:
            raise SqlToolDefinitionError(f"{row.name}: unknown required_tier {row.required_tier!r}")
        spec = SqlToolSpec(row.name, row.description, row.args_schema, level,
                           row.sql_template, list(row.allowed_columns), list(row.masked_columns or []),
                           min(row.row_limit, MAX_ROW_LIMIT))
        return SqlTool(spec, self._executor, self._today, BusinessDbConfig.SQL_TOOL_MAX_RESULT_CHARS())

    async def list(self) -> List[SqlToolDefinition]:
        """Every definition, enabled or not, by name."""
        async with self._database.session() as session:
            return list((await session.execute(select(SqlToolDefinition).order_by(SqlToolDefinition.name))).scalars().all())

    async def set_enabled(self, name: str, enabled: bool, updated_by: str) -> SqlToolDefinition:
        """
        Switch a tool on or off; applies to the next turn.

        Raises:
            NotFoundError: Unknown tool.
        """
        async with self._database.session() as session:
            row = await session.get(SqlToolDefinition, name)
            if row is None:
                raise NotFoundError("Tool not found")
            row.enabled = enabled
            row.updated_by = updated_by
        await self.load()
        logger.info("SQL tool %s %s by %s", name, "enabled" if enabled else "disabled", updated_by)
        return row

    async def sync(self, definitions: Sequence[Dict[str, Any]], updated_by: str) -> List[str]:
        """
        Create or update definitions from the integrator's file, keeping each tool's ``enabled`` flag.

        Returns:
            Names written.

        Raises:
            InvalidRequestError: A definition is malformed or unsafe (nothing is written then).
        """
        for definition in definitions:
            unknown = set(definition) - set(DEFINITION_KEYS) - {"enabled"}
            missing = {"name", "description", "args_schema", "sql_template", "allowed_columns"} - set(definition)
            if unknown or missing:
                raise InvalidRequestError(f"{definition.get('name', '?')}: unknown {sorted(unknown)} / missing {sorted(missing)}")
            try:
                values = {"required_tier": TIER_ANONYMOUS, "masked_columns": [], "row_limit": 20}
                values.update({key: definition[key] for key in DEFINITION_KEYS if key in definition})
                self._compile(SqlToolDefinition(**values))
            except SqlToolDefinitionError as exc:
                raise InvalidRequestError(str(exc)) from exc
        async with self._database.session() as session:
            for definition in definitions:
                row = await session.get(SqlToolDefinition, definition["name"])
                if row is None:
                    row = SqlToolDefinition(name=definition["name"], enabled=bool(definition.get("enabled", True)))
                    session.add(row)
                for key in DEFINITION_KEYS[1:]:
                    if key in definition:
                        setattr(row, key, definition[key])
                row.required_tier = definition.get("required_tier", "anonymous")
                row.masked_columns = definition.get("masked_columns", [])
                row.row_limit = int(definition.get("row_limit", 20))
                row.updated_by = updated_by
        await self.load()
        return [definition["name"] for definition in definitions]
