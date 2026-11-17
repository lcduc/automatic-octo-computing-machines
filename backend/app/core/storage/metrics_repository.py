"""
Daily metric rollups (OBS-03): aggregates one local day from the raw tables
and stores them in ``metrics_daily``, which is never purged.
"""

# Standard library imports
from datetime import date, datetime
from typing import Any, Dict, List, Sequence

# Third-party imports
from sqlalchemy import ColumnElement, Integer, cast, exists, extract, func, select, true
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

# Local imports
from app.models.chat_turn import LOW_CONFIDENCE, TurnOutcome
from .tables.conversation_tables import Conversation, Feedback, HandoffRequest, Message, TokenUsage
from .tables.knowledge_tables import DOCUMENT_STATUS_FAILED, KnowledgeDocument
from .tables.observability_tables import DailyMetrics, MessageTrace

#: Label for rows without a value in a breakdown (e.g. calls before tiers existed).
UNKNOWN = "unknown"
#: A ``steps_ms`` value that casts to ``integer`` (at most 9 digits, so it cannot overflow).
INTEGER_TEXT = "^[0-9]{1,9}$"
#: Decimals kept for the per-step latency percentiles.
STEP_LATENCY_DECIMALS = 1
#: Rows (ISO weekdays, Monday first) and columns (hours) of the traffic grid.
WEEKDAYS = 7
HOURS_PER_DAY = 24


