"""KnowledgeService against real PostgreSQL: CRUD keeps the search index in sync."""

import pytest

from core.retrieval.knowledge_index import KnowledgeIndex
from services.errors import ConflictError, InvalidRequestError
from services.ingestion_service import IngestionService
from services.knowledge_service import KnowledgeService
from .conftest import FakeEmbeddingService, FakeProcessor


def _service(database):
    ingestion = IngestionService(FakeProcessor, FakeEmbeddingService(), max_concurrent_files=1)
    index = KnowledgeIndex(database)
    return KnowledgeService(database, ingestion, index), index


@pytest.mark.asyncio
async def test_text_document_is_searchable_and_edits_refresh_the_index(database):
    service, index = _service(database)
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
async def test_add_and_delete_chunk_keep_positions_contiguous(database):
    service, index = _service(database)
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
async def test_file_upload_ingests_in_background_and_rejects_duplicates(database):
    service, index = _service(database)
    content = b"Muc luong toi thieu\n\nThoi gian thu viec"
    document = await service.upload_file(content, "policy.txt", "contracts", None, {"year": 2026}, None)
    assert document.status == "processing"
    await service.wait_for_background_jobs()
    await index.refresh()

    loaded = await service.get_document(document.id)
    assert loaded.status == "ready" and loaded.chunk_count == 2
    assert {c.source for c in index.snapshot.chunks} == {"contracts"}

    with pytest.raises(ConflictError):
        await service.upload_file(content, "policy-copy.txt", "contracts", None, {}, None)


@pytest.mark.asyncio
async def test_failed_ingestion_is_recorded_and_unknown_source_rejected(database):
    service, _ = _service(database)
    with pytest.raises(InvalidRequestError):
        await service.create_text_document("nope", "t", "x", {}, None)
    service._ingestion.supported_extensions = lambda: [".bad"]
    document = await service.upload_file(b"x", "broken.bad", "general", None, {}, None)
    await service.wait_for_background_jobs()
    loaded = await service.get_document(document.id)
    assert loaded.status == "failed" and "No content" in loaded.error


@pytest.mark.asyncio
async def test_source_cannot_be_deleted_while_it_has_documents(database):
    service, index = _service(database)
    await service.create_text_document("web_data", "Page", "content", {}, None)
    sources = {source.name: source for source, _ in await service.list_sources()}
    with pytest.raises(ConflictError):
        await service.delete_source(sources["web_data"].id)
    await service.update_source(sources["web_data"].id, {"enabled": False})
    assert index.snapshot.is_empty
