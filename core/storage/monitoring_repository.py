"""
Queries behind the alert rules (OBS-04) and the state that de-duplicates alerts.
"""

# Standard library imports
from datetime import datetime
from typing import List, Optional, Tuple

# Third-party imports
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# Local imports
from .tables.conversation_tables import HANDOFF_ACTIVE_STATUSES, HandoffRequest, Message
from .tables.knowledge_tables import DOCUMENT_STATUS_FAILED, KnowledgeDocument
from .tables.observability_tables import AlertState


class MonitoringRepository:
    """Alert-rule queries and alert state."""

    def __init__(self, session: AsyncSession):
        """
        Args:
            session: Open session (the caller owns the transaction).
        """
        self._session = session

    async def state(self, rule: str) -> AlertState:
        """The rule's state row, created (not firing) on first use."""
        state = await self._session.get(AlertState, rule)
        if state is None:
            state = AlertState(rule=rule, firing=False)
            self._session.add(state)
        return state

    async def turn_errors_since(self, since: datetime) -> Tuple[int, int]:
        """``(answers, errors)`` since ``since``."""
        turns, errors = (
            await self._session.execute(
                select(func.count(), func.count().filter(Message.outcome == "error")).where(
                    Message.role == "assistant", Message.created_at >= since
                )
            )
        ).one()
        return int(turns), int(errors)

    async def overdue_tickets(self, now: datetime) -> Tuple[int, Optional[datetime]]:
        """Open or assigned tickets past their due time, and the oldest due time."""
        count, oldest = (
            await self._session.execute(
                select(func.count(), func.min(HandoffRequest.due_at)).where(
                    HandoffRequest.status.in_(HANDOFF_ACTIVE_STATUSES), HandoffRequest.due_at < now
                )
            )
        ).one()
        return int(count), oldest

    async def failed_uploads_since(self, since: Optional[datetime]) -> List[KnowledgeDocument]:
        """Uploads whose ingestion failed after ``since`` (all failures when ``None``), oldest first."""
        query = select(KnowledgeDocument).where(
            KnowledgeDocument.status == DOCUMENT_STATUS_FAILED, KnowledgeDocument.processed_at.is_not(None)
        )
        if since is not None:
            query = query.where(KnowledgeDocument.processed_at > since)
        result = await self._session.execute(query.order_by(KnowledgeDocument.processed_at))
        return list(result.scalars().all())
