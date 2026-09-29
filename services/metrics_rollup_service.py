"""
Daily metrics rollup (OBS-03): keeps dashboard history after raw messages,
usage rows and traces are purged by retention.
"""

# Standard library imports
import logging
from datetime import date, datetime, time as dt_time, timedelta
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

# Local imports
from core.storage.database import Database
from core.storage.metrics_repository import MetricsRepository

logger = logging.getLogger(__name__)

#: Days recomputed on every run: late writes (a turn finishing after midnight) land in yesterday.
RECOMPUTED_DAYS = 2
#: Longest backfill on the first run, so an old database does not stall the worker.
MAX_BACKFILL_DAYS = 400


class MetricsRollupService:
    """Computes and reads the ``metrics_daily`` rows."""

    def __init__(self, database: Database, timezone: str):
        """
        Args:
            database: Connected database.
            timezone: IANA zone whose midnights bound a day (the app time zone).
        """
        self._database = database
        self._timezone = ZoneInfo(timezone)

    def _today(self) -> date:
        """The current local date."""
        return datetime.now(self._timezone).date()

    def _bounds(self, day: date) -> tuple[datetime, datetime]:
        """Local midnight of ``day`` and of the next day."""
        start = datetime.combine(day, dt_time.min, tzinfo=self._timezone)
        return start, datetime.combine(day + timedelta(days=1), dt_time.min, tzinfo=self._timezone)

    async def rollup_day(self, day: date) -> Dict[str, Any]:
        """Aggregate one local day and store it; returns the stored values."""
        start, end = self._bounds(day)
        async with self._database.session() as session:
            repository = MetricsRepository(session)
            values = await repository.aggregate(start, end)
            await repository.upsert(day, values)
        return values

    async def run(self) -> int:
        """
        Roll up the recent days, backfilling any gap since the last run.

        Returns:
            How many days were written.
        """
        today = self._today()
        async with self._database.session() as session:
            repository = MetricsRepository(session)
            latest = await repository.latest_day()
            first_activity = await repository.first_activity()
        if latest is not None:
            first_day = min(latest, today - timedelta(days=RECOMPUTED_DAYS - 1))
        elif first_activity is not None:
            first_day = max(first_activity.astimezone(self._timezone).date(), today - timedelta(days=MAX_BACKFILL_DAYS))
        else:
            first_day = today
        days = [first_day + timedelta(days=offset) for offset in range((today - first_day).days + 1)]
        logger.info("Rolling up metrics for %d day(s) from %s", len(days), first_day)
        for day in days:
            await self.rollup_day(day)
        return len(days)

    async def history(self, days: int) -> List[Dict[str, Any]]:
        """The last ``days`` rollups (oldest first) for the dashboards."""
        async with self._database.session() as session:
            rows = await MetricsRepository(session).history(self._today() - timedelta(days=days - 1))
        return [
            {
                "day": row.day.isoformat(),
                "turns": row.turns,
                "conversations": row.conversations,
                "errors": row.errors,
                "handoffs": row.handoffs,
                "p50_latency_ms": row.p50_latency_ms,
                "p95_latency_ms": row.p95_latency_ms,
                "p95_first_token_ms": row.p95_first_token_ms,
                "prompt_tokens": row.prompt_tokens,
                "completion_tokens": row.completion_tokens,
                "cost_micro_usd": row.cost_micro_usd,
                "breakdown": row.breakdown,
            }
            for row in rows
        ]
