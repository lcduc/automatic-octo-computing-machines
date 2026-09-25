"""
Database access for the knowledge base (sources, documents, chunks).

The repository only runs queries on the session it is given; transaction
boundaries belong to the calling service.
"""

# Standard library imports
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Third-party imports
from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

# Local imports
from .tables.knowledge_tables import (
    DOCUMENT_STATUS_READY,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
)


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
    ) -> Select:
        """Apply the admin list filters to a documents query."""
        if source_id is not None:
            statement = statement.where(KnowledgeDocument.source_id == source_id)
        if status:
            statement = statement.where(KnowledgeDocument.status == status)
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
    ) -> Tuple[List[KnowledgeDocument], int]:
        """
        Page of documents (newest first) plus the total matching count.

        Returns:
            ``(documents, total)``; each document has ``source`` loaded.
        """
        base = self._document_filter(select(KnowledgeDocument), source_id, status, search)
        total_result = await self._session.execute(
            self._document_filter(select(func.count(KnowledgeDocument.id)), source_id, status, search)
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

    async def find_by_hash(self, source_id: int, content_hash: str) -> Optional[KnowledgeDocument]:
        """An existing document in the same source with identical file content."""
        result = await self._session.execute(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.source_id == source_id, KnowledgeDocument.content_hash == content_hash)
            .limit(1)
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Chunks
    # ------------------------------------------------------------------

    async def get_chunk(self, chunk_id: uuid.UUID) -> Optional[KnowledgeChunk]:
        """Chunk by id, with its document loaded."""
        result = await self._session.execute(
            select(KnowledgeChunk).where(KnowledgeChunk.id == chunk_id).options(selectinload(KnowledgeChunk.document))
        )
        return result.scalar_one_or_none()

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

        Only ready, enabled documents in enabled sources with an embedding are
        returned; the ordering lets the index find a chunk's neighbours by
        adjacency.
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
            )
            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .join(KnowledgeSource, KnowledgeDocument.source_id == KnowledgeSource.id)
            .where(
                KnowledgeDocument.status == DOCUMENT_STATUS_READY,
                KnowledgeDocument.enabled.is_(True),
                KnowledgeSource.enabled.is_(True),
                KnowledgeChunk.embedding.is_not(None),
            )
            .order_by(KnowledgeChunk.document_id, KnowledgeChunk.position)
        )
        return [IndexRow(*row) for row in result.all()]
