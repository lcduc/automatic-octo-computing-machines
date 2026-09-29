"""
Daily retention purge (PRV-04, RET-R1): deletes personal data past the
periods the owner set, after refreshing the rollup so dashboard history
never depends on the rows being deleted (RET-R4).
"""

# Standard library imports
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict

# Local imports
from core.storage.database import Database
from core.storage.retention_repository import RetentionRepository
from .metrics_rollup_service import MetricsRollupService
from .rate_limit_service import RateLimitService
from .settings_service import SettingsService

logger = logging.getLogger(__name__)

#: Rate-limit buckets older than this can no longer affect a limit (the longest window is a month).
COUNTER_KEEP_DAYS = 62


def _utc_now() -> datetime:
    """The current time in UTC."""
    return datetime.now(timezone.utc)


class RetentionService:
    """Runs the purge and reports what it deleted."""

    def __init__(
        self,
        database: Database,
        settings: SettingsService,
        rollup: MetricsRollupService,
        rate_limits: RateLimitService,
        clock: Callable[[], datetime] = _utc_now,
    ):
        """
        Args:
            database: Connected database.
            settings: Source of the retention periods (reloaded on every run,
                since the owner edits them in another process).
            rollup: Refreshed before anything is deleted.
            rate_limits: Owner of the usage counters.
            clock: Current UTC time (tests pass a fixed one).
        """
        self._database = database
        self._settings = settings
        self._rollup = rollup
        self._rate_limits = rate_limits
        self._clock = clock

    async def purge(self) -> Dict[str, int]:
        """
        Delete everything past its retention period.

        Returns:
            Deleted row count per data type.

        Raises:
            Exception: Any database error; the scheduler alerts on it and retries next day.
        """
        await self._settings.load()
        policy = self._settings.retention_policy()
        await self._rollup.run()
        now = self._clock()

        def cutoff(days: int) -> datetime:
            return now - timedelta(days=days)

        async with self._database.session() as session:
            repository = RetentionRepository(session)
            counts = {
                "conversations": await repository.delete_conversations(
                    cutoff(policy.chat_days), cutoff(policy.anonymous_chat_days), cutoff(policy.ticket_days)
                ),
                "tickets": await repository.delete_tickets(cutoff(policy.ticket_days)),
                "traces": await repository.delete_traces(cutoff(policy.trace_days)),
                "token_usage": await repository.delete_token_usage(cutoff(policy.trace_days)),
                "audit_entries": await repository.delete_audit_entries(cutoff(policy.audit_days)),
                "host_token_bindings": await repository.delete_expired_token_bindings(),
            }
        counts["usage_counters"] = await self._rate_limits.purge_before(cutoff(COUNTER_KEEP_DAYS))
        logger.info("Retention purge deleted %s", counts)
        return counts
