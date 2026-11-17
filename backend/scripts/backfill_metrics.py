"""
Recompute the daily metric rollups for the last N local days.

Usage (from backend/, with the venv active, or inside the api container):

    python -m scripts.backfill_metrics            # the last 90 days
    python -m scripts.backfill_metrics --days 30

Run it after a release adds rollup keys, so days rolled up earlier get them too. Only days whose
raw rows still exist come out complete: messages, usage rows and traces older than the retention
periods are already purged, and re-running such a day would overwrite its row with lower counts.
So ``--days`` is capped at the shortest of the chat, anonymous-chat and trace retention periods.
"""

# Standard library imports
import argparse
import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

# Local imports
from app.config.settings import Config
from app.core.storage.database import Database
from app.models.retention_policy import RetentionPolicy
from app.services.metrics_rollup_service import MetricsRollupService
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)

#: Default span: the trace retention, the shortest-lived raw rows the rollup reads.
DEFAULT_DAYS = 90
#: One connection is enough for a sequential backfill.
BACKFILL_POOL_SIZE = 1


def backfill_days(today: date, days: int) -> List[date]:
    """The last ``days`` local days up to ``today``, oldest first."""
    return [today - timedelta(days=offset) for offset in range(max(1, days) - 1, -1, -1)]


def complete_days(policy: RetentionPolicy) -> int:
    """Past local days (today included) whose messages, usage rows and traces are all still stored."""
    return min(policy.chat_days, policy.anonymous_chat_days, policy.trace_days)


class MetricsBackfill:
    """Re-runs the daily rollup over a range of past days."""

    def __init__(self, rollup: MetricsRollupService, timezone: str):
        """
        Args:
            rollup: The rollup service that computes and stores one day.
            timezone: IANA zone whose dates are rolled up (the app time zone).
        """
        self._rollup = rollup
        self._timezone = ZoneInfo(timezone)

    async def run(self, days: int, policy: RetentionPolicy) -> int:
        """
        Recompute the last ``days`` local days, oldest first, never a day retention already purged.

        Args:
            days: Local days requested, today included.
            policy: The current retention periods (they cap ``days``).

        Returns:
            How many days were written.
        """
        allowed = complete_days(policy)
        if days > allowed:
            logger.warning("Capping the backfill at %d days: older raw rows are purged by retention", allowed)
            days = allowed
        today = datetime.now(self._timezone).date()
        targets = backfill_days(today, days)
        logger.info("Backfilling metrics for %d day(s) from %s", len(targets), targets[0])
        for day in targets:
            values = await self._rollup.rollup_day(day)
            logger.info("Rolled up %s: %d turns, %d conversations", day, values["turns"], values["conversations"])
        logger.info("Backfill finished")
        return len(targets)


async def _backfill(days: int) -> int:
    """Connect, backfill and close the pool."""
    database = Database(Config.Database.DATABASE_URL(), BACKFILL_POOL_SIZE)
    database.connect()
    try:
        settings = SettingsService(database)
        await settings.load()
        timezone = Config.Server.APP_TIMEZONE()
        backfill = MetricsBackfill(MetricsRollupService(database, timezone), timezone)
        return await backfill.run(days, settings.retention_policy())
    finally:
        await database.close()


def main(argv: Optional[List[str]] = None) -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Recompute the daily metric rollups for the last N days")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help=f"local days to recompute (default {DEFAULT_DAYS})")
    args = parser.parse_args(argv)
    if args.days < 1:
        parser.error("--days must be at least 1")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    written = asyncio.run(_backfill(args.days))
    # Intentional CLI output.
    print(f"Rolled up {written} day(s)")


if __name__ == "__main__":
    main()
