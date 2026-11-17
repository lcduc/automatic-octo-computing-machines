"""
Database access for the admin audit log (insert, filtered listing and the security summary).
"""

# Standard library imports
from datetime import datetime
from http import HTTPStatus
from typing import Any, Dict, List, Optional, Tuple

# Third-party imports
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

# Local imports
from .tables.audit_tables import AdminAuditEntry

#: ``LIKE`` patterns of the audited admin endpoints counted by :meth:`AuditRepository.summary`
#: (the middleware records full paths such as ``/api/v1/admin/auth/login``).
LOGIN_PATH_PATTERN = "%/auth/login"
PASSWORD_CHANGE_PATH_PATTERN = "%/auth/password"
CONTACT_REVEAL_PATH_PATTERN = "%/handoffs/%/reveal-contact"
API_KEYS_PATH_PATTERN = "%/api-keys%"
ADMIN_USERS_PATH_PATTERN = "%/users%"
DATA_SUBJECTS_PATH_PATTERN = "%/data-subjects/%"
LEGAL_HOLD_PATH_PATTERN = "%/legal-hold"
#: Status range counted as a completed change (2xx).
SUCCESS_STATUS_MIN = HTTPStatus.OK.value
SUCCESS_STATUS_MAX = HTTPStatus.MULTIPLE_CHOICES.value - 1


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

    async def summary(self, since: datetime) -> Dict[str, int]:
        """
        Security counts since ``since`` in one pass over the log.

        Failed logins are ``POST …/auth/login`` answered 401 and ``denied`` is any
        audited request answered 403; every other category counts 2xx only.
        """
        entry = AdminAuditEntry
        succeeded = entry.status_code.between(SUCCESS_STATUS_MIN, SUCCESS_STATUS_MAX)
        login = (entry.method == "POST", entry.path.like(LOGIN_PATH_PATTERN))
        result = await self._session.execute(
            select(
                func.count().filter(*login, entry.status_code == HTTPStatus.UNAUTHORIZED.value).label("logins_failed"),
                func.count().filter(*login, succeeded).label("logins_succeeded"),
                func.count()
                .filter(entry.method == "POST", entry.path.like(CONTACT_REVEAL_PATH_PATTERN), succeeded)
                .label("contact_reveals"),
                func.count().filter(entry.path.like(API_KEYS_PATH_PATTERN), succeeded).label("api_key_changes"),
                func.count()
                .filter(
                    or_(entry.path.like(ADMIN_USERS_PATH_PATTERN), entry.path.like(PASSWORD_CHANGE_PATH_PATTERN)),
                    succeeded,
                )
                .label("account_changes"),
                func.count().filter(entry.method == "DELETE", succeeded).label("deletions"),
                func.count()
                .filter(entry.method == "POST", entry.path.like(DATA_SUBJECTS_PATH_PATTERN), succeeded)
                .label("data_subject_requests"),
                func.count().filter(entry.path.like(LEGAL_HOLD_PATH_PATTERN), succeeded).label("legal_hold_changes"),
                func.count().filter(entry.status_code == HTTPStatus.FORBIDDEN.value).label("denied"),
            ).where(entry.created_at >= since)
        )
        return {key: int(value) for key, value in result.one()._mapping.items()}

    async def failed_login_ips(self, since: datetime, limit: int) -> List[Dict[str, Any]]:
        """Client IPs with the most failed sign-ins since ``since``, most first (unknown IPs left out)."""
        failures = func.count(AdminAuditEntry.id)
        result = await self._session.execute(
            select(AdminAuditEntry.client_ip, failures.label("count"))
            .where(
                AdminAuditEntry.created_at >= since,
                AdminAuditEntry.method == "POST",
                AdminAuditEntry.path.like(LOGIN_PATH_PATTERN),
                AdminAuditEntry.status_code == HTTPStatus.UNAUTHORIZED.value,
                AdminAuditEntry.client_ip.is_not(None),
            )
            .group_by(AdminAuditEntry.client_ip)
            .order_by(failures.desc(), AdminAuditEntry.client_ip)
            .limit(limit)
        )
        return [{"client_ip": ip, "count": int(count)} for ip, count in result.all()]
