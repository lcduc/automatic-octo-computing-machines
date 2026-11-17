"""
Document health for the admin dashboard: what answers cite, what they never cite,
what visitors rated down, and which documents expire soon or are not yet in force.
"""

# Standard library imports
import logging
from datetime import date, datetime, time as dt_time, timedelta
from typing import Any, Dict
from zoneinfo import ZoneInfo

# Local imports
from app.core.storage.database import Database
from app.core.storage.knowledge_health_repository import KnowledgeHealthRepository

logger = logging.getLogger(__name__)

#: A document is "expiring" when its last valid day is at most this many days away.
EXPIRING_WITHIN_DAYS = 30


class KnowledgeHealthService:
    """Builds the ``/knowledge/health`` report from a handful of aggregate queries."""

    def __init__(self, database: Database, timezone: str):
        """
        Args:
            database: Connected database.
            timezone: IANA zone whose dates bound the window and validity (the app time zone).
        """
        self._database = database
        self._timezone = ZoneInfo(timezone)

    def _today(self) -> date:
        """The current local date."""
        return datetime.now(self._timezone).date()

    async def health(self, days: int, limit: int) -> Dict[str, Any]:
        """
        Document health over the last ``days`` local days, today included.

        Args:
            days: Local days of answers whose citations are counted.
            limit: Most documents in each list.

        Returns:
            ``since``; the ``documents``/``disabled``/``failed`` counts; ``most_cited``,
            ``never_cited`` (count and oldest items), ``not_helpful``, ``expiring`` and
            ``scheduled`` document lists.
        """
        today = self._today()
        since = datetime.combine(today - timedelta(days=days - 1), dt_time.min, tzinfo=self._timezone)
        async with self._database.session() as session:
            repository = KnowledgeHealthRepository(session)
            counts = await repository.document_counts()
            most_cited = await repository.cited_documents(since, limit)
            not_helpful = await repository.cited_documents(since, limit, thumbs_down_only=True)
            never_cited_count, never_cited = await repository.never_cited(since, limit)
            expiring = await repository.expiring(today, today + timedelta(days=EXPIRING_WITHIN_DAYS), limit)
            scheduled = await repository.scheduled(today, limit)
        logger.debug("Knowledge health over %d days: %s, %d never cited", days, counts, never_cited_count)
        return {
            "since": since,
            **counts,
            "most_cited": [{**self._document(row), "citations": row["answers"]} for row in most_cited],
            "never_cited": {"count": never_cited_count, "items": never_cited},
            "not_helpful": [{**self._document(row), "count": row["answers"]} for row in not_helpful],
            "expiring": expiring,
            "scheduled": scheduled,
        }

    @staticmethod
    def _document(row: Dict[str, Any]) -> Dict[str, Any]:
        """The id and title of a ranked row."""
        return {"document_id": row["document_id"], "title": row["title"]}
