"""
Turns uploaded files or typed text into embedded chunks ready for storage.
"""

# Standard library imports
import asyncio
import gc
import logging
from typing import Callable, List, Optional

# Third-party imports
import numpy as np

# Local imports
from config.settings import Config
from core.document_processing.chunking import Chunker
from models.knowledge import (
    AUTO_STRATEGY,
    EXTRACTION_LOCAL,
    ChunkDraft,
    ChunkingResult,
    ChunkingSpec,
    ExtractedDocument,
)

logger = logging.getLogger(__name__)


class IngestionService:
    """
    Parsing, chunking and embedding for the knowledge base.

    Parsing (Docling / OCR) is memory-hungry, so at most
    ``OCR_MAX_CONCURRENT_FILES`` files are parsed at once.
    """

    def __init__(self, processor_factory: Callable[[], object], embedding_service, max_concurrent_files: int):
        """
        Args:
            processor_factory: Builds the ``MainDocumentProcessor`` on first use
                (loading Docling is slow, so it is deferred until an upload).
            embedding_service: Exposes ``embed_passages`` and ``model_name``.
            max_concurrent_files: Files parsed in parallel.
        """
        self._processor_factory = processor_factory
        self._processor: Optional[object] = None
        self._embedding_service = embedding_service
        self._parse_slots = asyncio.Semaphore(max(1, max_concurrent_files))
        self._chunker = Chunker()

    @property
    def embedding_model(self) -> str:
        """Name of the model new embeddings are produced with."""
        return self._embedding_service.model_name

    def supported_extensions(self) -> List[str]:
        """File extensions accepted for upload."""
        return list(Config.File.ALLOWED_EXTENSIONS())

    @staticmethod
    def pdf_page_count(content: bytes) -> Optional[int]:
        """
        Pages in a PDF (reads only its page tree, not the page contents).

        Returns:
            The page count, or ``None`` if the file cannot be opened; the
            worker then records the parse failure on the document.
        """
        try:
            import pymupdf

            with pymupdf.open(stream=content, filetype="pdf") as document:
                return document.page_count
        except Exception:
            logger.exception("Could not count the pages of an uploaded PDF")
            return None

    def _get_processor(self):
        """The shared document processor, built lazily."""
        if self._processor is None:
            self._processor = self._processor_factory()
        return self._processor

    async def extract(self, content: bytes, filename: str, spec: ChunkingSpec) -> ExtractedDocument:
        """
        Parse a file and chunk its text with ``spec``.

        ``auto`` keeps the chunks the processor made for this file type; any
        other strategy re-splits the processor's full text.

        Raises:
            ValueError: Unsupported type, too large, no text could be extracted,
                or the strategy cannot chunk this text (``InvalidChunkingError``).
        """
        if len(content) > Config.File.MAX_FILE_SIZE():
            raise ValueError(f"File too large; maximum is {Config.File.MAX_FILE_SIZE() // (1024 * 1024)}MB")
        async with self._parse_slots:
            logger.info("Parsing %s (%d bytes)", filename, len(content))
            try:
                result = await self._get_processor().process_file(content, filename)
            finally:
                self._release_memory()
        processor_chunks = [chunk for chunk in result["documents"] if chunk.strip()]
        text = result.get("text") or "\n\n".join(processor_chunks)
        method = result.get("extraction_method") or EXTRACTION_LOCAL
        if spec.strategy == AUTO_STRATEGY:
            chunking = ChunkingResult([ChunkDraft(chunk) for chunk in processor_chunks])
        else:
            chunking = await asyncio.to_thread(self.chunk, text, spec, method)
        logger.info("Parsed %s (%s) into %d chunks with %s", filename, method, len(chunking.drafts), spec.strategy)
        return ExtractedDocument(text=text, extraction_method=method, chunking=chunking)

    def chunk(self, text: str, spec: ChunkingSpec, extraction_method: str) -> ChunkingResult:
        """
        Chunk already-extracted text (CPU-bound; call it in a worker thread).

        Raises:
            InvalidChunkingError: The strategy cannot chunk this text.
        """
        return self._chunker.split(text, spec, extraction_method)

    async def embed(self, texts: List[str]) -> np.ndarray:
        """Embed chunk texts in a worker thread (GPU/CPU-bound)."""
        return await asyncio.to_thread(self._embedding_service.embed_passages, texts)

    @staticmethod
    def _release_memory() -> None:
        """Return parser/OCR memory to the OS and the GPU allocator after each file."""
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            logger.exception("Could not release GPU memory after parsing")