class MetricsRepository:
    """Aggregation queries over one time range and the rollup table."""

    def __init__(self, session: AsyncSession):
        """
        Args:
            session: Open session (the caller owns the transaction).
        """
        self._session = session

    async def _grouped(self, column, where, value=None, aggregate=None) -> Dict[str, Any]:
        """``{group: count-or-value}`` for one breakdown (``aggregate`` overrides the count or sum)."""
        if aggregate is None:
            aggregate = func.count() if value is None else func.coalesce(func.sum(value), 0)
        result = await self._session.execute(select(column, aggregate).where(*where).group_by(column))
        return {str(key) if key is not None else UNKNOWN: int(amount) for key, amount in result.all()}

    async def aggregate(self, start: datetime, end: datetime) -> Dict[str, Any]:
        """Every daily metric for ``[start, end)``, shaped like a ``metrics_daily`` row (without the day)."""
        answers = (Message.role == "assistant", Message.created_at >= start, Message.created_at < end)
        answered = Message.outcome == TurnOutcome.ANSWERED.value
        turns, errors, p50, p95, cited, low_confidence, cached = (
            await self._session.execute(
                select(
                    func.count(),
                    func.count().filter(Message.outcome == "error"),
                    func.percentile_cont(0.5).within_group(Message.latency_ms),
                    func.percentile_cont(0.95).within_group(Message.latency_ms),
                    func.count().filter(answered, func.jsonb_array_length(Message.citations) > 0),
                    func.count().filter(answered, Message.confidence < LOW_CONFIDENCE),
                    func.count().filter(answered, Message.cached.is_(True)),
                ).where(*answers)
            )
        ).one()
        conversations = await self._session.scalar(
            select(func.count(func.distinct(Message.conversation_id))).where(Message.created_at >= start, Message.created_at < end)
        )
        usage_window = (TokenUsage.created_at >= start, TokenUsage.created_at < end)
        prompt_tokens, completion_tokens, cost = (
            await self._session.execute(
                select(
                    func.coalesce(func.sum(TokenUsage.prompt_tokens), 0),
                    func.coalesce(func.sum(TokenUsage.completion_tokens), 0),
                    func.coalesce(func.sum(TokenUsage.cost_micro_usd), 0),
                ).where(*usage_window)
            )
        ).one()
        traces = (MessageTrace.created_at >= start, MessageTrace.created_at < end)
        first_token = cast(MessageTrace.steps_ms["first_token"].astext, Integer)
        p95_first_token = await self._session.scalar(
            select(func.percentile_cont(0.95).within_group(first_token)).where(*traces, first_token.is_not(None))
        )
        handoffs = (HandoffRequest.created_at >= start, HandoffRequest.created_at < end)
        handoff_reasons = await self._grouped(HandoffRequest.reason, handoffs)
        conversations_handed_off = await self._session.scalar(
            select(func.count(func.distinct(HandoffRequest.conversation_id))).where(*handoffs)
        )
        feedback = await self._grouped(Feedback.rating, (Feedback.created_at >= start, Feedback.created_at < end))
        ingestion_failures = await self._session.scalar(
            select(func.count()).where(
                KnowledgeDocument.status == DOCUMENT_STATUS_FAILED,
                KnowledgeDocument.processed_at >= start,
                KnowledgeDocument.processed_at < end,
            )
        )
        return {
            "turns": int(turns),
            "conversations": int(conversations or 0),
            "errors": int(errors),
            "handoffs": sum(handoff_reasons.values()),
            "p50_latency_ms": float(p50) if p50 is not None else None,
            "p95_latency_ms": float(p95) if p95 is not None else None,
            "p95_first_token_ms": float(p95_first_token) if p95_first_token is not None else None,
            "prompt_tokens": int(prompt_tokens),
            "completion_tokens": int(completion_tokens),
            "cost_micro_usd": int(cost),
            "breakdown": {
                "outcomes": await self._grouped(Message.outcome, answers),
                "cost_by_model": await self._grouped(TokenUsage.model, usage_window, TokenUsage.cost_micro_usd),
                "cost_by_tier": await self._grouped(TokenUsage.tier, usage_window, TokenUsage.cost_micro_usd),
                "tokens_by_purpose": await self._grouped(
                    TokenUsage.purpose, usage_window, TokenUsage.prompt_tokens + TokenUsage.completion_tokens
                ),
                "handoff_reasons": handoff_reasons,
                "conversations_handed_off": int(conversations_handed_off or 0),
                "cited_answers": int(cited),
                "low_confidence_answers": int(low_confidence),
                "cached_answers": int(cached),
                "guard_reasons": await self._grouped(
                    Message.guard_reason, (*answers, Message.guard_reason.is_not(None))
                ),
                "step_latency_ms": await self._step_latency(traces),
                "routes": await self._grouped(MessageTrace.route, traces),
                "intents": await self._grouped(MessageTrace.intent, traces),
                "feedback": {"positive": feedback.get("1", 0), "negative": feedback.get("-1", 0)},
                "ingestion_failures": int(ingestion_failures or 0),
                **await self.visitor_stats(start, end),
            },
        }

    async def visitor_stats(self, start: datetime, end: datetime) -> Dict[str, Any]:
        """
        Visitor counts for ``[start, end)``.

        Returns:
            ``visitors`` (distinct ``end_user_id`` with a message in the window), ``returning_visitors``
            (those with a conversation created before ``start``), ``visitors_by_tier`` (distinct
            ``end_user_id`` per tier in ``token_usage``) and ``single_turn_conversations`` (created in the
            window, exactly one assistant message in total, no handoff request).
        """
        window_visitors = (
            select(Conversation.end_user_id)
            .join(Message, Message.conversation_id == Conversation.id)
            .where(Message.created_at >= start, Message.created_at < end)
            .distinct()
            .subquery()
        )
        seen_before = exists().where(
            Conversation.end_user_id == window_visitors.c.end_user_id, Conversation.created_at < start
        )
        visitors, returning_visitors = (
            await self._session.execute(select(func.count(), func.count().filter(seen_before)).select_from(window_visitors))
        ).one()
        answers = (
            select(func.count())
            .where(Message.conversation_id == Conversation.id, Message.role == "assistant")
            .scalar_subquery()
        )
        handed_off = exists().where(HandoffRequest.conversation_id == Conversation.id)
        single_turn = await self._session.scalar(
            select(func.count()).where(
                Conversation.created_at >= start, Conversation.created_at < end, answers == 1, ~handed_off
            )
        )
        visitors_by_tier = await self._grouped(
            TokenUsage.tier,
            (TokenUsage.created_at >= start, TokenUsage.created_at < end, TokenUsage.end_user_id.is_not(None)),
            aggregate=func.count(func.distinct(TokenUsage.end_user_id)),
        )
        return {
            "visitors": int(visitors),
            "returning_visitors": int(returning_visitors),
            "visitors_by_tier": visitors_by_tier,
            "single_turn_conversations": int(single_turn or 0),
        }

    async def traffic(self, start: datetime, end: datetime, timezone: str) -> List[List[int]]:
        """
        User messages in ``[start, end)`` per local weekday and hour.

        Args:
            start: Window start (aware).
            end: Window end (aware).
            timezone: IANA zone the weekday and hour are read in.

        Returns:
            A 7x24 grid of counts: row 0 is Monday, column ``h`` the hour starting at ``h``:00 local time.
        """
        local = func.timezone(timezone, Message.created_at)
        weekday, hour = extract("isodow", local), extract("hour", local)
        result = await self._session.execute(
            select(weekday, hour, func.count())
            .where(Message.role == "user", Message.created_at >= start, Message.created_at < end)
            .group_by(weekday, hour)
        )
        grid = [[0] * HOURS_PER_DAY for _ in range(WEEKDAYS)]
        for day, hour_of_day, count in result.all():
            grid[int(day) - 1][int(hour_of_day)] = int(count)
        return grid

    async def _step_latency(self, traces: Sequence[ColumnElement[bool]]) -> Dict[str, Dict[str, float]]:
        """``{step: {"p50", "p95"}}`` over every integer value of the traces' ``steps_ms``."""
        steps = func.jsonb_each_text(MessageTrace.steps_ms).table_valued("key", "value").lateral("step")
        duration = cast(steps.c.value, Integer)
        result = await self._session.execute(
            select(
                steps.c.key,
                func.percentile_cont(0.5).within_group(duration),
                func.percentile_cont(0.95).within_group(duration),
            )
            .select_from(MessageTrace)
            .join(steps, true())
            .where(*traces, steps.c.value.regexp_match(INTEGER_TEXT))
            .group_by(steps.c.key)
        )
        return {
            step: {"p50": round(float(p50), STEP_LATENCY_DECIMALS), "p95": round(float(p95), STEP_LATENCY_DECIMALS)}
            for step, p50, p95 in result.all()
        }

    async def upsert(self, day: date, values: Dict[str, Any]) -> None:
        """Store (or replace) one day's rollup."""
        statement = insert(DailyMetrics).values(day=day, **values)
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[DailyMetrics.day],
                set_={**{key: statement.excluded[key] for key in values}, "updated_at": func.now()},
            )
        )

    async def latest_day(self) -> date | None:
        """The newest rolled-up day, or ``None`` before the first rollup."""
        return await self._session.scalar(select(func.max(DailyMetrics.day)))

    async def first_activity(self) -> datetime | None:
        """When the first message was stored (the backfill start)."""
        return await self._session.scalar(select(func.min(Message.created_at)))

    async def history(self, since: date) -> List[DailyMetrics]:
        """Rollups from ``since`` on, oldest first."""
        result = await self._session.execute(select(DailyMetrics).where(DailyMetrics.day >= since).order_by(DailyMetrics.day))
        return list(result.scalars().all())
