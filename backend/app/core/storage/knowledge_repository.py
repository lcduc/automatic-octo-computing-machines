"""
Database access for the knowledge base (sources, documents, chunks).

The repository only runs queries on the session it is given; transaction
boundaries belong to the calling service.
"""

# Standard library imports
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Third-party imports
from sqlalchemy import Select, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, undefer

# Local imports
from .tables.knowledge_tables import (
    DOCUMENT_STATUS_PROCESSING,
    DOCUMENT_STATUS_READY,
    REVIEW_APPROVED,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
)


@dataclass(frozen=True)
class ClaimedUpload:
    """An upload a worker has claimed from the ingestion queue."""

    document_id: uuid.UUID
    filename: Optional[str]
    file_type: str
    attempts: int
    #: The document's stored chunking spec (``{}`` = auto).
    chunking: Dict[str, Any]


@dataclass(frozen=True)
class IngestionQueueStats:
    """Snapshot of the ingestion queue for monitoring."""

    pending: int
    in_progress: int
    oldest_pending_seconds: Optional[float]


@dataclass(frozen=True)
class IndexRow:
    """The columns the in-memory index needs for one searchable chunk."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    position: int
    content: str
    embedding: Sequence[float]
    chunk_metadata: Dict[str, Any]
    document_title: str
    document_metadata: Dict[str, Any]
    original_filename: Optional[str]
    source_name: str
    source_priority: float
    access_tier: str = "anonymous"
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None


class KnowledgeRepository:
    """Queries over knowledge tables, bound to one session."""

    def __init__(self, session: AsyncSession):
        """
        Args:
            session: Open session; the caller commits or rolls back.
        """
        self._session = session

    # ------------------------------------------------------------------
    # Sources
    # ------------------------------------------------------------------

    async def list_sources_with_counts(self) -> List[Tuple[KnowledgeSource, int]]:
        """All sources with the number of documents in each, by name."""
        document_count = (
            select(func.count(KnowledgeDocument.id))
            .where(KnowledgeDocument.source_id == KnowledgeSource.id)
            .correlate(KnowledgeSource)
            .scalar_subquery()
        )
        result = await self._session.execute(
            select(KnowledgeSource, document_count).order_by(KnowledgeSource.name)
        )
        return [(source, count) for source, count in result.all()]

    async def get_source(self, source_id: int) -> Optional[KnowledgeSource]:
        """Source by primary key."""
        return await self._session.get(KnowledgeSource, source_id)

    async def get_source_by_name(self, name: str) -> Optional[KnowledgeSource]:
        """Source by its unique name (case-sensitive)."""
        result = await self._session.execute(select(KnowledgeSource).where(KnowledgeSource.name == name))
        return result.scalar_one_or_none()

    async def count_documents_in_source(self, source_id: int) -> int:
        """Documents currently filed under a source."""
        result = await self._session.execute(
            select(func.count(KnowledgeDocument.id)).where(KnowledgeDocument.source_id == source_id)
        )
        return int(result.scalar_one())

    def add(self, entity: Any) -> None:
        """Stage a new entity for insertion."""
        self._session.add(entity)

    async def delete(self, entity: Any) -> None:
        """Stage an entity for deletion."""
        await self._session.delete(entity)

    async def flush(self) -> None:
        """Send pending changes so generated keys become available."""
        await self._session.flush()

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    def _document_filter(
        self,
        statement: Select,
        source_id: Optional[int],
        status: Optional[str],
        search: Optional[str],
        review_status: Optional[str] = None,
    ) -> Select:
        """Apply the admin list filters to a documents query."""
        if source_id is not None:
            statement = statement.where(KnowledgeDocument.source_id == source_id)
        if status:
            statement = statement.where(KnowledgeDocument.status == status)
        if review_status:
            statement = statement.where(KnowledgeDocument.review_status == review_status)
        if search:
            pattern = f"%{search}%"
            statement = statement.where(
                or_(
                    KnowledgeDocument.title.ilike(pattern),
                    KnowledgeDocument.original_filename.ilike(pattern),
                )
            )
        return statement

    async def list_documents(
        self,
        source_id: Optional[int],
        status: Optional[str],
        search: Optional[str],
        limit: int,
        offset: int,
        review_status: Optional[str] = None,
    ) -> Tuple[List[KnowledgeDocument], int]:
        """
        Page of documents (newest first) plus the total matching count.

        Returns:
            ``(documents, total)``; each document has ``source`` loaded.
        """
        base = self._document_filter(select(KnowledgeDocument), source_id, status, search, review_status)
        total_result = await self._session.execute(
            self._document_filter(select(func.count(KnowledgeDocument.id)), source_id, status, search, review_status)
        )
        result = await self._session.execute(
            base.options(selectinload(KnowledgeDocument.source))
            .order_by(KnowledgeDocument.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), int(total_result.scalar_one())

    async def get_document(self, document_id: uuid.UUID, with_chunks: bool = False) -> Optional[KnowledgeDocument]:
        """Document by id with its source (and chunks, ordered, when requested)."""
        options = [selectinload(KnowledgeDocument.source)]
        if with_chunks:
            options.append(selectinload(KnowledgeDocument.chunks))
        result = await self._session.execute(
            select(KnowledgeDocument).where(KnowledgeDocument.id == document_id).options(*options)
        )
        return result.scalar_one_or_none()

    async def count_by_review_status(self) -> Dict[str, int]:
        """Documents per review status (statuses nobody holds are absent)."""
        result = await self._session.execute(
            select(KnowledgeDocument.review_status, func.count()).group_by(KnowledgeDocument.review_status)
        )
        return {status: int(count) for status, count in result.all()}

    async def list_ready_documents_with_chunks(self) -> List[KnowledgeDocument]:
        """Every ready, approved document with its source, ordered chunks and stored extracted text, oldest first."""
        result = await self._session.execute(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.status == DOCUMENT_STATUS_READY, KnowledgeDocument.review_status == REVIEW_APPROVED)
            .options(
                selectinload(KnowledgeDocument.source),
                selectinload(KnowledgeDocument.chunks),
                undefer(KnowledgeDocument.extracted_text),
            )
            .order_by(KnowledgeDocument.created_at)
        )
        return list(result.scalars().all())

    async def find_by_hash(self, source_id: int, content_hash: str) -> Optional[KnowledgeDocument]:
        """An existing document in the same source with identical file content."""
        result = await self._session.execute(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.source_id == source_id, KnowledgeDocument.content_hash == content_hash)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def lock_document(self, document_id: uuid.UUID) -> Optional[KnowledgeDocument]:
        """Document by id, row-locked until the transaction ends (serializes ingestion outcomes)."""
        return await self._session.get(KnowledgeDocument, document_id, with_for_update=True)

    # ------------------------------------------------------------------
    # Ingestion queue (documents in ``processing`` are the pending jobs)
    # ------------------------------------------------------------------

    async def claim_next_upload(self, lease_seconds: int) -> Optional["ClaimedUpload"]:
        """
        Claim the oldest pending upload that no live worker holds.

        A claim is a lease: ``claimed_at`` is renewed while the worker parses,
        so a claim older than ``lease_seconds`` belongs to a dead worker and is
        taken over. ``SKIP LOCKED`` lets concurrent workers claim distinct rows.
        """
        stale_before = func.now() - timedelta(seconds=lease_seconds)
        candidate = (
            select(KnowledgeDocument.id)
            .where(
                KnowledgeDocument.status == DOCUMENT_STATUS_PROCESSING,
                or_(KnowledgeDocument.claimed_at.is_(None), KnowledgeDocument.claimed_at < stale_before),
            )
            .order_by(KnowledgeDocument.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        result = await self._session.execute(
            update(KnowledgeDocument)
            .where(KnowledgeDocument.id == candidate)
            .values(claimed_at=func.now(), attempts=KnowledgeDocument.attempts + 1)
            .returning(
                KnowledgeDocument.id,
                KnowledgeDocument.original_filename,
                KnowledgeDocument.file_type,
                KnowledgeDocument.attempts,
                KnowledgeDocument.chunking,
            )
            .execution_options(synchronize_session=False)
        )
        row = result.one_or_none()
        return ClaimedUpload(*row) if row else None

    async def renew_claim(self, document_id: uuid.UUID) -> None:
        """Extend a worker's lease on an upload it is still parsing."""
        await self._session.execute(
            update(KnowledgeDocument)
            .where(KnowledgeDocument.id == document_id, KnowledgeDocument.status == DOCUMENT_STATUS_PROCESSING)
            .values(claimed_at=func.now())
            .execution_options(synchronize_session=False)
        )

    async def release_claim(self, document_id: uuid.UUID) -> None:
        """Hand an upload back to the queue after a clean shutdown, without counting the attempt."""
        await self._session.execute(
            update(KnowledgeDocument)
            .where(KnowledgeDocument.id == document_id, KnowledgeDocument.status == DOCUMENT_STATUS_PROCESSING)
            .values(claimed_at=None, attempts=func.greatest(KnowledgeDocument.attempts - 1, 0))
            .execution_options(synchronize_session=False)
        )

    async def ingestion_queue_stats(self, lease_seconds: int) -> "IngestionQueueStats":
        """Pending uploads, how many a live worker holds, and how long the oldest has waited."""
        live_claim = KnowledgeDocument.claimed_at >= func.now() - timedelta(seconds=lease_seconds)
        result = await self._session.execute(
            select(
                func.count(),
                func.count().filter(live_claim),
                func.extract("epoch", func.now() - func.min(KnowledgeDocument.created_at)),
            ).where(KnowledgeDocument.status == DOCUMENT_STATUS_PROCESSING)
        )
        pending, in_progress, oldest_age = result.one()
        return IngestionQueueStats(
            int(pending), int(in_progress), float(oldest_age) if oldest_age is not None else None
        )

    async def latest_processed_at(self) -> Optional[datetime]:
        """When the most recent ingestion finished, or ``None`` if none has."""
        result = await self._session.execute(select(func.max(KnowledgeDocument.processed_at)))
        return result.scalar_one()

    # ------------------------------------------------------------------
    # Chunks
    # ------------------------------------------------------------------

    async def get_chunk(self, chunk_id: uuid.UUID) -> Optional[KnowledgeChunk]:
        """Chunk by id, with its document loaded."""
        result = await self._session.execute(
            select(KnowledgeChunk).where(KnowledgeChunk.id == chunk_id).options(selectinload(KnowledgeChunk.document))
        )
        return result.scalar_one_or_none()

    def add_chunks(
        self,
        document: KnowledgeDocument,
        texts: List[str],
        vectors: Sequence[Sequence[float]],
        metadata: List[Dict[str, Any]],
        start: int,
        embedding_model: str,
    ) -> None:
        """Stage chunk rows for ``texts`` beginning at ``start`` and bump the document's count."""
        for offset, (text, vector, chunk_metadata) in enumerate(zip(texts, vectors, metadata)):
            self._session.add(
                KnowledgeChunk(
                    document_id=document.id,
                    position=start + offset,
                    content=text,
                    extra_metadata=chunk_metadata,
                    embedding=vector,
                    embedding_model=embedding_model,
                )
            )
        document.chunk_count = (document.chunk_count or 0) + len(texts)

    async def replace_chunks(
        self,
        document: KnowledgeDocument,
        texts: List[str],
        vectors: Sequence[Sequence[float]],
        metadata: List[Dict[str, Any]],
        embedding_model: str,
    ) -> None:
        """Delete every chunk of ``document`` and stage ``texts`` as its new chunks from position 0."""
        await self._session.execute(
            delete(KnowledgeChunk)
            .where(KnowledgeChunk.document_id == document.id)
            .execution_options(synchronize_session=False)
        )
        document.chunk_count = 0
        self.add_chunks(document, texts, vectors, metadata, 0, embedding_model)

    async def count_edited_chunks(self, document_id: uuid.UUID) -> int:
        """Chunks of a document that an admin wrote or changed."""
        result = await self._session.execute(
            select(func.count(KnowledgeChunk.id)).where(
                KnowledgeChunk.document_id == document_id, KnowledgeChunk.edited.is_(True)
            )
        )
        return int(result.scalar_one())

    async def load_extracted_text(self, document_id: uuid.UUID) -> Optional[Tuple[str, str]]:
        """``(extracted text, extraction method)`` of a document, or ``None`` if it has no stored text."""
        result = await self._session.execute(
            select(KnowledgeDocument.extracted_text, KnowledgeDocument.extraction_method).where(
                KnowledgeDocument.id == document_id
            )
        )
        row = result.one_or_none()
        if row is None or row.extracted_text is None:
            return None
        return row.extracted_text, row.extraction_method

    async def shift_positions(self, document_id: uuid.UUID, from_position: int, delta: int) -> None:
        """Add ``delta`` to the position of every chunk at or after ``from_position``."""
        await self._session.execute(
            update(KnowledgeChunk)
            .where(KnowledgeChunk.document_id == document_id, KnowledgeChunk.position >= from_position)
            .values(position=KnowledgeChunk.position + delta)
        )

    async def count_chunks(self, document_id: uuid.UUID) -> int:
        """Chunks belonging to a document."""
        result = await self._session.execute(
            select(func.count(KnowledgeChunk.id)).where(KnowledgeChunk.document_id == document_id)
        )
        return int(result.scalar_one())

    async def chunks_needing_embedding(self, embedding_model: str, limit: int) -> List[KnowledgeChunk]:
        """Chunks with no embedding, or one produced by a different model."""
        result = await self._session.execute(
            select(KnowledgeChunk)
            .where(
                or_(
                    KnowledgeChunk.embedding.is_(None),
                    KnowledgeChunk.embedding_model.is_(None),
                    KnowledgeChunk.embedding_model != embedding_model,
                )
            )
            .limit(limit)
        )
        return list(result.scalars().all())

    async def load_index_rows(self) -> List[IndexRow]:
        """
        Every chunk that should be searchable, ordered by document then position.

        Only ready, approved, enabled documents in enabled sources with an embedding are
        returned, and none whose validity already ended; the ordering lets the
        index find a chunk's neighbours by adjacency. Tier and effective dates
        are filtered again per query (documents activate on their date without
        a refresh).
        """
        result = await self._session.execute(
            select(
                KnowledgeChunk.id,
                KnowledgeChunk.document_id,
                KnowledgeChunk.position,
                KnowledgeChunk.content,
                KnowledgeChunk.embedding,
                KnowledgeChunk.extra_metadata,
                KnowledgeDocument.title,
                KnowledgeDocument.extra_metadata,
                KnowledgeDocument.original_filename,
                KnowledgeSource.name,
                KnowledgeSource.priority,
                KnowledgeDocument.access_tier,
                KnowledgeDocument.effective_from,
                KnowledgeDocument.effective_to,
            )
            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .join(KnowledgeSource, KnowledgeDocument.source_id == KnowledgeSource.id)
            .where(
                KnowledgeDocument.status == DOCUMENT_STATUS_READY,
                KnowledgeDocument.review_status == REVIEW_APPROVED,
                KnowledgeDocument.enabled.is_(True),
                KnowledgeSource.enabled.is_(True),
                KnowledgeChunk.embedding.is_not(None),
                or_(KnowledgeDocument.effective_to.is_(None), KnowledgeDocument.effective_to >= func.current_date()),
            )
            .order_by(KnowledgeChunk.document_id, KnowledgeChunk.position)
        )
        return [IndexRow(*row) for row in result.all()]
