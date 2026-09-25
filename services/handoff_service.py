"""
Transfer-to-human requests.

Today a handoff is recorded, the conversation is flagged and the admin web is
notified live; staff follow up from the Handoffs page. Connecting a real
live-agent channel (Zalo OA, e-mail, a helpdesk) means extending
:meth:`HandoffService.notify` — the chat flow already calls it for every
new request.
"""

# Standard library imports
import logging
import uuid
from typing import List, Optional, Tuple

# Local imports
from core.storage.conversation_repository import ConversationRepository
from core.storage.database import Database
from core.storage.tables.conversation_tables import (
    CONVERSATION_STATUS_ACTIVE,
    CONVERSATION_STATUS_HANDOFF,
    HANDOFF_STATUS_PENDING,
    HANDOFF_STATUS_RESOLVED,
    Conversation,
    HandoffRequest,
)
from .errors import InvalidRequestError, NotFoundError
from .usage_service import UsageService

logger = logging.getLogger(__name__)

#: Statuses an admin may set on a handoff request.
HANDOFF_STATUSES = ("pending", "in_progress", "resolved")


class HandoffService:
    """Creates, lists and resolves handoff requests."""

    def __init__(self, database: Database, live_feed: UsageService):
        """
        Args:
            database: Connected database.
            live_feed: Broadcasts new requests to admin dashboards.
        """
        self._database = database
        self._live_feed = live_feed

    @staticmethod
    def open_request(
        repository: ConversationRepository,
        conversation: Conversation,
        message_id: uuid.UUID,
        reason: str,
    ) -> HandoffRequest:
        """
        Stage a new pending request inside the caller's transaction.

        Args:
            repository: Repository bound to the caller's session.
            conversation: Conversation being handed off (its status is updated).
            message_id: Assistant message that announced the handoff.
            reason: ``no_knowledge`` or ``user_request``.
        """
        request = HandoffRequest(
            conversation_id=conversation.id,
            message_id=message_id,
            reason=reason,
            status=HANDOFF_STATUS_PENDING,
        )
        repository.add(request)
        conversation.status = CONVERSATION_STATUS_HANDOFF
        return request

    def notify(self, request: HandoffRequest) -> None:
        """
        Tell staff about a new request (after it was committed).

        Extension point for a real live-agent integration.
        """
        logger.info("Handoff requested for conversation %s (%s)", request.conversation_id, request.reason)
        self._live_feed.publish(
            {
                "type": "handoff",
                "handoff_id": str(request.id),
                "conversation_id": str(request.conversation_id),
                "reason": request.reason,
            }
        )

    async def list(self, status: Optional[str], limit: int, offset: int) -> Tuple[List[HandoffRequest], int]:
        """Requests newest first, optionally filtered by status."""
        async with self._database.session() as session:
            return await ConversationRepository(session).list_handoffs(status, limit, offset)

    async def update(self, handoff_id: uuid.UUID, status: str, note: Optional[str], updated_by: str) -> HandoffRequest:
        """
        Change a request's status (resolving it re-activates the conversation).

        Raises:
            NotFoundError: Unknown request.
            InvalidRequestError: Unknown status.
        """
        if status not in HANDOFF_STATUSES:
            raise InvalidRequestError(f"status must be one of {', '.join(HANDOFF_STATUSES)}")
        async with self._database.session() as session:
            repository = ConversationRepository(session)
            request = await repository.get_handoff(handoff_id)
            if request is None:
                raise NotFoundError("Handoff request not found")
            request.status = status
            if note is not None:
                request.note = note
            if status == HANDOFF_STATUS_RESOLVED:
                conversation = await repository.get_conversation(request.conversation_id)
                if conversation is not None:
                    conversation.status = CONVERSATION_STATUS_ACTIVE
        logger.info("Handoff %s set to %s by %s", handoff_id, status, updated_by)
        return request
