"""
Database access for conversations, messages, feedback, handoffs and token usage.
"""

# Standard library imports
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Third-party imports
from sqlalchemy import Date, cast, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

# Local imports
from .tables.conversation_tables import Conversation, Feedback, HandoffRequest, Message, TokenUsage


class ConversationRepository:
    """Queries over conversation tables, bound to one session."""

    def __init__(self, session: AsyncSession):
        """
        Args:
            session: Open session; the caller commits or rolls back.
        """
        self._session = session

    def add(self, entity: Any) -> None:
        """Stage a new entity for insertion."""
        self._session.add(entity)

    def add_all(self, entities: Sequence[Any]) -> None:
        """Stage several new entities for insertion."""
        self._session.add_all(list(entities))

    async def flush(self) -> None:
        """Send pending changes so generated keys become available."""
        await self._session.flush()

    # ------------------------------------------------------------------
    # Conversations and messages
    # ------------------------------------------------------------------

    async def get_conversation(self, conversation_id: uuid.UUID) -> Optional[Conversation]:
        """Conversation by id (messages not loaded)."""
        return await self._session.get(Conversation, conversation_id)

    async def recent_messages(self, conversation_id: uuid.UUID, limit: int) -> List[Message]:
        """The last ``limit`` messages of a conversation, oldest first."""
        result = await self._session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        return list(reversed(result.scalars().all()))

    async def get_message(self, message_id: uuid.UUID) -> Optional[Message]:
        """Message by id with its conversation and feedback."""
        result = await self._session.execute(
            select(Message)
            .where(Message.id == message_id)
            .options(selectinload(Message.conversation), selectinload(Message.feedback))
        )
        return result.scalar_one_or_none()

    async def list_conversations(
        self,
        outcome: Optional[str],
        status: Optional[str],
        since: Optional[datetime],
        limit: int,
        offset: int,
    ) -> Tuple[List[Conversation], int]:
        """
        Conversations newest-activity first, optionally only those containing a
        message with ``outcome`` (e.g. ``denied``) or in ``status``.
        """
        statement = select(Conversation)
        count_statement = select(func.count(Conversation.id))
        conditions = []
        if outcome:
            conditions.append(
                Conversation.id.in_(select(Message.conversation_id).where(Message.outcome == outcome))
            )
        if status:
            conditions.append(Conversation.status == status)
        if since:
            conditions.append(Conversation.last_activity_at >= since)
        if conditions:
            statement = statement.where(*conditions)
            count_statement = count_statement.where(*conditions)
        total = (await self._session.execute(count_statement)).scalar_one()
        result = await self._session.execute(
            statement.order_by(Conversation.last_activity_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all()), int(total)

    async def conversation_with_messages(self, conversation_id: uuid.UUID) -> Optional[Conversation]:
        """Conversation with all messages and their feedback, oldest first."""
        result = await self._session.execute(
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .options(selectinload(Conversation.messages).selectinload(Message.feedback))
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Feedback
    # ------------------------------------------------------------------

    async def upsert_feedback(self, message_id: uuid.UUID, rating: int, comment: Optional[str]) -> None:
        """Insert or replace the feedback on a message (one per message)."""
        statement = insert(Feedback).values(id=uuid.uuid4(), message_id=message_id, rating=rating, comment=comment)
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[Feedback.message_id],
                set_={"rating": rating, "comment": comment, "created_at": func.now()},
            )
        )

    async def list_feedback(
        self, rating: Optional[int], limit: int, offset: int
    ) -> Tuple[List[Tuple[Feedback, Message]], int]:
        """Feedback newest first, joined with the rated assistant message."""
        statement = select(Feedback, Message).join(Message, Feedback.message_id == Message.id)
        count_statement = select(func.count(Feedback.id))
        if rating is not None:
            statement = statement.where(Feedback.rating == rating)
            count_statement = count_statement.where(Feedback.rating == rating)
        total = (await self._session.execute(count_statement)).scalar_one()
        result = await self._session.execute(
            statement.order_by(Feedback.created_at.desc()).limit(limit).offset(offset)
        )
        return [(feedback, message) for feedback, message in result.all()], int(total)

    async def questions_for(self, assistant_messages: Sequence[Message]) -> Dict[uuid.UUID, str]:
        """
        The user message that preceded each assistant message, in one query.

        Returns:
            Assistant message id -> question text (missing when none precedes it).
        """
        conversation_ids = {message.conversation_id for message in assistant_messages}
        if not conversation_ids:
            return {}
        result = await self._session.execute(
            select(Message.conversation_id, Message.created_at, Message.content)
            .where(Message.conversation_id.in_(conversation_ids), Message.role == "user")
            .order_by(Message.created_at)
        )
        questions_by_conversation: Dict[uuid.UUID, List[Tuple[datetime, str]]] = {}
        for conversation_id, created_at, content in result.all():
            questions_by_conversation.setdefault(conversation_id, []).append((created_at, content))
        answers: Dict[uuid.UUID, str] = {}
        for message in assistant_messages:
            earlier = [text for created, text in questions_by_conversation.get(message.conversation_id, [])
                       if created <= message.created_at]
            if earlier:
                answers[message.id] = earlier[-1]
        return answers

    # ------------------------------------------------------------------
    # Handoffs
    # ------------------------------------------------------------------

    async def get_handoff(self, handoff_id: uuid.UUID) -> Optional[HandoffRequest]:
        """Handoff request by id."""
        return await self._session.get(HandoffRequest, handoff_id)

    async def list_handoffs(self, status: Optional[str], limit: int, offset: int) -> Tuple[List[HandoffRequest], int]:
        """Handoff requests newest first, optionally filtered by status."""
        statement = select(HandoffRequest)
        count_statement = select(func.count(HandoffRequest.id))
        if status:
            statement = statement.where(HandoffRequest.status == status)
            count_statement = count_statement.where(HandoffRequest.status == status)
        total = (await self._session.execute(count_statement)).scalar_one()
        result = await self._session.execute(
            statement.order_by(HandoffRequest.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all()), int(total)

    # ------------------------------------------------------------------
    # Token usage and statistics
    # ------------------------------------------------------------------

    async def tokens_used_since(self, end_user_id: str, since: datetime) -> int:
        """Prompt + completion tokens an end user consumed since ``since``."""
        result = await self._session.execute(
            select(func.coalesce(func.sum(TokenUsage.prompt_tokens + TokenUsage.completion_tokens), 0)).where(
                TokenUsage.end_user_id == end_user_id, TokenUsage.created_at >= since
            )
        )
        return int(result.scalar_one())

    async def usage_by_day(self, since: datetime) -> List[Dict[str, Any]]:
        """Daily token totals per model since ``since``."""
        day = cast(TokenUsage.created_at, Date)
        result = await self._session.execute(
            select(
                day.label("day"),
                TokenUsage.model,
                func.sum(TokenUsage.prompt_tokens).label("prompt_tokens"),
                func.sum(TokenUsage.completion_tokens).label("completion_tokens"),
                func.count(TokenUsage.id).label("calls"),
            )
            .where(TokenUsage.created_at >= since)
            .group_by(day, TokenUsage.model)
            .order_by(day)
        )
        return [dict(row._mapping) for row in result.all()]

    async def usage_by_purpose(self, since: datetime) -> List[Dict[str, Any]]:
        """Token totals per call purpose (answer, rewrite, …) since ``since``."""
        result = await self._session.execute(
            select(
                TokenUsage.purpose,
                func.sum(TokenUsage.prompt_tokens + TokenUsage.completion_tokens).label("tokens"),
                func.count(TokenUsage.id).label("calls"),
            )
            .where(TokenUsage.created_at >= since)
            .group_by(TokenUsage.purpose)
        )
        return [dict(row._mapping) for row in result.all()]

    async def outcome_counts(self, since: datetime) -> Dict[str, int]:
        """Assistant messages per outcome since ``since``."""
        result = await self._session.execute(
            select(Message.outcome, func.count(Message.id))
            .where(Message.role == "assistant", Message.created_at >= since)
            .group_by(Message.outcome)
        )
        return {outcome or "unknown": int(count) for outcome, count in result.all()}

    async def feedback_counts(self, since: datetime) -> Dict[str, int]:
        """Thumbs up / down counts since ``since``."""
        result = await self._session.execute(
            select(Feedback.rating, func.count(Feedback.id)).where(Feedback.created_at >= since).group_by(Feedback.rating)
        )
        counts = {int(rating): int(count) for rating, count in result.all()}
        return {"positive": counts.get(1, 0), "negative": counts.get(-1, 0)}

    async def latency_percentiles(self, since: datetime) -> Dict[str, Optional[float]]:
        """p50/p95 latency of assistant messages since ``since``."""
        result = await self._session.execute(
            select(
                func.percentile_cont(0.5).within_group(Message.latency_ms),
                func.percentile_cont(0.95).within_group(Message.latency_ms),
                func.count(func.distinct(Message.conversation_id)),
            ).where(Message.role == "assistant", Message.created_at >= since, Message.latency_ms.is_not(None))
        )
        p50, p95, conversations = result.one()
        return {
            "p50_ms": float(p50) if p50 is not None else None,
            "p95_ms": float(p95) if p95 is not None else None,
            "conversations": int(conversations or 0),
        }
