"""
Knowledge base management: sources, documents and chunks, kept in sync with the search index.
"""

# Standard library imports
import asyncio
import hashlib
import logging
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# Local imports
from config.settings import Config
from core.retrieval.knowledge_index import KnowledgeIndex
from core.storage.conversation_repository import ConversationRepository
from core.storage.database import Database
from core.storage.knowledge_repository import IngestionQueueStats, KnowledgeRepository
from core.storage.tables.knowledge_tables import (
    DOCUMENT_STATUS_FAILED,
    DOCUMENT_STATUS_PROCESSING,
    DOCUMENT_STATUS_READY,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
)
from core.storage.upload_store import UploadStore
from core.document_processing.chunking import InvalidChunkingError
from models.caller import TIER_ANONYMOUS
from models.knowledge import EXTRACTION_TEXT, ChunkingResult, ChunkingSpec
from .errors import ConflictError, InvalidRequestError, NotFoundError
from .ingestion_service import IngestionService
from .ingestion_worker import CLAIM_LEASE_SECONDS

logger = logging.getLogger(__name__)

#: Chunks re-embedded per batch when the embedding model changes.
REEMBED_BATCH_SIZE = 256
NO_STORED_TEXT_ERROR = (
    "This document's extracted text was not stored (it was uploaded before re-chunking existed); "
    "delete it and upload the file again to change its chunking."
)


