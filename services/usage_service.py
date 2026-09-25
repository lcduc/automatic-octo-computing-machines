"""
Token accounting: daily per-user budgets, the live usage feed and usage statistics.
"""

# Standard library imports
import asyncio
import logging
from datetime import date, datetime, time as dt_time, timedelta
from typing import Any, Dict, List, Set, Tuple
from zoneinfo import ZoneInfo

# Local imports
from config.settings import Config
from core.storage.conversation_repository import ConversationRepository
from core.storage.database import Database

logger = logging.getLogger(__name__)

#: Events buffered per live-feed subscriber before new ones are dropped.
LIVE_QUEUE_SIZE = 200


class UsageService:
    """
    Tracks tokens per end user per local day and fans usage events out to
    admin dashboards listening on the live feed.

    # ceiling: budget counters and subscribers live in this process (single
    # worker); move to Redis pub/sub + counters if the API is scaled out.
    """

    def __init__(self, database: Database):
        """
        Args:
            database: Connected database (used to seed counters after a restart).
        """
        self._database = database
        self._timezone = ZoneInfo(Config.Server.APP_TIMEZONE())
        self._daily_tokens: Dict[Tuple[str, date], int] = {}
        self._subscribers: Set[asyncio.Queue] = set()

    def _today(self) -> date:
        """Current date in the application time zone."""
        return datetime.now(self._timezone).date()

    def _start_of(self, day: date) -> datetime:
        """Local midnight of ``day`` as an aware datetime."""
        return datetime.combine(day, dt_time.min, tzinfo=self._timezone)

    async def tokens_used_today(self, end_user_id: str) -> int:
        """Tokens an end user consumed today (seeded from the database once per day)."""
        today = self._today()
        key = (end_user_id, today)
        if key not in self._daily_tokens:
            self._daily_tokens = {k: v for k, v in self._daily_tokens.items() if k[1] == today}
            async with self._database.session() as session:
                used = await ConversationRepository(session).tokens_used_since(end_user_id, self._start_of(today))
            self._daily_tokens[key] = used
        return self._daily_tokens[key]

    async def within_budget(self, end_user_id: str) -> bool:
        """True when the user may still spend tokens today."""
        budget = Config.Security.DAILY_TOKEN_BUDGET_PER_USER()
        return budget <= 0 or await self.tokens_used_today(end_user_id) < budget

    def add(self, end_user_id: str, tokens: int) -> None:
        """Count tokens just spent by a user (after they were persisted)."""
        key = (end_user_id, self._today())
        self._daily_tokens[key] = self._daily_tokens.get(key, 0) + tokens

    # ------------------------------------------------------------------
    # Live feed
    # ------------------------------------------------------------------

    def subscribe(self) -> asyncio.Queue:
        """Register a live-feed listener; pair with :meth:`unsubscribe`."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=LIVE_QUEUE_SIZE)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        """Remove a live-feed listener."""
        self._subscribers.discard(queue)

    def publish(self, event: Dict[str, Any]) -> None:
        """Push an event to every listener, dropping it for listeners that fell behind."""
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.debug("Live usage listener is behind; dropping an event")

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    async def summary(self, days: int) -> Dict[str, Any]:
        """
        Dashboard statistics for the last ``days`` local days.

        Returns:
            Daily tokens per model, tokens per purpose, outcome and feedback
            counts, latency percentiles and today's totals.
        """
        today = self._today()
        since = self._start_of(today - timedelta(days=max(1, days) - 1))
        async with self._database.session() as session:
            repository = ConversationRepository(session)
            daily = await repository.usage_by_day(since)
            by_purpose = await repository.usage_by_purpose(since)
            outcomes = await repository.outcome_counts(since)
            feedback = await repository.feedback_counts(since)
            latency = await repository.latency_percentiles(since)
        return {
            "since": since.isoformat(),
            "daily": [{**row, "day": row["day"].isoformat()} for row in daily],
            "by_purpose": by_purpose,
            "outcomes": outcomes,
            "feedback": feedback,
            "latency": latency,
            "totals": self._totals(daily),
        }

    @staticmethod
    def _totals(daily: List[Dict[str, Any]]) -> Dict[str, int]:
        """Sum the daily rows."""
        return {
            "prompt_tokens": int(sum(row["prompt_tokens"] or 0 for row in daily)),
            "completion_tokens": int(sum(row["completion_tokens"] or 0 for row in daily)),
            "calls": int(sum(row["calls"] or 0 for row in daily)),
        }
