"""
Token budgets, the monthly spend cap and usage statistics.

Budgets and spend are counters in PostgreSQL (see :class:`RateLimitService`):
tokens per visitor or signed-in user per local day, tokens per client IP per
day (so clearing cookies does not reset a budget), and spend for everyone per
month. Anonymous visitors are paused first as the spend cap nears.
"""

# Standard library imports
import logging
from datetime import date, datetime, time as dt_time, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

# Local imports
from app.config.settings import Config
from app.core.storage.conversation_repository import ConversationRepository
from app.core.storage.database import Database
from app.core.storage.metrics_repository import MetricsRepository
from app.core.storage.tables.usage_tables import WINDOW_DAY, WINDOW_HOUR, WINDOW_MINUTE, WINDOW_MONTH
from app.models.caller import ChatCaller
from app.models.usage_policy import MICRO_USD_PER_USD, UsagePolicy
from .rate_limit_service import Limit, RateLimitService, hashed

logger = logging.getLogger(__name__)

#: Counter holding everyone's LLM spend.
SPEND_SCOPE = "spend:all"
#: Month elapsed before spend is projected; earlier, a few hours of traffic extrapolate wildly.
MIN_PROJECTION_ELAPSED = timedelta(days=1)


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


def project_month_spend(
    spent_micro_usd: int, now: datetime, month_start: datetime, month_end: datetime
) -> Optional[int]:
    """
    Month-end spend if the month continues at its average pace so far.

    Args:
        spent_micro_usd: Spend from ``month_start`` until ``now``.
        now: The current moment (aware).
        month_start: Start of the current local month (aware).
        month_end: Start of the next local month (aware).

    Returns:
        Projected spend in micro-USD, or ``None`` during the month's first day.
    """
    # ceiling: linear projection, ignores weekday/seasonal patterns; fit on daily rollups if clients plan budgets from it
    elapsed = now.astimezone(timezone.utc) - month_start.astimezone(timezone.utc)
    if elapsed < MIN_PROJECTION_ELAPSED:
        return None
    month = month_end.astimezone(timezone.utc) - month_start.astimezone(timezone.utc)
    return round(spent_micro_usd * (month / elapsed))


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

    def _month(self, spend: Dict[str, int], spend_cap_usd: float) -> Dict[str, Any]:
        """This month's spend with its month-end projection and the cap (``0`` = no cap)."""
        buckets = self._counters.buckets
        now = buckets.now()
        start = buckets.start(WINDOW_MONTH, now)
        projected = project_month_spend(spend["cost_micro_usd"], now, start, buckets.end(WINDOW_MONTH, start))
        return {
            **spend,
            "projected_cost_micro_usd": projected,
            "spend_cap_micro_usd": round(max(0.0, spend_cap_usd) * MICRO_USD_PER_USD),
        }

    async def summary(self, days: int, spend_cap_usd: float) -> Dict[str, Any]:
        """
        Dashboard statistics for the last ``days`` local days.

        Args:
            days: Local days to cover, today included.
            spend_cap_usd: The monthly spend cap (``0`` = no cap), reported with this month's spend.

        Returns:
            Daily tokens and cost per model, tokens per purpose, cost per tier,
            outcome and feedback counts, latency percentiles, visitors, single-turn
            conversations, user messages per local weekday and hour (``traffic``,
            7x24, Monday first), totals and this month's spend with its projection
            and the cap.
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
            metrics = MetricsRepository(session)
            now = self._counters.buckets.now()
            visitors = await metrics.visitor_stats(since, now)
            traffic = await metrics.traffic(since, now, self._timezone.key)
        return {
            "since": since.isoformat(),
            "daily": [{**row, "day": row["day"].isoformat()} for row in daily],
            "by_purpose": by_purpose,
            "by_tier": by_tier,
            "outcomes": outcomes,
            "feedback": feedback,
            "latency": latency,
            "visitors": {
                "total": visitors["visitors"],
                "returning": visitors["returning_visitors"],
                "by_tier": visitors["visitors_by_tier"],
            },
            "single_turn_conversations": visitors["single_turn_conversations"],
            "traffic": traffic,
            "totals": self._totals(daily),
            "month": self._month(await self.month_spend(), spend_cap_usd),
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
