"""
Knowledge base management: sources and documents, kept in sync with the search index.

Chunk edits live in :mod:`services.chunk_editing_service`; index upkeep in
:mod:`services.index_sync_service`.
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
from app.config.settings import Config
from app.core.retrieval.knowledge_index import KnowledgeIndex
from app.core.storage.conversation_repository import ConversationRepository
from app.core.storage.database import Database
from app.core.storage.knowledge_repository import KnowledgeRepository
from app.core.storage.tables.knowledge_tables import (
    DOCUMENT_STATUS_FAILED,
    DOCUMENT_STATUS_PROCESSING,
    DOCUMENT_STATUS_READY,
    REVIEW_APPROVED,
    REVIEW_PENDING,
    REVIEW_REJECTED,
    KnowledgeDocument,
    KnowledgeSource,
    approved_by,
)
from app.core.storage.upload_store import UploadStore
from app.models.caller import TIER_ANONYMOUS
from app.models.knowledge import EXTRACTION_TEXT, ChunkingSpec
from .chunk_editing_service import chunk_off_loop
from .errors import ConflictError, InvalidRequestError, NotFoundError
from .ingestion_service import IngestionService

logger = logging.getLogger(__name__)


class KnowledgeService:
    """
    CRUD over the knowledge base. Every mutation refreshes the search index so
    the chatbot answers from the edited content immediately.

    Uploaded files are queued, not parsed here: :class:`IngestionWorker`
    processes them, and :class:`IndexSyncService` picks up the results.
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
            ingestion: Parser/chunker/embedder (checks uploads, embeds typed text).
            index: In-memory search index to refresh after changes.
            uploads: Where queued upload files are stored for the worker.
            on_upload: Called after an upload is queued (wakes an in-process worker).
        """
        self._database = database
        self._ingestion = ingestion
        self._index = index
        self._uploads = uploads
        self._on_upload = on_upload

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
        self,
        source_name: Optional[str],
        status: Optional[str],
        search: Optional[str],
        limit: int,
        offset: int,
        review_status: Optional[str] = None,
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
            return await repository.list_documents(source_id, status, search, limit, offset, review_status)

    async def review_counts(self) -> Dict[str, int]:
        """Documents per review status; every status is present, zero when empty."""
        async with self._database.session() as session:
            counts = await KnowledgeRepository(session).count_by_review_status()
        return {status: counts.get(status, 0) for status in (REVIEW_PENDING, REVIEW_APPROVED, REVIEW_REJECTED)}

    async def review_document(
        self, document_id: uuid.UUID, approve: bool, reviewer: str, note: Optional[str] = None
    ) -> KnowledgeDocument:
        """
        Approve or reject a document waiting for review.

        Approving makes it searchable (once it is also enabled); nobody is exempt,
        including the person who uploaded it.

        Raises:
            NotFoundError: Unknown document.
            ConflictError: The document was already reviewed, or approval was
                requested before ingestion produced a ready document.
        """
        async with self._database.session() as session:
            repository = KnowledgeRepository(session)
            document = await repository.lock_document(document_id)
            if document is None:
                raise NotFoundError("Document not found")
            if document.review_status != REVIEW_PENDING:
                raise ConflictError(f"This document was already {document.review_status}")
            if approve and document.status != DOCUMENT_STATUS_READY:
                raise ConflictError("Only a document that finished processing can be approved")
            document.review_status = REVIEW_APPROVED if approve else REVIEW_REJECTED
            document.reviewed_by = reviewer
            document.reviewed_at = datetime.now(ZoneInfo("UTC"))
            document.review_note = note
            outcome = document.review_status
        logger.info("Document %s %s by %s", document_id, outcome, reviewer)
        if approve:
            await self._index.refresh()
        return await self.get_document(document_id)

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
        auto_approve: bool = False,
    ) -> KnowledgeDocument:
        """
        Create a document from typed text (e.g. one FAQ entry), embedded synchronously.

        It waits for review like any new document, unless ``auto_approve`` (seed
        scripts run by an operator) marks it approved at creation.

        Raises:
            InvalidRequestError: Empty text, the strategy cannot chunk it, or unknown source.
        """
        drafts = (await chunk_off_loop(self._ingestion, text, chunking, EXTRACTION_TEXT)).drafts
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
                **(approved_by(created_by) if auto_approve else {}),
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
        if "access_tier" in changes and changes["access_tier"] not in self.access_tiers():
            raise InvalidRequestError(f"access_tier must be one of {', '.join(self.access_tiers())}")
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
    def access_tiers() -> List[str]:
        """Tiers a document may require: everyone, or one of the host's tiers."""
        return [TIER_ANONYMOUS, *Config.HostAuth.HOST_TIERS()]

    @staticmethod
    async def _supersede(repository: KnowledgeRepository, document: KnowledgeDocument, previous_id: uuid.UUID) -> None:
        """
        Mark ``document`` as the new version of ``previous_id`` and end the old one's validity.

        Raises:
            NotFoundError: Unknown previous document.
            InvalidRequestError: A document cannot supersede itself, or is not approved yet.
        """
        if previous_id == document.id:
            raise InvalidRequestError("A document cannot supersede itself")
        if document.review_status != REVIEW_APPROVED:
            raise InvalidRequestError("Approve the document before it supersedes another, or the old version would leave a gap")
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
