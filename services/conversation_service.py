"""
Reading conversations (visitor and admin views) and collecting feedback.
"""

# Standard library imports
import logging
import uuid
from datetime import datetime
from typing import List, Optional, Tuple

# Local imports
from core.storage.conversation_repository import ConversationRepository
from core.storage.database import Database
from core.storage.tables.base import utc_now
from core.storage.tables.conversation_tables import Conversation, Feedback, Message, TokenUsage
from core.storage.tables.observability_tables import MessageTrace
from models.caller import ChatCaller
from models.chat_turn import FALLBACK_MODE_HANDOFF, HandoffReason
from .errors import InvalidRequestError, NotFoundError

logger = logging.getLogger(__name__)

#: Longest accepted feedback comment.
MAX_FEEDBACK_COMMENT_LENGTH = 1000
#: Consecutive thumbs-down that open a ticket.
NEGATIVE_STREAK = 2


class ConversationService:
    """Conversation queries and feedback."""

    def __init__(self, database: Database, handoffs=None, settings=None):
        """
        Args:
            database: Connected database.
            handoffs: Opens a ticket after repeated thumbs-down (HND-04); ``None`` disables it.
            settings: Runtime policy (whether handoff is on).
        """
        self._database = database
        self._handoffs = handoffs
        self._settings = settings

    async def visitor_conversation(self, conversation_id: uuid.UUID, caller: ChatCaller) -> Conversation:
        """
        The caller's own conversation with its messages (to restore the widget).

        Raises:
            NotFoundError: Unknown id, or it belongs to someone else (including
                a logged-in user's conversation after they logged out, ID-09).
        """
        async with self._database.session() as session:
            conversation = await ConversationRepository(session).conversation_with_messages(conversation_id)
        if conversation is None or not caller.owns(conversation.user_id, conversation.end_user_id):
            raise NotFoundError("Conversation not found")
        return conversation

    async def submit_feedback(
        self, message_id: uuid.UUID, caller: ChatCaller, rating: int, comment: Optional[str]
    ) -> Optional[uuid.UUID]:
        """
        Record (or replace) a visitor's rating of an assistant message.

        Raises:
            NotFoundError: Unknown message or not in the visitor's conversation.
            InvalidRequestError: Rating a user message, or a bad rating value.
        """
        if rating not in (1, -1):
            raise InvalidRequestError("rating must be 1 or -1")
        async with self._database.session() as session:
            repository = ConversationRepository(session)
            message = await repository.get_message(message_id)
            if message is None or not caller.owns(message.conversation.user_id, message.conversation.end_user_id):
                raise NotFoundError("Message not found")
            if message.role != "assistant":
                raise InvalidRequestError("Only assistant messages can be rated")
            await repository.upsert_feedback(message_id, rating, (comment or "")[:MAX_FEEDBACK_COMMENT_LENGTH] or None)
            conversation_id = message.conversation_id
            recent = await repository.last_ratings(conversation_id, NEGATIVE_STREAK) if rating < 0 else []
        logger.info("Feedback %+d recorded for message %s", rating, message_id)
        if len(recent) == NEGATIVE_STREAK and all(value < 0 for value in recent) and self._handoff_on():
            ticket = await self._handoffs.open_unless_active(
                conversation_id, message_id, HandoffReason.NEGATIVE_FEEDBACK.value, caller.user_id
            )
            return ticket.id if ticket is not None else None
        return None

    def _handoff_on(self) -> bool:
        """Whether this deployment hands conversations to people."""
        return self._handoffs is not None and self._settings.chat_policy().fallback_mode == FALLBACK_MODE_HANDOFF

    async def list_conversations(
        self, outcome: Optional[str], status: Optional[str], since: Optional[datetime], limit: int, offset: int
    ) -> Tuple[List[Conversation], int]:
        """Admin list of conversations, newest activity first."""
        async with self._database.session() as session:
            return await ConversationRepository(session).list_conversations(outcome, status, since, limit, offset)

    async def conversation_detail(self, conversation_id: uuid.UUID) -> Conversation:
        """
        Admin view of one conversation with every message and its feedback.

        Raises:
            NotFoundError: Unknown conversation.
        """
        async with self._database.session() as session:
            conversation = await ConversationRepository(session).conversation_with_messages(conversation_id)
        if conversation is None:
            raise NotFoundError("Conversation not found")
        return conversation

    async def message_trace(self, message_id: uuid.UUID) -> Tuple[MessageTrace, List[TokenUsage]]:
        """
        What the pipeline did for one answer (ADM-05) and the LLM calls it made.

        Raises:
            NotFoundError: No trace (unknown message, a user message, or purged).
        """
        async with self._database.session() as session:
            repository = ConversationRepository(session)
            trace = await repository.message_trace(message_id)
            if trace is None:
                raise NotFoundError("No trace for this message")
            return trace, await repository.message_usage(message_id)

    async def list_feedback(
        self, rating: Optional[int], limit: int, offset: int, reviewed: Optional[bool] = None
    ) -> Tuple[List[Tuple[Feedback, Message, Optional[str]]], int]:
        """
        Admin feedback inbox: each rating with the rated answer and the question asked.

        Returns:
            ``([(feedback, assistant_message, question)], total)``.
        """
        async with self._database.session() as session:
            repository = ConversationRepository(session)
            rows, total = await repository.list_feedback(rating, limit, offset, reviewed)
            questions = await repository.questions_for([message for _, message in rows])
        return [(feedback, message, questions.get(message.id)) for feedback, message in rows], total

    async def mark_feedback_reviewed(self, feedback_id: uuid.UUID, reviewed: bool, reviewed_by: str) -> Feedback:
        """
        Mark a rating as looked at (ADM-12), or back to unreviewed.

        Raises:
            NotFoundError: Unknown rating.
        """
        async with self._database.session() as session:
            feedback = await ConversationRepository(session).get_feedback(feedback_id)
            if feedback is None:
                raise NotFoundError("Feedback not found")
            feedback.reviewed_at = utc_now() if reviewed else None
            feedback.reviewed_by = reviewed_by if reviewed else None
        return feedback
