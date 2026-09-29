"""
Queries behind data-subject requests (PRV-03) and legal hold (RET-R2).
"""

# Standard library imports
import uuid
from typing import List, Optional, Sequence

# Third-party imports
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

# Local imports
from models.data_subject import DataSubject
from .tables.conversation_tables import Conversation, HandoffRequest, Message, TokenUsage


class PrivacyRepository:
    """Finds, exports and deletes one person's conversations and tickets."""

    def __init__(self, session: AsyncSession):
        """
        Args:
            session: Open session (the caller owns the transaction).
        """
        self._session = session

    async def get_conversation(self, conversation_id: uuid.UUID) -> Optional[Conversation]:
        """One conversation by id."""
        return await self._session.get(Conversation, conversation_id)

    async def get_ticket(self, ticket_id: uuid.UUID) -> Optional[HandoffRequest]:
        """One ticket by id."""
        return await self._session.get(HandoffRequest, ticket_id)

    async def tickets(self, subject: DataSubject) -> List[HandoffRequest]:
        """Tickets the person opened (as the signed-in user, the visitor, or by contact e-mail)."""
        matches = []
        if subject.user_id:
            matches.append(HandoffRequest.user_id == subject.user_id)
        if subject.email:
            matches.append(func.lower(HandoffRequest.contact_email) == subject.email.lower())
        if subject.visitor_id:
            visitor_conversations = select(Conversation.id).where(Conversation.end_user_id == subject.visitor_id)
            matches.append(HandoffRequest.conversation_id.in_(visitor_conversations))
        result = await self._session.execute(select(HandoffRequest).where(or_(*matches)).order_by(HandoffRequest.created_at))
        return list(result.scalars().all())

    async def conversations(self, subject: DataSubject, ticket_conversation_ids: Sequence[uuid.UUID]) -> List[Conversation]:
        """The person's conversations with messages and feedback, plus those behind their tickets."""
        matches = [Conversation.id.in_(ticket_conversation_ids)] if ticket_conversation_ids else []
        if subject.user_id:
            matches.append(Conversation.user_id == subject.user_id)
        if subject.visitor_id:
            matches.append(Conversation.end_user_id == subject.visitor_id)
        if not matches:
            return []
        result = await self._session.execute(
            select(Conversation)
            .where(or_(*matches))
            .options(selectinload(Conversation.messages).selectinload(Message.feedback))
            .order_by(Conversation.created_at)
        )
        return list(result.scalars().unique().all())

    async def delete_tickets(self, ticket_ids: Sequence[uuid.UUID]) -> int:
        """Delete tickets by id; returns how many."""
        if not ticket_ids:
            return 0
        result = await self._session.execute(delete(HandoffRequest).where(HandoffRequest.id.in_(ticket_ids)))
        return int(result.rowcount or 0)

    async def delete_conversations(self, conversation_ids: Sequence[uuid.UUID]) -> int:
        """Delete conversations by id (messages, feedback, traces and tickets cascade); returns how many."""
        if not conversation_ids:
            return 0
        result = await self._session.execute(delete(Conversation).where(Conversation.id.in_(conversation_ids)))
        return int(result.rowcount or 0)

    async def delete_visitor_usage(self, visitor_id: str) -> int:
        """Per-call usage rows keyed by the visitor id; returns how many."""
        result = await self._session.execute(delete(TokenUsage).where(TokenUsage.end_user_id == visitor_id))
        return int(result.rowcount or 0)
