"""
Chunk-level editing of knowledge documents: hand edits, inserts, deletes and re-chunking.
"""

# Standard library imports
import asyncio
import logging
import uuid
from typing import Any, Dict, Optional, Tuple

# Local imports
from core.document_processing.chunking import InvalidChunkingError
from core.retrieval.knowledge_index import KnowledgeIndex
from core.storage.database import Database
from core.storage.knowledge_repository import KnowledgeRepository
from core.storage.tables.knowledge_tables import (
    DOCUMENT_STATUS_PROCESSING,
    DOCUMENT_STATUS_READY,
    KnowledgeChunk,
    KnowledgeDocument,
)
from models.knowledge import ChunkingResult, ChunkingSpec
from .errors import ConflictError, InvalidRequestError, NotFoundError
from .ingestion_service import IngestionService

logger = logging.getLogger(__name__)

NO_STORED_TEXT_ERROR = (
    "This document's extracted text was not stored (it was uploaded before re-chunking existed); "
    "delete it and upload the file again to change its chunking."
)


async def chunk_off_loop(
    ingestion: IngestionService, text: str, spec: ChunkingSpec, extraction_method: str
) -> ChunkingResult:
    """
    Chunk text in a worker thread.

    Raises:
        InvalidRequestError: The strategy cannot chunk this text.
    """
    try:
        return await asyncio.to_thread(ingestion.chunk, text, spec, extraction_method)
    except InvalidChunkingError as exc:
        raise InvalidRequestError(str(exc)) from exc


