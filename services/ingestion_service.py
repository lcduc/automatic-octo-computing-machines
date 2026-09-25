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
from utils.text_utils import TextUtils

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

    @property
    def embedding_model(self) -> str:
        """Name of the model new embeddings are produced with."""
        return self._embedding_service.model_name

    def supported_extensions(self) -> List[str]:
        """File extensions accepted for upload."""
        return list(Config.File.ALLOWED_EXTENSIONS())

    def _get_processor(self):
        """The shared document processor, built lazily."""
        if self._processor is None:
            self._processor = self._processor_factory()
        return self._processor

    async def extract_chunks(self, content: bytes, filename: str) -> List[str]:
        """
        Parse a file into cleaned text chunks.

        Raises:
            ValueError: Unsupported type, too large, or no text could be extracted.
        """
        if len(content) > Config.File.MAX_FILE_SIZE():
            raise ValueError(f"File too large; maximum is {Config.File.MAX_FILE_SIZE() // (1024 * 1024)}MB")
        async with self._parse_slots:
            logger.info("Parsing %s (%d bytes)", filename, len(content))
            try:
                result = await self._get_processor().process_file(content, filename)
            finally:
                self._release_memory()
        chunks = [chunk for chunk in result["documents"] if chunk.strip()]
        logger.info("Parsed %s into %d chunks", filename, len(chunks))
        return chunks

    @staticmethod
    def split_text(text: str) -> List[str]:
        """Split hand-written text into chunks using the configured chunk size."""
        pieces = TextUtils.chunk_text(
            text, chunk_size=Config.File.CHUNK_SIZE(), overlap=Config.File.CHUNK_OVERLAP()
        )
        return [cleaned for cleaned in (TextUtils.clean_chunk_text(p) for p in pieces) if cleaned.strip()]

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
