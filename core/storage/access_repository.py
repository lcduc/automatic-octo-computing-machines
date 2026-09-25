"""
Database access for API keys and admin users.
"""

# Standard library imports
import uuid
from typing import List, Optional

# Third-party imports
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# Local imports
from .tables.access_tables import AdminUser, ApiKey


class AccessRepository:
    """Queries over access-control tables, bound to one session."""

    def __init__(self, session: AsyncSession):
        """
        Args:
            session: Open session; the caller commits or rolls back.
        """
        self._session = session

    def add(self, entity) -> None:
        """Stage a new entity for insertion."""
        self._session.add(entity)

    async def flush(self) -> None:
        """Send pending changes so generated keys become available."""
        await self._session.flush()

    async def api_key_by_hash(self, key_hash: str) -> Optional[ApiKey]:
        """Active or revoked key by its SHA-256 hash."""
        result = await self._session.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
        return result.scalar_one_or_none()

    async def get_api_key(self, key_id: uuid.UUID) -> Optional[ApiKey]:
        """Key by id."""
        return await self._session.get(ApiKey, key_id)

    async def list_api_keys(self) -> List[ApiKey]:
        """All keys, newest first."""
        result = await self._session.execute(select(ApiKey).order_by(ApiKey.created_at.desc()))
        return list(result.scalars().all())

    async def admin_by_email(self, email: str) -> Optional[AdminUser]:
        """Admin by e-mail (case-insensitive)."""
        result = await self._session.execute(select(AdminUser).where(func.lower(AdminUser.email) == email.lower()))
        return result.scalar_one_or_none()

    async def get_admin(self, admin_id: uuid.UUID) -> Optional[AdminUser]:
        """Admin by id."""
        return await self._session.get(AdminUser, admin_id)

    async def list_admins(self) -> List[AdminUser]:
        """All admins by e-mail."""
        result = await self._session.execute(select(AdminUser).order_by(AdminUser.email))
        return list(result.scalars().all())

    async def count_active_owners(self) -> int:
        """Enabled admins with the owner role."""
        result = await self._session.execute(
            select(func.count(AdminUser.id)).where(AdminUser.role == "owner", AdminUser.disabled.is_(False))
        )
        return int(result.scalar_one())
