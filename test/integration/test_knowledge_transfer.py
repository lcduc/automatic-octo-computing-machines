"""KnowledgeTransferService against real PostgreSQL: a knowledge base round-trips without its embeddings."""

import pytest
from sqlalchemy import text

from core.retrieval.knowledge_index import KnowledgeIndex
from core.storage.upload_store import UploadStore
from models.knowledge_bundle import KnowledgeBundle
from services.errors import InvalidRequestError
from services.ingestion_service import IngestionService
from services.knowledge_service import KnowledgeService
from services.knowledge_transfer_service import KnowledgeTransferService
from .conftest import FakeEmbeddingService, FakeProcessor


@pytest.fixture
def knowledge(database, tmp_path):
    """Knowledge service (to create and embed content) and the transfer service on one database."""
    ingestion = IngestionService(FakeProcessor, FakeEmbeddingService(), max_concurrent_files=1)
    service = KnowledgeService(database, ingestion, KnowledgeIndex(database), UploadStore(str(tmp_path / "uploads")))
    return service, KnowledgeTransferService(database)


async def _embedded_chunks(database) -> int:
    async with database.session() as session:
        return (await session.execute(text("SELECT count(*) FROM knowledge_chunks WHERE embedding IS NOT NULL"))).scalar_one()


@pytest.mark.asyncio
async def test_round_trip_keeps_content_and_leaves_embedding_to_the_new_server(knowledge, database):
    service, transfer = knowledge
    document = await service.create_text_document("FAQ", "Giờ làm việc", "Mở cửa từ 8 giờ.", {"tag": "hours"}, "a@x.test", auto_approve=True)
    chunk_id = (await service.get_document(document.id)).chunks[0].id
    await service.update_chunk(chunk_id, "Mở cửa từ 7 giờ.", {"page": 2})
    bundle = KnowledgeBundle.model_validate_json((await transfer.export_bundle()).model_dump_json())

    await service.delete_document(document.id)
    result = await transfer.import_bundle(bundle)

    assert (result.documents_imported, result.documents_skipped, result.chunks_imported) == (1, 0, 1)
    assert await _embedded_chunks(database) == 0
    documents, _ = await service.list_documents("FAQ", None, None, 10, 0)
    restored = await service.get_document(documents[0].id)
    assert (restored.title, restored.extra_metadata) == ("Giờ làm việc", {"tag": "hours"})
    assert restored.chunks[0].content == "Mở cửa từ 7 giờ." and restored.chunks[0].edited
    assert await service.reembed_stale_chunks() == 1
    assert await _embedded_chunks(database) == 1


@pytest.mark.asyncio
async def test_importing_twice_skips_documents_already_present(knowledge):
    service, transfer = knowledge
    await service.create_text_document("FAQ", "Doc", "some text", {}, None, auto_approve=True)
    bundle = await transfer.export_bundle()

    result = await transfer.import_bundle(bundle)

    assert (result.documents_imported, result.documents_skipped) == (0, 1)


@pytest.mark.asyncio
async def test_import_creates_missing_sources(knowledge, database):
    service, transfer = knowledge
    await service.create_text_document("FAQ", "Doc", "some text", {}, None, auto_approve=True)
    bundle = await transfer.export_bundle()
    async with database.session() as session:
        await session.execute(text("DELETE FROM knowledge_documents"))
        await session.execute(text("DELETE FROM knowledge_sources WHERE name = 'FAQ'"))

    result = await transfer.import_bundle(bundle)

    assert result.sources_created == 1 and result.documents_imported == 1


@pytest.mark.asyncio
async def test_import_rejects_an_unknown_access_tier_and_changes_nothing(knowledge, database):
    service, transfer = knowledge
    await service.create_text_document("FAQ", "Doc", "some text", {}, None, auto_approve=True)
    bundle = await transfer.export_bundle()
    bundle.documents[0].access_tier = "no-such-tier"
    bundle.documents[0].content_hash = "different"

    with pytest.raises(InvalidRequestError, match="no-such-tier"):
        await transfer.import_bundle(bundle)
    async with database.session() as session:
        assert (await session.execute(text("SELECT count(*) FROM knowledge_documents"))).scalar_one() == 1


@pytest.mark.asyncio
async def test_imported_documents_wait_for_review_unless_the_operator_approves_them(knowledge, database):
    service, transfer = knowledge
    await service.create_text_document("FAQ", "Doc", "some text", {}, None, auto_approve=True)
    bundle = await transfer.export_bundle()
    for auto_approve, expected in ((False, "pending"), (True, "approved")):
        async with database.session() as session:
            await session.execute(text("DELETE FROM knowledge_documents"))
        await transfer.import_bundle(bundle, auto_approve=auto_approve)
        documents, _ = await service.list_documents("FAQ", None, None, 10, 0)
        assert [d.review_status for d in documents] == [expected]

    async with database.session() as session:
        await session.execute(text("UPDATE knowledge_documents SET review_status = 'pending'"))
    assert (await transfer.export_bundle()).documents == []  # only approved documents leave the server
