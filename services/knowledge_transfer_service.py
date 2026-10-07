"""
Moves a knowledge base between servers (e.g. development to production) as one JSON bundle.
"""

# Standard library imports
import logging
from typing import Dict

# Local imports
from config.settings import Config
from core.storage.database import Database
from core.storage.knowledge_repository import KnowledgeRepository
from core.storage.tables.knowledge_tables import (
    DOCUMENT_STATUS_READY,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
    approved_by,
)
from models.caller import TIER_ANONYMOUS
from models.knowledge_bundle import (
    BundleChunk,
    BundleDocument,
    BundleSource,
    ImportResult,
    KnowledgeBundle,
)
from services.errors import InvalidRequestError

logger = logging.getLogger(__name__)

#: ``created_by`` recorded on imported documents.
IMPORT_CREATED_BY = "import"


class KnowledgeTransferService:
    """Exports ready documents and imports them without embeddings (the API embeds them at start-up)."""

    def __init__(self, database: Database):
        """
        Args:
            database: Connected database.
        """
        self._database = database

    async def export_bundle(self) -> KnowledgeBundle:
        """
        Every source and ready document with its chunk text.

        Documents without a content hash cannot be matched on import and are skipped.
        """
        # ceiling: the whole knowledge base is held in memory; stream per document if it outgrows RAM
        async with self._database.session() as session:
            repository = KnowledgeRepository(session)
            sources = [BundleSource.model_validate(source, from_attributes=True)
                       for source, _ in await repository.list_sources_with_counts()]
            documents = []
            for document in await repository.list_ready_documents_with_chunks():
                if not document.content_hash:
                    logger.warning("Skipping document %s (%s): it has no content hash", document.id, document.title)
                    continue
                documents.append(self._to_bundle_document(document))
        logger.info("Exported %d sources and %d documents", len(sources), len(documents))
        return KnowledgeBundle(sources=sources, documents=documents)

    async def import_bundle(self, bundle: KnowledgeBundle, auto_approve: bool = False) -> ImportResult:
        """
        Add the bundle's sources and documents that this server does not have yet.

        Imported documents wait for review like uploads, unless ``auto_approve``
        (the operator CLI) approves them on arrival.

        Existing sources are left as they are, and a document whose content hash is
        already in its source is skipped. Everything happens in one transaction.

        Raises:
            InvalidRequestError: A document names an unknown source or an access tier
                this server does not have.
        """
        self._check_tiers(bundle)
        declared = {source.name: source for source in bundle.sources}
        async with self._database.session() as session:
            repository = KnowledgeRepository(session)
            source_ids: Dict[str, int] = {}
            created = 0
            for name in sorted({document.source for document in bundle.documents} | set(declared)):
                source = await repository.get_source_by_name(name)
                if source is None:
                    if name not in declared:
                        raise InvalidRequestError(f"Document source '{name}' is not in the bundle or on this server")
                    source = KnowledgeSource(**declared[name].model_dump())
                    repository.add(source)
                    await repository.flush()
                    created += 1
                source_ids[name] = source.id
            imported = skipped = chunks = 0
            for document in bundle.documents:
                source_id = source_ids[document.source]
                if await repository.find_by_hash(source_id, document.content_hash) is not None:
                    skipped += 1
                    continue
                repository.add(self._to_document(document, source_id, auto_approve))
                await repository.flush()
                imported += 1
                chunks += len(document.chunks)
        logger.info("Imported %d documents (%d chunks), skipped %d, created %d sources",
                    imported, chunks, skipped, created)
        return ImportResult(created, imported, skipped, chunks)

    @staticmethod
    def _check_tiers(bundle: KnowledgeBundle) -> None:
        """
        Raises:
            InvalidRequestError: A document requires a tier this server does not define.
        """
        allowed = {TIER_ANONYMOUS, *Config.HostAuth.HOST_TIERS()}
        unknown = sorted({document.access_tier for document in bundle.documents} - allowed)
        if unknown:
            raise InvalidRequestError(
                f"Unknown access tier(s) {', '.join(unknown)}; this server has {', '.join(sorted(allowed))}"
            )

    @staticmethod
    def _to_bundle_document(document: KnowledgeDocument) -> BundleDocument:
        """A stored document as its portable form."""
        return BundleDocument(
            source=document.source.name,
            title=document.title,
            original_filename=document.original_filename,
            file_type=document.file_type,
            content_hash=document.content_hash,
            metadata=document.extra_metadata,
            enabled=document.enabled,
            chunking=document.chunking,
            extracted_text=document.extracted_text,
            extraction_method=document.extraction_method,
            access_tier=document.access_tier,
            language=document.language,
            version=document.version,
            effective_from=document.effective_from,
            effective_to=document.effective_to,
            chunks=[
                BundleChunk(content=chunk.content, metadata=chunk.extra_metadata, edited=chunk.edited)
                for chunk in document.chunks
            ],
        )

    @staticmethod
    def _to_document(document: BundleDocument, source_id: int, auto_approve: bool) -> KnowledgeDocument:
        """A ready document whose chunks have no embedding yet."""
        return KnowledgeDocument(
            source_id=source_id,
            title=document.title,
            original_filename=document.original_filename,
            file_type=document.file_type,
            content_hash=document.content_hash,
            extra_metadata=document.metadata,
            status=DOCUMENT_STATUS_READY,
            enabled=document.enabled,
            chunk_count=len(document.chunks),
            created_by=IMPORT_CREATED_BY,
            **(approved_by(IMPORT_CREATED_BY) if auto_approve else {}),
            chunking=document.chunking,
            extracted_text=document.extracted_text,
            extraction_method=document.extraction_method,
            access_tier=document.access_tier,
            language=document.language,
            version=document.version,
            effective_from=document.effective_from,
            effective_to=document.effective_to,
            chunks=[
                KnowledgeChunk(position=position, content=chunk.content, extra_metadata=chunk.metadata, edited=chunk.edited)
                for position, chunk in enumerate(document.chunks)
            ],
        )
