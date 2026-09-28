"""
Background ingestion: claims queued uploads, parses and embeds them, stores their chunks.
"""

# Standard library imports
import asyncio
import logging
import uuid
from typing import List, Optional

# Third-party imports
from sqlalchemy import func

# Local imports
from core.storage.database import Database
from core.storage.knowledge_repository import ClaimedUpload, KnowledgeRepository
from core.storage.tables.knowledge_tables import (
    DOCUMENT_STATUS_FAILED,
    DOCUMENT_STATUS_PROCESSING,
    DOCUMENT_STATUS_READY,
    KnowledgeDocument,
)
from core.storage.upload_store import UploadStore
from .ingestion_service import IngestionService

logger = logging.getLogger(__name__)

#: Seconds a claim stays valid without renewal; an upload held by a worker
#: that has been dead this long is taken over by another claim.
CLAIM_LEASE_SECONDS = 120
#: Seconds between lease renewals while a file is being parsed.
CLAIM_RENEW_SECONDS = 30
#: Seconds an idle worker waits before checking the queue again.
IDLE_POLL_SECONDS = 2.0
#: Claims after which an upload that keeps killing the worker (OOM, segfault) is failed.
MAX_ATTEMPTS = 3
#: Longest error text stored on a failed document.
MAX_ERROR_LENGTH = 500

MISSING_FILE_ERROR = "The uploaded file is no longer available; delete this document and upload it again."
CRASH_LOOP_ERROR = "Processing stopped the worker repeatedly; the file may be too large or malformed."
GENERIC_ERROR = "Processing failed; see server logs."


class IngestionWorker:
    """
    Drains the ingestion queue: documents in ``processing`` whose file is in the
    :class:`UploadStore`.

    Runs either inside the API process (``INGESTION_WORKER=embedded``) or as
    its own process via ``worker.py`` (``external``), so parsing can be given
    its own CPU and memory limits and a crash there cannot take the API down.
    Claims are leases, so a job left behind by a killed worker is retried by
    the next claim; a clean shutdown hands its job back straight away.
    """

    def __init__(self, database: Database, ingestion: IngestionService, uploads: UploadStore, concurrency: int):
        """
        Args:
            database: Connected database holding the queue.
            ingestion: Parser/chunker/embedder.
            uploads: Where queued files are stored.
            concurrency: Uploads processed at once.
        """
        self._database = database
        self._ingestion = ingestion
        self._uploads = uploads
        self._concurrency = max(1, concurrency)
        self._wake = asyncio.Event()

    def wake(self) -> None:
        """Signal that an upload was queued, so an idle worker in this process starts at once."""
        self._wake.set()

    async def run(self) -> None:
        """Process uploads until cancelled."""
        logger.info("Ingestion worker started with %d slot(s)", self._concurrency)
        try:
            await asyncio.gather(*(self._run_slot() for _ in range(self._concurrency)))
        finally:
            logger.info("Ingestion worker stopped")

    async def _run_slot(self) -> None:
        """One processing loop; the worker runs ``concurrency`` of them."""
        while True:
            try:
                processed = await self.process_next()
            except asyncio.CancelledError:
                raise
            except Exception:
                # E.g. the database is unreachable; the claimed job's lease
                # expires and it is retried, so keep polling.
                logger.exception("Ingestion worker iteration failed")
                processed = False
            if not processed:
                await self._wait_for_work()

    async def _wait_for_work(self) -> None:
        """Sleep until woken or the idle poll interval passes."""
        try:
            await asyncio.wait_for(self._wake.wait(), IDLE_POLL_SECONDS)
        except asyncio.TimeoutError:
            pass
        self._wake.clear()

    async def process_next(self) -> bool:
        """
        Claim and ingest the oldest pending upload.

        Returns:
            ``False`` when the queue is empty, ``True`` once a job was handled.
        """
        async with self._database.session() as session:
            job = await KnowledgeRepository(session).claim_next_upload(CLAIM_LEASE_SECONDS)
        if job is None:
            return False
        if job.attempts > MAX_ATTEMPTS:
            logger.error("Upload %s failed %d claims in a row; giving up", job.document_id, job.attempts - 1)
            await self._finish(job, DOCUMENT_STATUS_FAILED, CRASH_LOOP_ERROR)
            return True

        renewer = asyncio.create_task(self._keep_claim(job.document_id))
        try:
            await self._ingest(job)
        except asyncio.CancelledError:
            await self._release(job.document_id)
            raise
        finally:
            renewer.cancel()
        return True

    async def _ingest(self, job: ClaimedUpload) -> None:
        """Parse, embed and store one claimed upload, recording the outcome on its document."""
        filename = job.filename or f"upload.{job.file_type}"
        logger.info("Ingesting %s (document %s, attempt %d)", filename, job.document_id, job.attempts)
        try:
            content = await asyncio.to_thread(self._uploads.read, job.document_id, job.file_type)
        except FileNotFoundError:
            logger.error("Stored file for document %s is missing", job.document_id)
            await self._finish(job, DOCUMENT_STATUS_FAILED, MISSING_FILE_ERROR)
            return
        try:
            texts = await self._ingestion.extract_chunks(content, filename)
            vectors = await self._ingestion.embed(texts)
        except Exception as exc:
            logger.exception("Ingestion failed for %s", filename)
            message = str(exc) if isinstance(exc, ValueError) else GENERIC_ERROR
            await self._finish(job, DOCUMENT_STATUS_FAILED, message)
            return
        await self._finish(job, DOCUMENT_STATUS_READY, None, texts, vectors)
        logger.info("Ingested %s: %d chunks", filename, len(texts))

    async def _finish(
        self,
        job: ClaimedUpload,
        status: str,
        error: Optional[str],
        texts: Optional[List[str]] = None,
        vectors=None,
    ) -> None:
        """
        Record a job's outcome (with its chunks when ``ready``) and drop its stored file.

        The row lock plus the ``processing`` check make the outcome land once,
        even if a stalled worker and the one that took over its lease both finish.
        """
        async with self._database.session() as session:
            repository = KnowledgeRepository(session)
            document = await repository.lock_document(job.document_id)
            if document is None or document.status != DOCUMENT_STATUS_PROCESSING:
                logger.warning("Document %s was deleted or already finished; discarding result", job.document_id)
            else:
                if texts:
                    repository.add_chunks(
                        document, texts, vectors, [{} for _ in texts], 0, self._ingestion.embedding_model
                    )
                self._mark_finished(document, status, error)
        await asyncio.to_thread(self._uploads.delete, job.document_id, job.file_type)

    @staticmethod
    def _mark_finished(document: KnowledgeDocument, status: str, error: Optional[str]) -> None:
        """Set a document's final ingestion state and release its claim."""
        document.status = status
        document.error = error[:MAX_ERROR_LENGTH] if error else None
        document.claimed_at = None
        document.processed_at = func.now()

    async def _keep_claim(self, document_id: uuid.UUID) -> None:
        """Renew the lease on a job until cancelled."""
        while True:
            await asyncio.sleep(CLAIM_RENEW_SECONDS)
            try:
                async with self._database.session() as session:
                    await KnowledgeRepository(session).renew_claim(document_id)
            except Exception:
                logger.exception("Could not renew claim on document %s", document_id)

    async def _release(self, document_id: uuid.UUID) -> None:
        """Return an unfinished job to the queue on shutdown."""
        try:
            async with self._database.session() as session:
                await KnowledgeRepository(session).release_claim(document_id)
            logger.info("Released unfinished upload %s back to the queue", document_id)
        except Exception:
            logger.exception("Could not release claim on document %s; it is retried after the lease expires", document_id)
