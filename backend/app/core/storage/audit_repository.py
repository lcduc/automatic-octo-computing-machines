"""
Database access for the admin audit log (insert and filtered listing only).
"""

# Standard library imports
from datetime import datetime
from typing import List, Optional, Tuple

# Third-party imports
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

# Local imports
from .tables.audit_tables import AdminAuditEntry


class AuditRepository:
    """Queries on ``admin_audit_log``; the table is append-only, so there is no update or delete."""

    def __init__(self, session: AsyncSession):
        """
        Args:
            session: Session whose transaction the caller owns.
        """
        self._session = session

    def add(self, entry: AdminAuditEntry) -> None:
        """Stage a new entry."""
        self._session.add(entry)

    @staticmethod
    def _filtered(
        query: Select, actor: Optional[str], method: Optional[str], path_contains: Optional[str], since: Optional[datetime]
    ) -> Select:
        """Apply the listing filters to ``query``."""
        if actor:
            query = query.where(AdminAuditEntry.actor_email.ilike(f"%{actor}%"))
        if method:
            query = query.where(AdminAuditEntry.method == method.upper())
        if path_contains:
            query = query.where(AdminAuditEntry.path.contains(path_contains))
        if since:
            query = query.where(AdminAuditEntry.created_at >= since)
        return query

    async def list(
        self,
        actor: Optional[str],
        method: Optional[str],
        path_contains: Optional[str],
        since: Optional[datetime],
        limit: int,
        offset: int,
    ) -> Tuple[List[AdminAuditEntry], int]:
        """A page of entries, newest first, plus the total matching the filters."""
        total = await self._session.execute(
            self._filtered(select(func.count(AdminAuditEntry.id)), actor, method, path_contains, since)
        )
        rows = await self._session.execute(
            self._filtered(select(AdminAuditEntry), actor, method, path_contains, since)
            .order_by(AdminAuditEntry.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(rows.scalars().all()), int(total.scalar_one())
