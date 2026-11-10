"""
Async PostgreSQL connection pool shared by the whole process.
"""

# Standard library imports
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

# Third-party imports
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

logger = logging.getLogger(__name__)

#: Extra connections allowed above the pool size under burst load.
POOL_MAX_OVERFLOW = 5
#: Recycle connections periodically so a restarted database is picked up cleanly.
POOL_RECYCLE_SECONDS = 1800


class Database:
    """
    Owns the async engine and session factory.

    Construction is cheap; the engine (and its connection pool) is only
    created by :meth:`connect`, which the application lifecycle calls once.
    """

    def __init__(self, url: str, pool_size: int):
        """
        Args:
            url: SQLAlchemy async URL (``postgresql+asyncpg://…``).
            pool_size: Connections kept open in the pool.
        """
        self._url = url
        self._pool_size = pool_size
        self._engine: Optional[AsyncEngine] = None
        self._sessionmaker: Optional[async_sessionmaker[AsyncSession]] = None

    @property
    def engine(self) -> AsyncEngine:
        """The connected engine; raises if :meth:`connect` was not called."""
        if self._engine is None:
            raise RuntimeError("Database is not connected")
        return self._engine

    def connect(self) -> None:
        """Create the engine and session factory (idempotent)."""
        if self._engine is not None:
            return
        self._engine = create_async_engine(
            self._url,
            pool_size=self._pool_size,
            max_overflow=POOL_MAX_OVERFLOW,
            pool_pre_ping=True,
            pool_recycle=POOL_RECYCLE_SECONDS,
        )
        self._sessionmaker = async_sessionmaker(self._engine, expire_on_commit=False)
        logger.info("Database engine created (pool_size=%d)", self._pool_size)

    async def ping(self) -> bool:
        """Return True when a trivial query succeeds."""
        try:
            async with self.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            return True
        except Exception:
            logger.exception("Database ping failed")
            return False

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """
        Yield a session that commits on success and rolls back on error.

        Yields:
            An ``AsyncSession`` bound to the pool.
        """
        if self._sessionmaker is None:
            raise RuntimeError("Database is not connected")
        async with self._sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def close(self) -> None:
        """Dispose of the pool."""
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._sessionmaker = None
            logger.info("Database engine disposed")
