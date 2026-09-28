"""KnowledgeService and IngestionWorker against real PostgreSQL: CRUD keeps the index in sync, uploads go through the queue."""

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from core.retrieval.knowledge_index import KnowledgeIndex
from core.storage.knowledge_repository import IngestionQueueStats, KnowledgeRepository
from core.storage.upload_store import UploadStore
from services.errors import ConflictError, InvalidRequestError, NotFoundError
from services.ingestion_service import IngestionService
from services.ingestion_worker import CRASH_LOOP_ERROR, MAX_ATTEMPTS, IngestionWorker
from services.knowledge_service import KnowledgeService
from .conftest import FakeEmbeddingService, FakeProcessor


@pytest.fixture
def kb(database, tmp_path):
    """Service, index, upload store and worker sharing one database and upload dir."""
    ingestion = IngestionService(FakeProcessor, FakeEmbeddingService(), max_concurrent_files=1)
    index = KnowledgeIndex(database)
    uploads = UploadStore(str(tmp_path / "uploads"))
    worker = IngestionWorker(database, ingestion, uploads, concurrency=1)
    service = KnowledgeService(database, ingestion, index, uploads, worker.wake)
    return SimpleNamespace(service=service, index=index, uploads=uploads, worker=worker, database=database)


async def _expire_claim(database, document_id, attempts=None) -> None:
    """Make a claim look abandoned by a worker that died long ago."""
    async with database.session() as session:
        await session.execute(
            text("UPDATE knowledge_documents SET claimed_at = now() - interval '1 hour' WHERE id = :id"),
            {"id": document_id},
        )
        if attempts is not None:
            await session.execute(
                text("UPDATE knowledge_documents SET attempts = :n WHERE id = :id"), {"n": attempts, "id": document_id}
            )


async def _claim(database):
    async with database.session() as session:
        return await KnowledgeRepository(session).claim_next_upload(lease_seconds=120)


@pytest.mark.asyncio
async def test_text_document_is_searchable_and_edits_refresh_the_index(kb):
    service, index = kb.service, kb.index
    document = await service.create_text_document(
        "FAQ", "Giờ làm việc", "Văn phòng mở cửa từ 8 giờ sáng.", {"url": "https://x.test/faq"}, "admin@x.test"
    )
    assert index.snapshot.chunks[0].source == "FAQ"
    assert index.snapshot.chunks[0].metadata["url"] == "https://x.test/faq"

    chunk_id = (await service.get_document(document.id)).chunks[0].id
    await service.update_chunk(chunk_id, "Văn phòng mở cửa từ 7 giờ sáng.", {"page": 2})
    chunk = index.snapshot.chunks[0]
    assert "7 giờ" in chunk.content and chunk.metadata["page"] == 2

    await service.update_document(document.id, {"enabled": False})
    assert index.snapshot.is_empty
    await service.update_document(document.id, {"enabled": True, "source": "general", "metadata": {"tag": "hours"}})
    assert index.snapshot.chunks[0].source == "general"
    assert index.snapshot.chunks[0].metadata == {"tag": "hours", "page": 2}


@pytest.mark.asyncio
async def test_add_and_delete_chunk_keep_positions_contiguous(kb):
    service, index = kb.service, kb.index
    document = await service.create_text_document("general", "Doc", "first", {}, None)
    await service.add_chunk(document.id, "third", {}, position=None)
    await service.add_chunk(document.id, "second", {}, position=1)
    loaded = await service.get_document(document.id)
    assert [c.content for c in loaded.chunks] == ["first", "second", "third"]
    assert loaded.chunk_count == 3

    await service.delete_chunk(loaded.chunks[0].id)
    loaded = await service.get_document(document.id)
    assert [(c.position, c.content) for c in loaded.chunks] == [(0, "second"), (1, "third")]
    assert [c.content for c in index.snapshot.chunks] == ["second", "third"]


@pytest.mark.asyncio
async def test_upload_is_queued_then_ingested_by_the_worker(kb):
    service, index = kb.service, kb.index
    assert await service.refresh_index_if_ingested() is False  # records the starting mark
    content = b"Muc luong toi thieu\n\nThoi gian thu viec"
    document = await service.upload_file(content, "policy.txt", "contracts", None, {"year": 2026}, None)
    assert document.status == "processing"
    assert kb.uploads.path_for(document.id, "txt").exists()

    assert await kb.worker.process_next() is True
    assert await kb.worker.process_next() is False
    assert await service.refresh_index_if_ingested() is True
    assert await service.refresh_index_if_ingested() is False

    loaded = await service.get_document(document.id)
    assert loaded.status == "ready" and loaded.chunk_count == 2 and loaded.claimed_at is None
    assert {c.source for c in index.snapshot.chunks} == {"contracts"}
    assert not kb.uploads.path_for(document.id, "txt").exists()

    with pytest.raises(ConflictError):
        await service.upload_file(content, "policy-copy.txt", "contracts", None, {}, None)


@pytest.mark.asyncio
async def test_failed_ingestion_is_recorded_and_unknown_source_rejected(kb):
    service = kb.service
    with pytest.raises(InvalidRequestError):
        await service.create_text_document("nope", "t", "x", {}, None)
    service._ingestion.supported_extensions = lambda: [".bad"]
    document = await service.upload_file(b"x", "broken.bad", "general", None, {}, None)
    await kb.worker.process_next()
    loaded = await service.get_document(document.id)
    assert loaded.status == "failed" and "No content" in loaded.error
    assert not kb.uploads.path_for(document.id, "bad").exists()


