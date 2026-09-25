"""
Knowledge base management: sources, documents and chunks, kept in sync with the search index.
"""

# Standard library imports
import asyncio
import hashlib
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Local imports
from core.retrieval.knowledge_index import KnowledgeIndex
from core.storage.database import Database
from core.storage.knowledge_repository import KnowledgeRepository
from core.storage.tables.knowledge_tables import (
    DOCUMENT_STATUS_FAILED,
    DOCUMENT_STATUS_PROCESSING,
    DOCUMENT_STATUS_READY,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
)
from .errors import ConflictError, InvalidRequestError, NotFoundError
from .ingestion_service import IngestionService

logger = logging.getLogger(__name__)

#: Chunks re-embedded per batch when the embedding model changes.
REEMBED_BATCH_SIZE = 256
#: Longest error text stored on a failed document.
MAX_ERROR_LENGTH = 500


class KnowledgeService:
    """
    CRUD over the knowledge base. Every mutation refreshes the search index so
    the chatbot answers from the edited content immediately.
    """

    def __init__(self, database: Database, ingestion: IngestionService, index: KnowledgeIndex):
        """
        Args:
            database: Connected database.
            ingestion: Parser/chunker/embedder.
            index: In-memory search index to refresh after changes.
        """
        self._database = database
        self._ingestion = ingestion
        self._index = index
        self._background_jobs: Set[asyncio.Task] = set()

    # ------------------------------------------------------------------
    # Sources
    # ------------------------------------------------------------------

    async def list_sources(self) -> List[Tuple[KnowledgeSource, int]]:
        """All sources with their document counts."""
        async with self._database.session() as session:
            return await KnowledgeRepository(session).list_sources_with_counts()

    async def create_source(self, name: str, description: str, priority: float, enabled: bool) -> KnowledgeSource:
        """
        Create a source category.

        Raises:
            ConflictError: A source with this name exists.
        """
        async with self._database.session() as session:
            repository = KnowledgeRepository(session)
            if await repository.get_source_by_name(name):
                raise ConflictError(f"Source '{name}' already exists")
            source = KnowledgeSource(name=name, description=description, priority=priority, enabled=enabled)
            repository.add(source)
            await repository.flush()
        logger.info("Created knowledge source %s", name)
        return source

    async def update_source(self, source_id: int, changes: Dict[str, Any]) -> KnowledgeSource:
        """
        Update a source's name/description/priority/enabled flag.

        Raises:
            NotFoundError: Unknown source.
            ConflictError: Renaming onto an existing name.
        """
        async with self._database.session() as session:
            repository = KnowledgeRepository(session)
            source = await repository.get_source(source_id)
            if source is None:
                raise NotFoundError("Source not found")
            new_name = changes.get("name")
            if new_name and new_name != source.name and await repository.get_source_by_name(new_name):
                raise ConflictError(f"Source '{new_name}' already exists")
            for field_name, value in changes.items():
                setattr(source, field_name, value)
        logger.info("Updated knowledge source %d: %s", source_id, sorted(changes))
        await self._index.refresh()
        return source

    async def delete_source(self, source_id: int) -> None:
        """
        Delete an empty source.

        Raises:
            NotFoundError: Unknown source.
            ConflictError: The source still holds documents.
        """
        async with self._database.session() as session:
            repository = KnowledgeRepository(session)
            source = await repository.get_source(source_id)
            if source is None:
                raise NotFoundError("Source not found")
            if await repository.count_documents_in_source(source_id):
                raise ConflictError("Move or delete the source's documents first")
            await repository.delete(source)
        logger.info("Deleted knowledge source %d", source_id)

    async def _require_source(self, repository: KnowledgeRepository, name: str) -> KnowledgeSource:
        """Look up a source by name or raise ``InvalidRequestError``."""
        source = await repository.get_source_by_name(name)
        if source is None:
            raise InvalidRequestError(f"Unknown source '{name}'")
        return source

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    async def list_documents(
        self, source_name: Optional[str], status: Optional[str], search: Optional[str], limit: int, offset: int
    ) -> Tuple[List[KnowledgeDocument], int]:
        """Page of documents plus the total count matching the filters."""
        async with self._database.session() as session:
            repository = KnowledgeRepository(session)
            source_id = None
            if source_name:
                source = await repository.get_source_by_name(source_name)
                if source is None:
                    return [], 0
                source_id = source.id
            return await repository.list_documents(source_id, status, search, limit, offset)

    async def get_document(self, document_id: uuid.UUID) -> KnowledgeDocument:
        """
        Document with its source and ordered chunks.

        Raises:
            NotFoundError: Unknown document.
        """
        async with self._database.session() as session:
            document = await KnowledgeRepository(session).get_document(document_id, with_chunks=True)
        if document is None:
            raise NotFoundError("Document not found")
        return document

    async def upload_file(
        self,
        content: bytes,
        filename: str,
        source_name: str,
        title: Optional[str],
        metadata: Dict[str, Any],
        created_by: Optional[str],
    ) -> KnowledgeDocument:
        """
        Register an uploaded file and parse/embed it in the background.

        The document is returned immediately with status ``processing``; it
        becomes ``ready`` (or ``failed`` with an error) once ingestion finishes.

        Raises:
            InvalidRequestError: Empty file, unsupported type or unknown source.
            ConflictError: The same file already exists in this source.
        """
        extension = Path(filename).suffix.lower()
        if not content:
            raise InvalidRequestError("The file is empty")
        if extension not in self._ingestion.supported_extensions():
            raise InvalidRequestError(f"Unsupported file type '{extension}'")
        content_hash = hashlib.sha256(content).hexdigest()

        async with self._database.session() as session:
            repository = KnowledgeRepository(session)
            source = await self._require_source(repository, source_name)
            duplicate = await repository.find_by_hash(source.id, content_hash)
            if duplicate is not None:
                raise ConflictError(f"This file already exists in '{source_name}' as '{duplicate.title}'")
            document = KnowledgeDocument(
                source_id=source.id,
                title=(title or Path(filename).stem)[:512],
                original_filename=filename[:512],
                file_type=extension.lstrip("."),
                content_hash=content_hash,
                extra_metadata=metadata,
                status=DOCUMENT_STATUS_PROCESSING,
                created_by=created_by,
            )
            repository.add(document)
            await repository.flush()
            document.source = source

        logger.info("Queued ingestion of %s into %s as %s", filename, source_name, document.id)
        job = asyncio.create_task(self._ingest_file(document.id, content, filename))
        self._background_jobs.add(job)
        job.add_done_callback(self._background_jobs.discard)
        return document

    async def _ingest_file(self, document_id: uuid.UUID, content: bytes, filename: str) -> None:
        """Background job: parse, embed and store a file's chunks."""
        try:
            texts = await self._ingestion.extract_chunks(content, filename)
            vectors = await self._ingestion.embed(texts)
            async with self._database.session() as session:
                repository = KnowledgeRepository(session)
                document = await repository.get_document(document_id)
                if document is None:
                    logger.warning("Document %s was deleted during ingestion", document_id)
                    return
                self._add_chunks(repository, document, texts, vectors, [{} for _ in texts], start=0)
                document.status = DOCUMENT_STATUS_READY
                document.error = None
            logger.info("Ingested %s: %d chunks", filename, len(texts))
        except Exception as exc:
            logger.exception("Ingestion failed for %s", filename)
            await self._mark_failed(document_id, exc)
        self._index.request_refresh()

    async def _mark_failed(self, document_id: uuid.UUID, exc: Exception) -> None:
        """Record an ingestion failure on the document."""
        message = str(exc) if isinstance(exc, ValueError) else "Processing failed; see server logs."
        try:
            async with self._database.session() as session:
                document = await KnowledgeRepository(session).get_document(document_id)
                if document is not None:
                    document.status = DOCUMENT_STATUS_FAILED
                    document.error = message[:MAX_ERROR_LENGTH]
        except Exception:
            logger.exception("Could not mark document %s as failed", document_id)

    def _add_chunks(
        self,
        repository: KnowledgeRepository,
        document: KnowledgeDocument,
        texts: List[str],
        vectors,
        metadata: List[Dict[str, Any]],
        start: int,
    ) -> None:
        """Stage chunk rows for ``texts`` beginning at ``start`` and bump the document's count."""
        model = self._ingestion.embedding_model
        for offset, (text, vector, chunk_metadata) in enumerate(zip(texts, vectors, metadata)):
            repository.add(
                KnowledgeChunk(
                    document_id=document.id,
                    position=start + offset,
                    content=text,
                    extra_metadata=chunk_metadata,
                    embedding=vector,
                    embedding_model=model,
                )
            )
        document.chunk_count = (document.chunk_count or 0) + len(texts)

    async def create_text_document(
        self,
        source_name: str,
        title: str,
        text: str,
        metadata: Dict[str, Any],
        created_by: Optional[str],
    ) -> KnowledgeDocument:
        """
        Create a document from typed text (e.g. one FAQ entry), embedded synchronously.

        Raises:
            InvalidRequestError: Empty text or unknown source.
        """
        texts = self._ingestion.split_text(text)
        if not texts:
            raise InvalidRequestError("The content is empty")
        vectors = await self._ingestion.embed(texts)
        async with self._database.session() as session:
            repository = KnowledgeRepository(session)
            source = await self._require_source(repository, source_name)
            document = KnowledgeDocument(
                source_id=source.id,
                title=title[:512],
                file_type="text",
                content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                extra_metadata=metadata,
                status=DOCUMENT_STATUS_READY,
                created_by=created_by,
            )
            repository.add(document)
            await repository.flush()
            self._add_chunks(repository, document, texts, vectors, [{} for _ in texts], start=0)
            document.source = source
        logger.info("Created text document %s in %s (%d chunks)", document.id, source_name, len(texts))
        await self._index.refresh()
        return document

    async def update_document(self, document_id: uuid.UUID, changes: Dict[str, Any]) -> KnowledgeDocument:
        """
        Update title, metadata, enabled flag or source of a document.

        Args:
            changes: Any of ``title``, ``metadata``, ``enabled``, ``source``.

        Raises:
            NotFoundError: Unknown document.
            InvalidRequestError: Unknown target source.
        """
        async with self._database.session() as session:
            repository = KnowledgeRepository(session)
            document = await repository.get_document(document_id)
            if document is None:
                raise NotFoundError("Document not found")
            if "source" in changes:
                document.source = await self._require_source(repository, changes["source"])
            if "title" in changes:
                document.title = changes["title"][:512]
            if "metadata" in changes:
                document.extra_metadata = changes["metadata"]
            if "enabled" in changes:
                document.enabled = changes["enabled"]
        logger.info("Updated document %s: %s", document_id, sorted(changes))
        await self._index.refresh()
        return await self.get_document(document_id)

    async def delete_document(self, document_id: uuid.UUID) -> None:
        """
        Delete a document and all of its chunks.

        Raises:
            NotFoundError: Unknown document.
        """
        async with self._database.session() as session:
            repository = KnowledgeRepository(session)
            document = await repository.get_document(document_id)
            if document is None:
                raise NotFoundError("Document not found")
            await repository.delete(document)
        logger.info("Deleted document %s", document_id)
        await self._index.refresh()

    # ------------------------------------------------------------------
    # Chunks
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

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

    async def wait_for_background_jobs(self) -> None:
        """Await in-flight ingestion jobs (used on shutdown and in tests)."""
        if self._background_jobs:
            await asyncio.gather(*self._background_jobs, return_exceptions=True)
