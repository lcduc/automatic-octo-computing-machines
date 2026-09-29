"""
Checks that the business database role given to the chatbot cannot write (TOOL-05, preflight).
"""

# Standard library imports
import logging
from typing import List

# Third-party imports
import asyncpg
from sqlalchemy.engine import make_url

logger = logging.getLogger(__name__)

WRITE_PRIVILEGES = ("INSERT", "UPDATE", "DELETE", "TRUNCATE")
PROBE_TABLE = "chatbot_write_probe"


class BusinessDbProbe:
    """Connects with the configured role and looks for any way it could change data."""

    def __init__(self, sqlalchemy_url: str):
        """
        Args:
            sqlalchemy_url: ``BUSINESS_DB_URL``.
        """
        self._dsn = make_url(sqlalchemy_url).set(drivername="postgresql").render_as_string(hide_password=False)

    async def problems(self) -> List[str]:
        """Every way the role could write; empty when it is read-only."""
        connection = await asyncpg.connect(self._dsn)
        try:
            issues: List[str] = []
            role = await connection.fetchrow(
                "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname = current_user"
            )
            for flag, label in (("rolsuper", "is a superuser"), ("rolbypassrls", "bypasses row-level security"),
                                ("rolcreaterole", "can create roles"), ("rolcreatedb", "can create databases")):
                if role[flag]:
                    issues.append(f"the role {label}")
            writable = await connection.fetch(
                "SELECT DISTINCT table_schema || '.' || table_name AS name FROM information_schema.table_privileges "
                "WHERE grantee = current_user AND privilege_type = ANY($1::text[])",
                list(WRITE_PRIVILEGES),
            )
            if writable:
                issues.append("write privileges on " + ", ".join(row["name"] for row in writable[:10]))
            issues.extend(await self._write_attempt(connection))
            return issues
        finally:
            await connection.close()

    @staticmethod
    async def _write_attempt(connection: asyncpg.Connection) -> List[str]:
        """Try to create a table inside a transaction that is always rolled back."""
        transaction = connection.transaction()
        await transaction.start()
        try:
            await connection.execute(f"CREATE TABLE {PROBE_TABLE} (id integer)")
            return ["the role can create tables"]
        except asyncpg.PostgresError:
            # Refused, as it should be: read-only transaction or no CREATE privilege.
            logger.info("Write probe refused, as expected")
            return []
        finally:
            await transaction.rollback()
