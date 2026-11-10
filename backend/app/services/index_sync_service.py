"""
Keeps the in-memory search index in step with ingestion and with the active embedding model.
"""

# Standard library imports
import asyncio
import logging
from datetime import datetime
from typing import Optional

# Local imports
from app.core.retrieval.knowledge_index import KnowledgeIndex
from app.core.storage.database import Database
from app.core.storage.knowledge_repository import IngestionQueueStats, KnowledgeRepository
from .ingestion_service import IngestionService
from .ingestion_worker import CLAIM_LEASE_SECONDS

logger = logging.getLogger(__name__)

#: Chunks re-embedded per batch when the embedding model changes.
REEMBED_BATCH_SIZE = 256


class IndexSyncService:
    """
    Background upkeep of the knowledge index.

    Uploads are parsed by :class:`IngestionWorker`, possibly in another process;
    this service notices when they finish and refreshes the index, and re-embeds
    chunks left over from a previous embedding model.
    """

    def __init__(self, database: Database, ingestion: IngestionService, index: KnowledgeIndex):
        """
        Args:
            database: Connected database.
            ingestion: Embedder (its model is the one chunks must match).
            index: In-memory search index to refresh.
        """
        self._database = database
        self._ingestion = ingestion
        self._index = index
        self._last_processed_at: Optional[datetime] = None
        self._ingestion_mark_seen = False

    async def ingestion_queue(self) -> IngestionQueueStats:
        """
        State of the upload queue. ``pending`` uploads with none ``in_progress``
        for long means the ingestion worker is down or stuck.
        """
        async with self._database.session() as session:
            return await KnowledgeRepository(session).ingestion_queue_stats(CLAIM_LEASE_SECONDS)

    async def refresh_index_if_ingested(self) -> bool:
        """
        Rebuild the search index if an upload finished since the last check.

        Ingestion may run in another process, so the API learns about finished
        uploads from ``processed_at`` rather than from an in-process callback.
        The first call only records the current mark.

        Returns:
            Whether the index was refreshed.
        """
        async with self._database.session() as session:
            latest = await KnowledgeRepository(session).latest_processed_at()
        changed = self._ingestion_mark_seen and latest != self._last_processed_at
        self._last_processed_at, self._ingestion_mark_seen = latest, True
        if changed:
            logger.info("Uploads finished ingesting; refreshing the knowledge index")
            await self._index.refresh()
        return changed

    async def watch_ingestions(self, interval_seconds: float) -> None:
        """Call :meth:`refresh_index_if_ingested` every ``interval_seconds`` until cancelled."""
        while True:
            try:
                await self.refresh_index_if_ingested()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Checking for finished ingestions failed")
            await asyncio.sleep(interval_seconds)

    async def reembed_stale_chunks(self) -> int:
        """
        Re-embed chunks produced by a different embedding model (or none).

        Run at start-up so changing ``EMBEDDING_MODEL`` never mixes vector spaces.

        Returns:
            Number of chunks re-embedded.
        """
        model = self._ingestion.embedding_model
        total = 0
        while True:
            async with self._database.session() as session:
                repository = KnowledgeRepository(session)
                chunks = await repository.chunks_needing_embedding(model, REEMBED_BATCH_SIZE)
                if not chunks:
                    break
                vectors = await self._ingestion.embed([chunk.content for chunk in chunks])
                for chunk, vector in zip(chunks, vectors):
                    chunk.embedding = vector
                    chunk.embedding_model = model
            total += len(chunks)
            logger.info("Re-embedded %d chunks so far with %s", total, model)
        if total:
            await self._index.refresh()
        return total
