"""
Read-only queries behind the document-health card: which documents answers cite,
which they never cite, and which are about to expire or not yet in force.

Citations are read from ``messages.citations`` (a JSONB array of objects carrying
``document_id`` as text), so the figures only reach back as far as chat retention.
"""

# Standard library imports
from datetime import date, datetime
from typing import Any, Dict, List, Tuple

# Third-party imports
from sqlalchemy import ColumnElement, Select, String, Subquery, cast, column, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

# Local imports
from .tables.conversation_tables import Feedback, Message
from .tables.knowledge_tables import DOCUMENT_STATUS_FAILED, DOCUMENT_STATUS_READY, REVIEW_APPROVED, KnowledgeDocument

#: ``feedback.rating`` of a thumbs-down.
THUMBS_DOWN_RATING = -1
#: Only the assistant's answers carry citations.
ASSISTANT_ROLE = "assistant"

#: A document the assistant may answer from: enabled, processed and approved.
ACTIVE_DOCUMENT = (
    KnowledgeDocument.enabled.is_(True),
    KnowledgeDocument.status == DOCUMENT_STATUS_READY,
    KnowledgeDocument.review_status == REVIEW_APPROVED,
)


class KnowledgeHealthRepository:
    """Aggregate queries over documents and the answers citing them (a fixed handful per call)."""

    def __init__(self, session: AsyncSession):
        """
        Args:
            session: Session whose transaction the caller owns.
        """
        self._session = session

    @staticmethod
    def _citations(since: datetime, thumbs_down_only: bool = False) -> Subquery:
        """
        One row per (assistant message since ``since``, cited document id as text).

        A message citing several chunks of one document yields several rows for it;
        callers count distinct ``message_id``.
        """
        element = func.jsonb_array_elements(Message.citations).table_valued(column("value", JSONB), joins_implicitly=True)
        query = select(Message.id.label("message_id"), element.c.value["document_id"].astext.label("document_id")).where(
            Message.role == ASSISTANT_ROLE, Message.created_at >= since
        )
        if thumbs_down_only:
            query = query.join(Feedback, Feedback.message_id == Message.id).where(Feedback.rating == THUMBS_DOWN_RATING)
        return query.subquery("citations")

    @staticmethod
    def _document_key() -> ColumnElement[str]:
        """The document id as the text stored in citations (casting this side never fails on a bad id)."""
        return cast(KnowledgeDocument.id, String)

    async def document_counts(self) -> Dict[str, int]:
        """Active (enabled, ready, approved), disabled and failed documents."""
        result = await self._session.execute(
            select(
                func.count().filter(*ACTIVE_DOCUMENT).label("documents"),
                func.count().filter(KnowledgeDocument.enabled.is_(False)).label("disabled"),
                func.count().filter(KnowledgeDocument.status == DOCUMENT_STATUS_FAILED).label("failed"),
            ).select_from(KnowledgeDocument)
        )
        return {key: int(value) for key, value in result.one()._mapping.items()}

    async def cited_documents(self, since: datetime, limit: int, thumbs_down_only: bool = False) -> List[Dict[str, Any]]:
        """
        Documents ranked by how many answers since ``since`` cited them.

        Args:
            since: Start of the window.
            limit: Most documents returned.
            thumbs_down_only: Count only answers rated thumbs-down.

        Returns:
            ``document_id``, ``title`` and ``answers`` (each answer counted once per document), most first.
        """
        citations = self._citations(since, thumbs_down_only)
        answers = func.count(func.distinct(citations.c.message_id))
        result = await self._session.execute(
            select(KnowledgeDocument.id.label("document_id"), KnowledgeDocument.title, answers.label("answers"))
            .join(citations, citations.c.document_id == self._document_key())
            .group_by(KnowledgeDocument.id, KnowledgeDocument.title)
            .order_by(answers.desc(), KnowledgeDocument.title)
            .limit(limit)
        )
        return [dict(row._mapping) for row in result.all()]

    async def never_cited(self, since: datetime, limit: int) -> Tuple[int, List[Dict[str, Any]]]:
        """
        Active documents created before ``since`` that no answer since then cited.

        Returns:
            How many there are, and the oldest ``limit`` of them (``document_id``, ``title``, ``created_at``).
        """
        citations = self._citations(since)
        cited = select(citations.c.message_id).where(citations.c.document_id == self._document_key()).exists()
        conditions = (*ACTIVE_DOCUMENT, KnowledgeDocument.created_at < since, ~cited)
        total = await self._session.execute(select(func.count(KnowledgeDocument.id)).where(*conditions))
        rows = await self._session.execute(
            select(KnowledgeDocument.id.label("document_id"), KnowledgeDocument.title, KnowledgeDocument.created_at)
            .where(*conditions)
            .order_by(KnowledgeDocument.created_at, KnowledgeDocument.title)
            .limit(limit)
        )
        return int(total.scalar_one()), [dict(row._mapping) for row in rows.all()]

    async def _dated(self, query: Select, limit: int) -> List[Dict[str, Any]]:
        """Run ``query`` (already filtered and ordered) for its first ``limit`` rows."""
        result = await self._session.execute(query.limit(limit))
        return [dict(row._mapping) for row in result.all()]

    async def expiring(self, today: date, until: date, limit: int) -> List[Dict[str, Any]]:
        """Enabled documents whose last valid day falls between ``today`` and ``until`` (inclusive), soonest first."""
        return await self._dated(
            select(KnowledgeDocument.id.label("document_id"), KnowledgeDocument.title, KnowledgeDocument.effective_to)
            .where(KnowledgeDocument.enabled.is_(True), KnowledgeDocument.effective_to.between(today, until))
            .order_by(KnowledgeDocument.effective_to, KnowledgeDocument.title),
            limit,
        )

    async def scheduled(self, today: date, limit: int) -> List[Dict[str, Any]]:
        """Enabled documents that only come into force after ``today``, soonest first."""
        return await self._dated(
            select(KnowledgeDocument.id.label("document_id"), KnowledgeDocument.title, KnowledgeDocument.effective_from)
            .where(KnowledgeDocument.enabled.is_(True), KnowledgeDocument.effective_from > today)
            .order_by(KnowledgeDocument.effective_from, KnowledgeDocument.title),
            limit,
        )
