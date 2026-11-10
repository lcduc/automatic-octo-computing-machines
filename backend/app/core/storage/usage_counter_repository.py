"""
Database access for time-bucketed usage counters.
"""

# Standard library imports
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Sequence, Tuple

# Third-party imports
from sqlalchemy import delete, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

# Local imports
from .tables.usage_tables import UsageCounter

#: ``(scope_key, window, bucket_start)``.
CounterKey = Tuple[str, str, datetime]


@dataclass(frozen=True)
class CounterTotals:
    """What one counter bucket holds."""

    requests: int = 0
    tokens: int = 0
    cost_micro_usd: int = 0


class UsageCounterRepository:
    """Upserts and reads counter buckets, bound to one session."""

    def __init__(self, session: AsyncSession):
        """
        Args:
            session: Open session; the caller commits or rolls back.
        """
        self._session = session

    async def add(
        self, keys: Sequence[CounterKey], requests: int = 0, tokens: int = 0, cost_micro_usd: int = 0
    ) -> Dict[CounterKey, CounterTotals]:
        """
        Add to every bucket in ``keys`` in one statement and return the new totals.

        Duplicate keys are merged first (one statement may not update a row twice).
        """
        unique = list(dict.fromkeys(keys))
        if not unique:
            return {}
        statement = insert(UsageCounter).values([
            {"scope_key": key, "window": window, "bucket_start": start,
             "requests": requests, "tokens": tokens, "cost_micro_usd": cost_micro_usd}
            for key, window, start in unique
        ])
        statement = statement.on_conflict_do_update(
            index_elements=[UsageCounter.scope_key, UsageCounter.window, UsageCounter.bucket_start],
            set_={
                "requests": UsageCounter.requests + statement.excluded.requests,
                "tokens": UsageCounter.tokens + statement.excluded.tokens,
                "cost_micro_usd": UsageCounter.cost_micro_usd + statement.excluded.cost_micro_usd,
            },
        ).returning(
            UsageCounter.scope_key, UsageCounter.window, UsageCounter.bucket_start,
            UsageCounter.requests, UsageCounter.tokens, UsageCounter.cost_micro_usd,
        )
        result = await self._session.execute(statement)
        return {(row[0], row[1], row[2]): CounterTotals(row[3], row[4], row[5]) for row in result.all()}

    async def totals(self, keys: Sequence[CounterKey]) -> Dict[CounterKey, CounterTotals]:
        """Current totals of ``keys`` (buckets never written read as zero)."""
        unique = list(dict.fromkeys(keys))
        if not unique:
            return {}
        result = await self._session.execute(
            select(
                UsageCounter.scope_key, UsageCounter.window, UsageCounter.bucket_start,
                UsageCounter.requests, UsageCounter.tokens, UsageCounter.cost_micro_usd,
            ).where(tuple_(UsageCounter.scope_key, UsageCounter.window, UsageCounter.bucket_start).in_(unique))
        )
        found = {(row[0], row[1], row[2]): CounterTotals(row[3], row[4], row[5]) for row in result.all()}
        return {key: found.get(key, CounterTotals()) for key in unique}

    async def purge_before(self, cutoff: datetime) -> int:
        """Delete buckets that started before ``cutoff``; returns how many."""
        result = await self._session.execute(delete(UsageCounter).where(UsageCounter.bucket_start < cutoff))
        return int(result.rowcount or 0)
