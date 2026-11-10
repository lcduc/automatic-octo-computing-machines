"""
Daily metric rollups (OBS-03): aggregates one local day from the raw tables
and stores them in ``metrics_daily``, which is never purged.
"""

# Standard library imports
from datetime import date, datetime
from typing import Any, Dict, List

# Third-party imports
from sqlalchemy import Integer, cast, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

# Local imports
from .tables.conversation_tables import Feedback, HandoffRequest, Message, TokenUsage
from .tables.knowledge_tables import DOCUMENT_STATUS_FAILED, KnowledgeDocument
from .tables.observability_tables import DailyMetrics, MessageTrace

#: Label for rows without a value in a breakdown (e.g. calls before tiers existed).
UNKNOWN = "unknown"


class MetricsRepository:
    """Aggregation queries over one time range and the rollup table."""

    def __init__(self, session: AsyncSession):
        """
        Args:
            session: Open session (the caller owns the transaction).
        """
        self._session = session

    async def _grouped(self, column, where, value=None) -> Dict[str, Any]:
        """``{group: count-or-value}`` for one breakdown."""
        aggregate = func.count() if value is None else func.coalesce(func.sum(value), 0)
        result = await self._session.execute(select(column, aggregate).where(*where).group_by(column))
        return {str(key) if key is not None else UNKNOWN: int(amount) for key, amount in result.all()}

    async def aggregate(self, start: datetime, end: datetime) -> Dict[str, Any]:
        """Every daily metric for ``[start, end)``, shaped like a ``metrics_daily`` row (without the day)."""
        answers = (Message.role == "assistant", Message.created_at >= start, Message.created_at < end)
        turns, errors, p50, p95 = (
            await self._session.execute(
                select(
                    func.count(),
                    func.count().filter(Message.outcome == "error"),
                    func.percentile_cont(0.5).within_group(Message.latency_ms),
                    func.percentile_cont(0.95).within_group(Message.latency_ms),
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
        handoff_reasons = await self._grouped(
            HandoffRequest.reason, (HandoffRequest.created_at >= start, HandoffRequest.created_at < end)
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
                "routes": await self._grouped(MessageTrace.route, traces),
                "intents": await self._grouped(MessageTrace.intent, traces),
                "feedback": {"positive": feedback.get("1", 0), "negative": feedback.get("-1", 0)},
                "ingestion_failures": int(ingestion_failures or 0),
            },
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