class KnowledgeService:
    """
    CRUD over the knowledge base. Every mutation refreshes the search index so
    the chatbot answers from the edited content immediately.

    Uploaded files are queued, not parsed here: :class:`IngestionWorker`
    processes them, and :meth:`watch_ingestions` picks up the results.
    """

    def __init__(
        self,
        database: Database,
        ingestion: IngestionService,
        index: KnowledgeIndex,
        uploads: UploadStore,
        on_upload: Optional[Callable[[], None]] = None,
    ):
        """
        Args:
            database: Connected database.
            ingestion: Parser/chunker/embedder (embeds typed text and edited chunks).
            index: In-memory search index to refresh after changes.
            uploads: Where queued upload files are stored for the worker.
            on_upload: Called after an upload is queued (wakes an in-process worker).
        """
        self._database = database
        self._ingestion = ingestion
        self._index = index
        self._uploads = uploads
        self._on_upload = on_upload
        self._last_processed_at: Optional[datetime] = None
        self._ingestion_mark_seen = False

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
        chunking: ChunkingSpec = ChunkingSpec(),
        enabled: bool = True,
    ) -> KnowledgeDocument:
        """
        Register an uploaded file and queue it for the ingestion worker.

        The document is returned immediately with status ``processing``; it
        becomes ``ready`` (or ``failed`` with an error) once the worker is done.
        Uploading with ``enabled=False`` keeps it out of answers until an admin
        has checked (and possibly re-chunked) it.

        A previously *failed* upload of the same file in the same source is
        replaced, so retrying never needs a manual delete first.

        Raises:
            InvalidRequestError: Empty file, unsupported type, too many PDF pages or unknown source.
            ConflictError: The same file already exists (queued or ready) in this source.
        """
        extension = Path(filename).suffix.lower()
        if not content:
            raise InvalidRequestError("The file is empty")
        if extension not in self._ingestion.supported_extensions():
            raise InvalidRequestError(f"Unsupported file type '{extension}'")
        if extension == ".pdf":
            pages = await asyncio.to_thread(self._ingestion.pdf_page_count, content)
            max_pages = Config.File.MAX_PDF_PAGES()
            if pages is not None and pages > max_pages:
                raise InvalidRequestError(f"The PDF has {pages} pages; the maximum is {max_pages}. Split it and upload the parts.")
        content_hash = hashlib.sha256(content).hexdigest()

        stored = False
        replaced: Optional[Tuple[uuid.UUID, str]] = None
        try:
            async with self._database.session() as session:
                repository = KnowledgeRepository(session)
                source = await self._require_source(repository, source_name)
                duplicate = await repository.find_by_hash(source.id, content_hash)
                if duplicate is not None and duplicate.status == DOCUMENT_STATUS_FAILED:
                    # Retrying a failed upload replaces it rather than being refused as a duplicate.
                    logger.info("Replacing failed document %s with a new upload of %s", duplicate.id, filename)
                    replaced = (duplicate.id, duplicate.file_type)
                    await repository.delete(duplicate)
                elif duplicate is not None:
                    raise ConflictError(f"This file already exists in '{source_name}' as '{duplicate.title}'")
                document = KnowledgeDocument(
                    source_id=source.id,
                    title=(title or Path(filename).stem)[:512],
                    original_filename=filename[:512],
                    file_type=extension.lstrip("."),
                    content_hash=content_hash,
                    extra_metadata=metadata,
                    status=DOCUMENT_STATUS_PROCESSING,
                    enabled=enabled,
                    chunking=chunking.to_json(),
                    created_by=created_by,
                )
                repository.add(document)
                await repository.flush()
                document.source = source
                # Stored before the row commits, so a worker never claims a job without its file.
                await asyncio.to_thread(self._uploads.save, document.id, document.file_type, content)
                stored = True
        except Exception:
            if stored:
                logger.exception("Could not queue upload %s; removing its stored file", filename)
                await asyncio.to_thread(self._uploads.delete, document.id, document.file_type)
            raise

        if replaced is not None:
            await asyncio.to_thread(self._uploads.delete, *replaced)
        logger.info("Queued ingestion of %s into %s as %s", filename, source_name, document.id)
        if self._on_upload is not None:
            self._on_upload()
        return document

    async def create_text_document(
        self,
        source_name: str,
        title: str,
        text: str,
        metadata: Dict[str, Any],
        created_by: Optional[str],
        chunking: ChunkingSpec = ChunkingSpec(),
    ) -> KnowledgeDocument:
        """
        Create a document from typed text (e.g. one FAQ entry), embedded synchronously.

        Raises:
            InvalidRequestError: Empty text, the strategy cannot chunk it, or unknown source.
        """
        drafts = (await self._chunk(text, chunking, EXTRACTION_TEXT)).drafts
        texts = [draft.content for draft in drafts]
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
                chunking=chunking.to_json(),
                extracted_text=text,
                extraction_method=EXTRACTION_TEXT,
                created_by=created_by,
            )
            repository.add(document)
            await repository.flush()
            repository.add_chunks(
                document, texts, vectors, [draft.metadata for draft in drafts], 0, self._ingestion.embedding_model
            )
            document.source = source
        logger.info("Created text document %s in %s (%d chunks)", document.id, source_name, len(texts))
        await self._index.refresh()
        return document

    async def update_document(self, document_id: uuid.UUID, changes: Dict[str, Any]) -> KnowledgeDocument:
        """
        Update a document's details; none of them re-embeds its chunks (ADM-16).

        Args:
            changes: Any of ``title``, ``metadata``, ``enabled``, ``source``,
                ``access_tier``, ``language``, ``version``, ``effective_from``,
                ``effective_to``, ``supersedes_id``. Naming a superseded document
                ends its validity the day before this one starts (ADM-17).

        Raises:
            NotFoundError: Unknown document or superseded document.
            InvalidRequestError: Unknown source or tier, or an empty validity range.
        """
        if "access_tier" in changes and changes["access_tier"] not in self._access_tiers():
            raise InvalidRequestError(f"access_tier must be one of {', '.join(self._access_tiers())}")
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
            for key in ("enabled", "access_tier", "language", "version", "effective_from", "effective_to"):
                if key in changes:
                    setattr(document, key, changes[key])
            if document.effective_from and document.effective_to and document.effective_to < document.effective_from:
                raise InvalidRequestError("effective_to must not be before effective_from")
            if changes.get("supersedes_id") is not None:
                await self._supersede(repository, document, changes["supersedes_id"])
        logger.info("Updated document %s: %s", document_id, sorted(changes))
        await self._index.refresh()
        return await self.get_document(document_id)

    @staticmethod
    def _access_tiers() -> List[str]:
        """Tiers a document may require: everyone, or one of the host's tiers."""
        return [TIER_ANONYMOUS, *Config.HostAuth.HOST_TIERS()]

    @staticmethod
    async def _supersede(repository: KnowledgeRepository, document: KnowledgeDocument, previous_id: uuid.UUID) -> None:
        """
        Mark ``document`` as the new version of ``previous_id`` and end the old one's validity.

        Raises:
            NotFoundError: Unknown previous document.
            InvalidRequestError: A document cannot supersede itself.
        """
        if previous_id == document.id:
            raise InvalidRequestError("A document cannot supersede itself")
        previous = await repository.get_document(previous_id)
        if previous is None:
            raise NotFoundError("Superseded document not found")
        document.supersedes_id = previous_id
        starts = document.effective_from or datetime.now(ZoneInfo(Config.Server.APP_TIMEZONE())).date()
        document.effective_from = starts
        ends = starts - timedelta(days=1)
        if previous.effective_to is None or previous.effective_to > ends:
            previous.effective_to = ends
        logger.info("Document %s supersedes %s from %s", document.id, previous_id, starts)

    async def answers_citing(self, document_id: uuid.UUID, limit: int) -> List[Dict[str, Any]]:
        """Recent assistant answers that cited ``document_id`` (ADM-18)."""
        async with self._database.session() as session:
            return await ConversationRepository(session).answers_citing(document_id, limit)

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
            file_type = document.file_type
            await repository.delete(document)
        # A still-queued upload's file would otherwise be left behind.
        await asyncio.to_thread(self._uploads.delete, document_id, file_type)
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

    # ------------------------------------------------------------------
    # Chunking strategy
    # ------------------------------------------------------------------

    async def _chunk(self, text: str, spec: ChunkingSpec, extraction_method: str) -> ChunkingResult:
        """
        Chunk text off the event loop.

        Raises:
            InvalidRequestError: The strategy cannot chunk this text.
        """
        try:
            return await asyncio.to_thread(self._ingestion.chunk, text, spec, extraction_method)
        except InvalidChunkingError as exc:
            raise InvalidRequestError(str(exc)) from exc

    async def _stored_text(self, repository: KnowledgeRepository, document_id: uuid.UUID) -> Tuple[str, str]:
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
        result = await self._chunk(text, spec, method)
        logger.info("Previewed %s on document %s: %d chunks", spec.strategy, document_id, len(result.drafts))
        return result

    async def rechunk(
        self, document_id: uuid.UUID, spec: ChunkingSpec, discard_manual_edits: bool
    ) -> KnowledgeDocument:
        """
        Replace a document's chunks with its stored text chunked by ``spec``.

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
        drafts = (await self._chunk(text, spec, method)).drafts
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
        return await self.get_document(document_id)

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

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

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
