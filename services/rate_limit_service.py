"""
Request limits and usage totals kept in PostgreSQL time buckets.

Each check adds one request to every bucket it names (per minute, hour, day
or month) in a single upsert and compares the new counts with the limits, so
limits are exact across restarts and across several API processes. Days and
months follow the application time zone, so "per day" means the local day.

# ceiling: fixed windows allow up to 2x a limit across a bucket boundary;
# switch to a two-bucket sliding estimate if bursts at boundaries matter.
"""

# Standard library imports
import hashlib
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

# Local imports
from core.storage.database import Database
from core.storage.tables.usage_tables import WINDOW_DAY, WINDOW_HOUR, WINDOW_MINUTE, WINDOW_MONTH
from core.storage.usage_counter_repository import CounterKey, CounterTotals, UsageCounterRepository

logger = logging.getLogger(__name__)

#: Characters of a SHA-256 kept when an IP or e-mail is part of a counter key (never stored in clear).
KEY_HASH_LENGTH = 24


def hashed(value: str) -> str:
    """Stable, non-reversible stand-in for personal data inside counter keys."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:KEY_HASH_LENGTH]


@dataclass(frozen=True)
class Limit:
    """At most ``limit`` requests for ``scope_key`` per ``window`` (``limit <= 0`` disables it)."""

    scope_key: str
    window: str
    limit: int


class TimeBuckets:
    """Bucket boundaries in the application time zone."""

    def __init__(self, time_zone: str, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        """
        Args:
            time_zone: IANA zone that days and months follow.
            clock: Current UTC time (injectable for tests).
        """
        self._zone = ZoneInfo(time_zone)
        self._clock = clock

    def now(self) -> datetime:
        """The current moment in the application zone."""
        return self._clock().astimezone(self._zone)

    def start(self, window: str, moment: Optional[datetime] = None) -> datetime:
        """Start of the bucket containing ``moment`` (default: now)."""
        local = (moment or self.now()).astimezone(self._zone)
        if window == WINDOW_MINUTE:
            return local.replace(second=0, microsecond=0)
        if window == WINDOW_HOUR:
            return local.replace(minute=0, second=0, microsecond=0)
        if window == WINDOW_DAY:
            return local.replace(hour=0, minute=0, second=0, microsecond=0)
        if window == WINDOW_MONTH:
            return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        raise ValueError(f"Unknown window {window!r}")

    def end(self, window: str, start: datetime) -> datetime:
        """Start of the bucket after ``start``."""
        if window == WINDOW_MINUTE:
            return start + timedelta(minutes=1)
        if window == WINDOW_HOUR:
            return start + timedelta(hours=1)
        if window == WINDOW_DAY:
            return (start + timedelta(days=1, hours=2)).replace(hour=0)
        if window == WINDOW_MONTH:
            return (start + timedelta(days=32)).replace(day=1)
        raise ValueError(f"Unknown window {window!r}")


class RateLimitService:
    """Checks limits and accumulates tokens/cost in the ``usage_counters`` table."""

    def __init__(self, database: Database, buckets: TimeBuckets):
        """
        Args:
            database: Connected database.
            buckets: Bucket boundaries (application time zone).
        """
        self._database = database
        self._buckets = buckets

    @property
    def buckets(self) -> TimeBuckets:
        """The bucket calendar in use."""
        return self._buckets

    def key(self, scope_key: str, window: str) -> CounterKey:
        """The current bucket of ``scope_key`` in ``window``."""
        return scope_key, window, self._buckets.start(window)

    async def hit(self, limits: Sequence[Limit]) -> Optional[int]:
        """
        Count one request against every active limit.

        Returns:
            ``None`` when all are within bounds, else seconds until the
            tightest exceeded bucket ends (for ``Retry-After``).
        """
        active = [limit for limit in limits if limit.limit > 0]
        if not active:
            return None
        keys = {limit: self.key(limit.scope_key, limit.window) for limit in active}
        async with self._database.session() as session:
            totals = await UsageCounterRepository(session).add(list(keys.values()), requests=1)
        exceeded = [limit for limit in active if totals[keys[limit]].requests > limit.limit]
        if not exceeded:
            return None
        now = self._buckets.now()
        waits = [self._buckets.end(limit.window, keys[limit][2]) - now for limit in exceeded]
        logger.warning("Rate limit hit: %s", ", ".join(f"{limit.scope_key.split(':')[0]}/{limit.window}" for limit in exceeded))
        return max(1, math.ceil(max(wait.total_seconds() for wait in waits)))

    async def add_usage(self, scopes: Sequence[Tuple[str, str]], tokens: int, cost_micro_usd: int) -> None:
        """Add tokens and cost to the current bucket of each ``(scope_key, window)``."""
        keys = [self.key(scope_key, window) for scope_key, window in scopes]
        async with self._database.session() as session:
            await UsageCounterRepository(session).add(keys, tokens=tokens, cost_micro_usd=cost_micro_usd)

    async def totals(self, scopes: Sequence[Tuple[str, str]]) -> Dict[Tuple[str, str], CounterTotals]:
        """Current-bucket totals of each ``(scope_key, window)``."""
        keys = {scope: self.key(*scope) for scope in scopes}
        async with self._database.session() as session:
            found = await UsageCounterRepository(session).totals(list(keys.values()))
        return {scope: found[key] for scope, key in keys.items()}

    async def purge_before(self, cutoff: datetime) -> int:
        """Delete counter buckets older than ``cutoff`` (they can no longer affect a limit)."""
        async with self._database.session() as session:
            return await UsageCounterRepository(session).purge_before(cutoff)
