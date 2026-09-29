"""
Runs a SQL tool's template against the business database, read-only and time-boxed (TOOL-03/05).

Every query runs in its own transaction that is ``READ ONLY`` with a
``statement_timeout``, and with ``app.user_id`` set to the verified caller so
row-level security policies can filter per-user tables (the role is expected
to have SELECT on views only). Parameters are always bound, never formatted
into the SQL text.
"""

# Standard library imports
import logging
from typing import Any, Dict, List, Optional, Tuple

# Third-party imports
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError

# Local imports
from core.storage.database import Database

logger = logging.getLogger(__name__)


class SqlToolTimeoutError(RuntimeError):
    """The query ran longer than the statement timeout."""


class SqlToolExecutor:
    """Executes tool templates on the business database."""

    def __init__(self, database: Database, statement_timeout_ms: int):
        """
        Args:
            database: Connected business database (a read-only role).
            statement_timeout_ms: Per-query limit enforced by PostgreSQL.
        """
        self._database = database
        self._statement_timeout_ms = statement_timeout_ms

    async def fetch(
        self, template: str, parameters: Dict[str, Any], user_id: Optional[str], max_rows: int
    ) -> Tuple[List[Dict[str, Any]], bool]:
        """
        Run ``template`` and return at most ``max_rows`` rows.

        Returns:
            ``(rows, truncated)``.

        Raises:
            SqlToolTimeoutError: The statement timeout cancelled the query.
            DBAPIError: Any other database failure.
        """
        try:
            async with self._database.session() as session:
                # Must be the transaction's first statement.
                await session.execute(text("SET TRANSACTION READ ONLY"))
                await session.execute(
                    text("SELECT set_config('statement_timeout', :timeout, true), set_config('app.user_id', :user_id, true)"),
                    {"timeout": f"{self._statement_timeout_ms}ms", "user_id": user_id or ""},
                )
                result = await session.execute(text(template), parameters)
                rows = [dict(row) for row in result.mappings().fetchmany(max_rows + 1)]
        except (OperationalError, DBAPIError) as exc:
            if "statement timeout" in str(exc).lower() or "canceling statement" in str(exc).lower():
                logger.warning("SQL tool query timed out after %d ms", self._statement_timeout_ms)
                raise SqlToolTimeoutError(f"query took longer than {self._statement_timeout_ms} ms") from exc
            raise
        return rows[:max_rows], len(rows) > max_rows
