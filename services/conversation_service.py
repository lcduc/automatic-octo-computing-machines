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
from core.storage.tables.conversation_tables import Conversation, Feedback, Message
from .errors import InvalidRequestError, NotFoundError

logger = logging.getLogger(__name__)

#: Longest accepted feedback comment.
MAX_FEEDBACK_COMMENT_LENGTH = 1000


class ConversationService:
    """Conversation queries and feedback."""

    def __init__(self, database: Database):
        """
        Args:
            database: Connected database.
        """
        self._database = database

    async def visitor_conversation(self, conversation_id: uuid.UUID, end_user_id: str) -> Conversation:
        """
        A visitor's own conversation with its messages (to restore the widget).

        Raises:
            NotFoundError: Unknown id, or it belongs to someone else.
        """
        async with self._database.session() as session:
            conversation = await ConversationRepository(session).conversation_with_messages(conversation_id)
        if conversation is None or conversation.end_user_id != end_user_id:
            raise NotFoundError("Conversation not found")
        return conversation

    async def submit_feedback(
        self, message_id: uuid.UUID, end_user_id: str, rating: int, comment: Optional[str]
    ) -> None:
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
            if message is None or message.conversation.end_user_id != end_user_id:
                raise NotFoundError("Message not found")
            if message.role != "assistant":
                raise InvalidRequestError("Only assistant messages can be rated")
            await repository.upsert_feedback(message_id, rating, (comment or "")[:MAX_FEEDBACK_COMMENT_LENGTH] or None)
        logger.info("Feedback %+d recorded for message %s", rating, message_id)

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

    async def list_feedback(
        self, rating: Optional[int], limit: int, offset: int
    ) -> Tuple[List[Tuple[Feedback, Message, Optional[str]]], int]:
        """
        Admin feedback inbox: each rating with the rated answer and the question asked.

        Returns:
            ``([(feedback, assistant_message, question)], total)``.
        """
        async with self._database.session() as session:
            repository = ConversationRepository(session)
            rows, total = await repository.list_feedback(rating, limit, offset)
            questions = await repository.questions_for([message for _, message in rows])
        return [(feedback, message, questions.get(message.id)) for feedback, message in rows], total
