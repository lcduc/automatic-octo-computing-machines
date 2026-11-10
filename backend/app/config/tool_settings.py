"""
Settings of the SQL tool layer: the client's business database and its safety limits.
"""

# Local imports
from .env import env_int, env_str


class BusinessDbConfig:
    """Read-only access to the client's business database."""

    @staticmethod
    def BUSINESS_DB_URL() -> str:
        """SQLAlchemy async URL of a read-only role (``postgresql+asyncpg://…``); empty = no SQL tools."""
        return env_str("BUSINESS_DB_URL", "")

    @staticmethod
    def SQL_TOOL_STATEMENT_TIMEOUT_MS() -> int:
        """Longest a tool query may run before the database cancels it."""
        return env_int("SQL_TOOL_STATEMENT_TIMEOUT_MS", 3000)

    @staticmethod
    def SQL_TOOL_MAX_RESULT_CHARS() -> int:
        """Longest tool result handed to the model (keeps the context budget)."""
        return env_int("SQL_TOOL_MAX_RESULT_CHARS", 6000)

    @staticmethod
    def BUSINESS_DB_POOL_SIZE() -> int:
        """Connections kept to the business database."""
        return env_int("BUSINESS_DB_POOL_SIZE", 3)
