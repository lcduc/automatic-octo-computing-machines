"""
Bulk deletes behind the retention purge (PRV-04). Anything under legal hold,
and conversations whose tickets are still kept, survive.
"""

# Standard library imports
from datetime import datetime

# Third-party imports
from sqlalchemy import and_, delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

# Local imports
from .tables.access_tables import HostTokenUse
from .tables.audit_tables import AdminAuditEntry
from .tables.conversation_tables import HANDOFF_ACTIVE_STATUSES, Conversation, HandoffRequest, TokenUsage
from .tables.observability_tables import MessageTrace


def _held_conversation_ids():
    """Ids of conversations under legal hold."""
    return select(Conversation.id).where(Conversation.legal_hold.is_(True))


class RetentionRepository:
    """One ``DELETE`` per data type; each returns how many rows went."""

    def __init__(self, session: AsyncSession):
        """
        Args:
            session: Open session (the caller owns the transaction).
        """
        self._session = session

    async def _count(self, statement) -> int:
        """Run a delete and return its row count."""
        result = await self._session.execute(statement.execution_options(synchronize_session=False))
        return int(result.rowcount or 0)

    async def delete_conversations(self, user_cutoff: datetime, anonymous_cutoff: datetime, ticket_cutoff: datetime) -> int:
        """
        Conversations idle since before their cutoff (signed-in vs anonymous),
        not on hold and with no ticket that is on hold, still open or younger
        than ``ticket_cutoff``. Messages, feedback and traces cascade.
        """
        kept_ticket = exists().where(
            HandoffRequest.conversation_id == Conversation.id,
            or_(
                HandoffRequest.legal_hold.is_(True),
                HandoffRequest.status.in_(HANDOFF_ACTIVE_STATUSES),
                HandoffRequest.created_at >= ticket_cutoff,
            ),
        )
        idle = or_(
            and_(Conversation.user_id.is_not(None), Conversation.last_activity_at < user_cutoff),
            and_(Conversation.user_id.is_(None), Conversation.last_activity_at < anonymous_cutoff),
        )
        return await self._count(
            delete(Conversation).where(Conversation.legal_hold.is_(False), idle, ~kept_ticket)
        )

    async def delete_tickets(self, cutoff: datetime) -> int:
        """Closed tickets opened before ``cutoff``, unless they or their conversation are on hold."""
        return await self._count(
            delete(HandoffRequest).where(
                HandoffRequest.created_at < cutoff,
                HandoffRequest.legal_hold.is_(False),
                HandoffRequest.status.not_in(HANDOFF_ACTIVE_STATUSES),
                HandoffRequest.conversation_id.not_in(_held_conversation_ids()),
            )
        )

    async def delete_traces(self, cutoff: datetime) -> int:
        """Per-answer traces older than ``cutoff`` outside held conversations."""
        return await self._count(
            delete(MessageTrace).where(
                MessageTrace.created_at < cutoff, MessageTrace.conversation_id.not_in(_held_conversation_ids())
            )
        )

    async def delete_token_usage(self, cutoff: datetime) -> int:
        """Per-call usage rows older than ``cutoff`` outside held conversations (the rollup keeps totals)."""
        return await self._count(
            delete(TokenUsage).where(
                TokenUsage.created_at < cutoff,
                or_(TokenUsage.conversation_id.is_(None), TokenUsage.conversation_id.not_in(_held_conversation_ids())),
            )
        )

    async def delete_audit_entries(self, cutoff: datetime) -> int:
        """Admin audit entries older than ``cutoff``."""
        return await self._count(delete(AdminAuditEntry).where(AdminAuditEntry.created_at < cutoff))

    async def delete_expired_token_bindings(self) -> int:
        """Host-token replay bindings whose token has expired (ID-06)."""
        return await self._count(delete(HostTokenUse).where(HostTokenUse.expires_at < func.now()))
