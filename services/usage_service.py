"""
Token budgets, the monthly spend cap and usage statistics.

Budgets and spend are counters in PostgreSQL (see :class:`RateLimitService`):
tokens per visitor or signed-in user per local day, tokens per client IP per
day (so clearing cookies does not reset a budget), and spend for everyone per
month. Anonymous visitors are paused first as the spend cap nears.
"""

# Standard library imports
import logging
from datetime import date, datetime, time as dt_time, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

# Local imports
from config.settings import Config
from core.storage.conversation_repository import ConversationRepository
from core.storage.database import Database
from core.storage.tables.usage_tables import WINDOW_DAY, WINDOW_HOUR, WINDOW_MINUTE, WINDOW_MONTH
from models.caller import ChatCaller
from models.usage_policy import UsagePolicy
from .rate_limit_service import Limit, RateLimitService, hashed

logger = logging.getLogger(__name__)

#: Counter holding everyone's LLM spend.
SPEND_SCOPE = "spend:all"


class BudgetVerdict(str, Enum):
    """Whether a caller may start another turn."""

    OK = "ok"
    #: The caller's (or their IP's) daily token budget is used up.
    TOKENS_EXHAUSTED = "tokens_exhausted"
    #: The monthly spend cap stops this caller's tier.
    SPEND_PAUSED = "spend_paused"


def identity_scope(caller: ChatCaller) -> str:
    """Counter identity: the signed-in user, else the visitor."""
    return f"user:{caller.user_id}" if caller.logged_in else f"visitor:{caller.end_user_id}"


def ip_scope(caller: ChatCaller) -> str:
    """Counter identity of the caller's IP (hashed: IPs are personal data)."""
    return f"ip:{hashed(caller.client_ip)}"


class UsageService:
    """Budgets and spend for chat turns, plus the dashboard statistics."""

    def __init__(self, database: Database, counters: RateLimitService):
        """
        Args:
            database: Connected database (statistics).
            counters: Durable counters (limits, budgets, spend).
        """
        self._database = database
        self._counters = counters
        self._timezone = ZoneInfo(Config.Server.APP_TIMEZONE())

    # ------------------------------------------------------------------
    # Limits and budgets
    # ------------------------------------------------------------------

    async def hit_request_limits(self, caller: ChatCaller, policy: UsagePolicy) -> Optional[int]:
        """
        Count one chat message against the caller's per-minute and per-hour limits.

        Returns:
            ``None`` when allowed, else seconds to wait.
        """
        per_minute, per_hour, _ = policy.for_caller(caller.logged_in)
        scope = f"chat:{identity_scope(caller)}"
        return await self._counters.hit([Limit(scope, WINDOW_MINUTE, per_minute), Limit(scope, WINDOW_HOUR, per_hour)])

    async def budget_verdict(self, caller: ChatCaller, policy: UsagePolicy) -> BudgetVerdict:
        """Whether the caller's token budgets and the spend cap allow another turn."""
        tokens_scope = (f"tokens:{identity_scope(caller)}", WINDOW_DAY)
        ip_tokens_scope = (f"tokens:{ip_scope(caller)}", WINDOW_DAY)
        spend_scope = (SPEND_SCOPE, WINDOW_MONTH)
        totals = await self._counters.totals([tokens_scope, ip_tokens_scope, spend_scope])
        spend_limit = policy.spend_limit_micro_usd(caller.logged_in)
        if policy.spend_cap_usd > 0 and totals[spend_scope].cost_micro_usd >= spend_limit:
            logger.warning("Spend cap reached for %s callers", caller.tier)
            return BudgetVerdict.SPEND_PAUSED
        _, _, tokens_per_day = policy.for_caller(caller.logged_in)
        if 0 < tokens_per_day <= totals[tokens_scope].tokens:
            return BudgetVerdict.TOKENS_EXHAUSTED
        if 0 < policy.ip_tokens_per_day <= totals[ip_tokens_scope].tokens:
            return BudgetVerdict.TOKENS_EXHAUSTED
        return BudgetVerdict.OK

    def seconds_until(self, verdict: BudgetVerdict) -> int:
        """``Retry-After`` for a refused turn: the end of the day or the month."""
        window = WINDOW_MONTH if verdict == BudgetVerdict.SPEND_PAUSED else WINDOW_DAY
        buckets = self._counters.buckets
        start = buckets.start(window)
        return max(1, int((buckets.end(window, start) - buckets.now()).total_seconds()))

    async def record_turn(self, caller: ChatCaller, tokens: int, cost_micro_usd: int) -> None:
        """Charge a finished turn's tokens and cost to the caller, their IP and the spend counters."""
        if tokens <= 0 and cost_micro_usd <= 0:
            return
        await self._counters.add_usage(
            [
                (f"tokens:{identity_scope(caller)}", WINDOW_DAY),
                (f"tokens:{ip_scope(caller)}", WINDOW_DAY),
                (SPEND_SCOPE, WINDOW_DAY),
                (SPEND_SCOPE, WINDOW_MONTH),
            ],
            tokens,
            cost_micro_usd,
        )

    async def month_spend(self) -> Dict[str, int]:
        """This month's tokens and cost for everyone."""
        totals = (await self._counters.totals([(SPEND_SCOPE, WINDOW_MONTH)]))[(SPEND_SCOPE, WINDOW_MONTH)]
        return {"tokens": totals.tokens, "cost_micro_usd": totals.cost_micro_usd}

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def _today(self) -> date:
        """Current date in the application time zone."""
        return datetime.now(self._timezone).date()

    def _start_of(self, day: date) -> datetime:
        """Local midnight of ``day`` as an aware datetime."""
        return datetime.combine(day, dt_time.min, tzinfo=self._timezone)

    async def summary(self, days: int) -> Dict[str, Any]:
        """
        Dashboard statistics for the last ``days`` local days.

        Returns:
            Daily tokens and cost per model, tokens per purpose, cost per tier,
            outcome and feedback counts, latency percentiles, totals and this
            month's spend.
        """
        today = self._today()
        since = self._start_of(today - timedelta(days=max(1, days) - 1))
        async with self._database.session() as session:
            repository = ConversationRepository(session)
            daily = await repository.usage_by_day(since)
            by_purpose = await repository.usage_by_purpose(since)
            by_tier = await repository.cost_by_tier(since)
            outcomes = await repository.outcome_counts(since)
            feedback = await repository.feedback_counts(since)
            latency = await repository.latency_percentiles(since)
        return {
            "since": since.isoformat(),
            "daily": [{**row, "day": row["day"].isoformat()} for row in daily],
            "by_purpose": by_purpose,
            "by_tier": by_tier,
            "outcomes": outcomes,
            "feedback": feedback,
            "latency": latency,
            "totals": self._totals(daily),
            "month": await self.month_spend(),
        }

    @staticmethod
    def _totals(daily: List[Dict[str, Any]]) -> Dict[str, int]:
        """Sum the daily rows."""
        return {
            "prompt_tokens": int(sum(row["prompt_tokens"] or 0 for row in daily)),
            "completion_tokens": int(sum(row["completion_tokens"] or 0 for row in daily)),
            "calls": int(sum(row["calls"] or 0 for row in daily)),
            "cost_micro_usd": int(sum(row["cost_micro_usd"] or 0 for row in daily)),
        }