@pytest.mark.asyncio
async def test_reuploading_a_failed_file_replaces_the_failed_document(kb):
    kb.service._ingestion.supported_extensions = lambda: [".bad"]
    failed = await kb.service.upload_file(b"x", "broken.bad", "general", None, {}, None)
    await kb.worker.process_next()

    retried = await kb.service.upload_file(b"x", "broken.bad", "general", None, {}, None)
    assert retried.id != failed.id and retried.status == "processing"
    with pytest.raises(NotFoundError):
        await kb.service.get_document(failed.id)


@pytest.mark.asyncio
async def test_pdf_over_the_page_limit_is_refused(kb, monkeypatch):
    monkeypatch.setenv("MAX_PDF_PAGES", "2")
    monkeypatch.setenv("ALLOWED_EXTENSIONS", ".pdf")
    with pytest.raises(InvalidRequestError, match="3 pages"):
        await kb.service.upload_file(_pdf_with_pages(3), "scan.pdf", "general", None, {}, None)
    accepted = await kb.service.upload_file(_pdf_with_pages(2), "short.pdf", "general", None, {}, None)
    assert accepted.status == "processing"


def _pdf_with_pages(count: int) -> bytes:
    """A minimal PDF with ``count`` blank pages."""
    import fitz

    with fitz.open() as document:
        for _ in range(count):
            document.new_page()
        return document.tobytes()


@pytest.mark.asyncio
async def test_queue_stats_report_pending_and_claimed_uploads(kb):
    assert await kb.service.ingestion_queue() == IngestionQueueStats(0, 0, None)
    await kb.service.upload_file(b"a\n\nb", "one.txt", "general", None, {}, None)
    await kb.service.upload_file(b"c\n\nd", "two.txt", "general", None, {}, None)
    held = await _claim(kb.database)  # another worker is busy with the first one

    stats = await kb.service.ingestion_queue()
    assert (stats.pending, stats.in_progress) == (2, 1) and stats.oldest_pending_seconds >= 0

    assert await kb.worker.process_next() is True  # takes the second upload
    stats = await kb.service.ingestion_queue()
    assert (stats.pending, stats.in_progress) == (1, 1)

    await _expire_claim(kb.database, held.document_id)  # that worker died
    stats = await kb.service.ingestion_queue()
    assert (stats.pending, stats.in_progress) == (1, 0)
    assert await kb.worker.process_next() is True
    assert await kb.service.ingestion_queue() == IngestionQueueStats(0, 0, None)


@pytest.mark.asyncio
async def test_live_claim_is_not_stolen_but_a_dead_workers_claim_is_retried(kb):
    document = await kb.service.upload_file(b"a\n\nb", "doc.txt", "general", None, {}, None)
    assert (await _claim(kb.database)).document_id == document.id  # a worker claims it, then dies

    assert await kb.worker.process_next() is False  # lease still live
    await _expire_claim(kb.database, document.id)
    assert await kb.worker.process_next() is True

    loaded = await kb.service.get_document(document.id)
    assert loaded.status == "ready" and loaded.attempts == 2


@pytest.mark.asyncio
async def test_upload_that_keeps_killing_the_worker_is_failed(kb):
    document = await kb.service.upload_file(b"a\n\nb", "doc.txt", "general", None, {}, None)
    await _expire_claim(kb.database, document.id, attempts=MAX_ATTEMPTS)
    assert await kb.worker.process_next() is True

    loaded = await kb.service.get_document(document.id)
    assert loaded.status == "failed" and loaded.error == CRASH_LOOP_ERROR
    assert not kb.uploads.path_for(document.id, "txt").exists()


@pytest.mark.asyncio
async def test_clean_shutdown_hands_the_job_back_to_the_queue(kb):
    started = asyncio.Event()

    async def parse_forever(content, filename):
        started.set()
        await asyncio.Event().wait()

    kb.service._ingestion.extract_chunks = parse_forever
    document = await kb.service.upload_file(b"a\n\nb", "doc.txt", "general", None, {}, None)
    task = asyncio.create_task(kb.worker.run())
    await asyncio.wait_for(started.wait(), timeout=10)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    loaded = await kb.service.get_document(document.id)
    assert loaded.status == "processing" and loaded.claimed_at is None and loaded.attempts == 0
    assert kb.uploads.path_for(document.id, "txt").exists()


@pytest.mark.asyncio
async def test_deleting_a_queued_upload_removes_its_file_and_the_job(kb):
    document = await kb.service.upload_file(b"a\n\nb", "doc.txt", "general", None, {}, None)
    await kb.service.delete_document(document.id)
    assert not kb.uploads.path_for(document.id, "txt").exists()
    assert await kb.worker.process_next() is False


@pytest.mark.asyncio
async def test_source_cannot_be_deleted_while_it_has_documents(kb):
    service, index = kb.service, kb.index
    await service.create_text_document("web_data", "Page", "content", {}, None)
    sources = {source.name: source for source, _ in await service.list_sources()}
    with pytest.raises(ConflictError):
        await service.delete_source(sources["web_data"].id)
    await service.update_source(sources["web_data"].id, {"enabled": False})
    assert index.snapshot.is_empty