class ChunkEditingService:
    """
    Edits a document's chunks. Every change re-embeds what it touches and
    refreshes the search index, so answers use the edited content immediately.
    """

    def __init__(self, database: Database, ingestion: IngestionService, index: KnowledgeIndex):
        """
        Args:
            database: Connected database.
            ingestion: Chunker and embedder.
            index: In-memory search index to refresh after changes.
        """
        self._database = database
        self._ingestion = ingestion
        self._index = index

    async def update_chunk(
        self, chunk_id: uuid.UUID, content: Optional[str], metadata: Optional[Dict[str, Any]]
    ) -> KnowledgeChunk:
        """
        Edit a chunk's text (re-embedded) and/or metadata.

        Raises:
            NotFoundError: Unknown chunk.
            InvalidRequestError: Empty content.
        """
        vector = None
        if content is not None:
            if not content.strip():
                raise InvalidRequestError("Chunk content cannot be empty")
            vector = (await self._ingestion.embed([content]))[0]
        async with self._database.session() as session:
            chunk = await KnowledgeRepository(session).get_chunk(chunk_id)
            if chunk is None:
                raise NotFoundError("Chunk not found")
            if content is not None:
                chunk.content = content
                chunk.embedding = vector
                chunk.embedding_model = self._ingestion.embedding_model
            if metadata is not None:
                chunk.extra_metadata = metadata
            chunk.edited = True
        logger.info("Updated chunk %s", chunk_id)
        await self._index.refresh()
        return chunk

    async def add_chunk(
        self, document_id: uuid.UUID, content: str, metadata: Dict[str, Any], position: Optional[int]
    ) -> KnowledgeChunk:
        """
        Insert a chunk into a document at ``position`` (appended when ``None``).

        Raises:
            NotFoundError: Unknown document.
            InvalidRequestError: Empty content.
        """
        if not content.strip():
            raise InvalidRequestError("Chunk content cannot be empty")
        vector = (await self._ingestion.embed([content]))[0]
        async with self._database.session() as session:
            repository = KnowledgeRepository(session)
            document = await repository.get_document(document_id)
            if document is None:
                raise NotFoundError("Document not found")
            count = await repository.count_chunks(document_id)
            target = count if position is None else max(0, min(position, count))
            if target < count:
                await repository.shift_positions(document_id, target, 1)
            chunk = KnowledgeChunk(
                document_id=document_id,
                position=target,
                content=content,
                extra_metadata=metadata,
                embedding=vector,
                embedding_model=self._ingestion.embedding_model,
                edited=True,
            )
            repository.add(chunk)
            document.chunk_count = count + 1
            if document.status != DOCUMENT_STATUS_READY:
                document.status = DOCUMENT_STATUS_READY
                document.error = None
        logger.info("Added chunk to document %s at position %d", document_id, target)
        await self._index.refresh()
        return chunk

    async def delete_chunk(self, chunk_id: uuid.UUID) -> None:
        """
        Remove a chunk and close the gap in its document's positions.

        Raises:
            NotFoundError: Unknown chunk.
        """
        async with self._database.session() as session:
            repository = KnowledgeRepository(session)
            chunk = await repository.get_chunk(chunk_id)
            if chunk is None:
                raise NotFoundError("Chunk not found")
            document, position = chunk.document, chunk.position
            await repository.delete(chunk)
            await repository.flush()
            await repository.shift_positions(document.id, position + 1, -1)
            document.chunk_count = max(0, (document.chunk_count or 1) - 1)
        logger.info("Deleted chunk %s", chunk_id)
        await self._index.refresh()

    async def preview_chunking(self, document_id: uuid.UUID, spec: ChunkingSpec) -> ChunkingResult:
        """
        Chunk a document's stored text with ``spec`` without embedding or saving anything.

        Raises:
            NotFoundError: Unknown document.
            ConflictError: Still processing, or no stored text.
            InvalidRequestError: The strategy cannot chunk this text.
        """
        async with self._database.session() as session:
            text, method = await self._stored_text(KnowledgeRepository(session), document_id)
        result = await chunk_off_loop(self._ingestion, text, spec, method)
        logger.info("Previewed %s on document %s: %d chunks", spec.strategy, document_id, len(result.drafts))
        return result

    async def rechunk(
        self, document_id: uuid.UUID, spec: ChunkingSpec, discard_manual_edits: bool
    ) -> KnowledgeDocument:
        """
        Replace a document's chunks with its stored text chunked by ``spec``.

        Returns:
            The document with its source and new chunks.

        Raises:
            NotFoundError: Unknown document.
            ConflictError: Still processing, no stored text, or chunks edited by
                hand while ``discard_manual_edits`` is false.
            InvalidRequestError: The strategy cannot chunk this text.
        """
        # ceiling: chunks and embeds inside the request (≤MAX_PDF_PAGES pages, a few thousand chunks); move to the ingestion queue if re-chunk requests time out
        async with self._database.session() as session:
            repository = KnowledgeRepository(session)
            text, method = await self._stored_text(repository, document_id)
            await self._check_manual_edits(repository, document_id, discard_manual_edits)
        drafts = (await chunk_off_loop(self._ingestion, text, spec, method)).drafts
        vectors = await self._ingestion.embed([draft.content for draft in drafts])
        async with self._database.session() as session:
            repository = KnowledgeRepository(session)
            document = await repository.lock_document(document_id)
            if document is None:
                raise NotFoundError("Document not found")
            if document.status == DOCUMENT_STATUS_PROCESSING:
                raise ConflictError("The document is still being processed")
            # Re-checked under the lock: an edit may have landed while embedding.
            await self._check_manual_edits(repository, document_id, discard_manual_edits)
            await repository.replace_chunks(
                document,
                [draft.content for draft in drafts],
                vectors,
                [draft.metadata for draft in drafts],
                self._ingestion.embedding_model,
            )
            document.chunking = spec.to_json()
            document.status, document.error = DOCUMENT_STATUS_READY, None
        logger.info("Re-chunked document %s with %s into %d chunks", document_id, spec.strategy, len(drafts))
        await self._index.refresh()
        async with self._database.session() as session:
            rechunked = await KnowledgeRepository(session).get_document(document_id, with_chunks=True)
        if rechunked is None:
            raise NotFoundError("Document not found")
        return rechunked

    @staticmethod
    async def _stored_text(repository: KnowledgeRepository, document_id: uuid.UUID) -> Tuple[str, str]:
        """
        A ready document's extracted text and extraction method.

        Raises:
            NotFoundError: Unknown document.
            ConflictError: Still processing, or its text was never stored.
        """
        document = await repository.get_document(document_id)
        if document is None:
            raise NotFoundError("Document not found")
        if document.status == DOCUMENT_STATUS_PROCESSING:
            raise ConflictError("The document is still being processed")
        stored = await repository.load_extracted_text(document_id)
        if stored is None:
            raise ConflictError(NO_STORED_TEXT_ERROR)
        return stored

    @staticmethod
    async def _check_manual_edits(repository: KnowledgeRepository, document_id: uuid.UUID, discard: bool) -> None:
        """
        Raises:
            ConflictError: The document has hand-edited chunks and ``discard`` is false.
        """
        edited = await repository.count_edited_chunks(document_id)
        if edited and not discard:
            raise ConflictError(
                f"{edited} chunk(s) were edited by hand and would be lost; resend with discard_manual_edits=true"
            )
