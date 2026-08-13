"""
Main document processor for orchestrating specialized file processors.
Provides unified interface for processing various file formats with metadata generation.

Routing is Docling-first: every format Docling accepts is converted by it, since
it produces layout-aware Markdown with heading-based chunking and OCRs PDFs that
have no text layer.

The local processors are a fallback for exactly two cases: Docling rejects the
format outright (``.txt``), or Docling *errors* on the file. An empty Docling
result deliberately does **not** fall back — for a scanned PDF that means the
OCR engines already ran and found nothing, and the local extractors read text
layers only, so retrying with them would return nothing while hiding the real
"no readable text" signal.
"""

# Standard library imports
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Local imports
from config.settings import Config
from models.metadata import ProcessingMethod
from .docling_processor import DoclingProcessor
from .file_manager import FileManager
from .processors import (
    BaseProcessor,
    DocumentProcessor,
    PDFProcessor,
    SpreadsheetProcessor,
    TextProcessor,
)

logger = logging.getLogger(__name__)


class MainDocumentProcessor:
    """
    Main document processor that orchestrates all specialized processors.
    Routes each file to the processor that actually supports its format and
    returns processed documents with comprehensive metadata.
    """

    SUPPORTED_EXTENSIONS = set(Config.File.ALLOWED_EXTENSIONS())

    def __init__(
        self,
        file_manager=None,
        enable_ocr: bool = None,  # Deprecated - OCR is now automatic for PDFs
        llm_client=None,
        llm_model: str = None,
    ):
        """
        Initialize main processor with file manager and Docling processor.
        - PDFs: Automatically OCR'd when they have no extractable text layer
        - Other formats: Use normal Docling extraction

        Args:
            file_manager: File manager for handling file operations
            enable_ocr: Deprecated - OCR is now automatic for PDFs
            llm_client: OpenAI client for enhanced processing
            llm_model: LLM model to use for enhanced processing
        """
        self.file_manager = file_manager if file_manager is not None else FileManager()

        self.docling_processor = DoclingProcessor(
            enable_ocr=False,  # OCR is now automatic based on file type
            llm_client=llm_client,
            llm_model=llm_model,
        )
        spreadsheet_processor = SpreadsheetProcessor()

        #: Local processor per extension, used when Docling declines the format
        #: or fails on the file. Every allowed extension has one, so a Docling
        #: outage degrades extraction quality rather than rejecting uploads.
        self._fallback_processors = {
            ".txt": TextProcessor(),
            ".pdf": PDFProcessor(),
            ".docx": DocumentProcessor(),
            ".csv": spreadsheet_processor,
            ".xlsx": spreadsheet_processor,
        }

        logger.info("MainDocumentProcessor initialized with automatic OCR for PDFs")

    def _local_processor_for(self, file_ext: str) -> Optional[BaseProcessor]:
        """
        Return the fallback processor for an extension, if one exists.

        Used when Docling declines the format or extracts nothing.

        Args:
            file_ext: Lower-cased file extension including the leading dot.

        Returns:
            The processor able to handle this extension locally, or ``None``.
        """
        return self._fallback_processors.get(file_ext)

    async def _extract_locally(
        self, file_content: bytes, filename: str, file_ext: str
    ) -> tuple:
        """
        Run the local fallback processor for a format.

        Args:
            file_content: Raw file bytes.
            filename: Original filename.
            file_ext: Lower-cased extension including the leading dot.

        Returns:
            ``(documents, metadata)``.

        Raises:
            ValueError: No local processor handles this extension.
        """
        processor = self._local_processor_for(file_ext)
        if processor is None:
            raise ValueError(f"No processor could extract content from {filename}")

        documents = await processor.process(file_content, filename)
        return documents, {
            "processing_method": ProcessingMethod.EXISTING_PROCESSOR.value,
            "processor_version": type(processor).__name__,
        }

    async def process_file(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        """
        Process file content using the processor that supports its format.

        Args:
            file_content: Raw file content in bytes
            filename: Original filename for processing and metadata

        Returns:
            Dict containing processed documents and comprehensive metadata

        Raises:
            ValueError: The extension is not allowed, or no content was extracted.
        """
        file_ext = Path(filename).suffix.lower()

        # Validate file extension against supported types
        if file_ext not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported file type: {file_ext}")

        try:
            if self.docling_processor.is_format_supported(filename):
                try:
                    result = await self.docling_processor.process_document(
                        file_content, filename
                    )
                    metadata = result.get("metadata", {})
                    documents = result.get("documents") or []
                    extra_metadata = {
                        **metadata,
                        "processor_version": metadata.get(
                            "processor_version", "docling"
                        ),
                    }
                except Exception:
                    # Only a *failed* conversion falls back. An empty result is
                    # not a failure to route around: for a scanned PDF, Docling
                    # has already run the OCR engines, and the local extractors
                    # read text layers only — they would return nothing too, and
                    # would disguise "this document has no readable text".
                    logger.warning(
                        "Docling conversion failed for %s; using local processor",
                        filename,
                        exc_info=True,
                    )
                    documents, extra_metadata = await self._extract_locally(
                        file_content, filename, file_ext
                    )
            else:
                # Docling rejects this format outright (e.g. .txt).
                documents, extra_metadata = await self._extract_locally(
                    file_content, filename, file_ext
                )

            if not documents:
                raise ValueError(f"No content could be extracted from {filename}")

            # Save chunks to files for persistence and debugging
            chunks_dir = await self.file_manager.save_chunks_to_files(
                documents, filename
            )

            return {
                "documents": documents,
                "metadata": {
                    **extra_metadata,
                    "chunks_directory": chunks_dir,
                    "processing_timestamp": datetime.now().isoformat(),
                    "chunk_size": Config.File.CHUNK_SIZE(),
                    "chunk_overlap": Config.File.CHUNK_OVERLAP(),
                    "file_type": file_ext,
                    "total_chunks": len(documents),
                },
            }

        except Exception:
            logger.exception("Error processing file %s", filename)
            raise

    def get_supported_formats(self) -> List[str]:
        """Get list of supported file formats."""
        return list(self.SUPPORTED_EXTENSIONS)

    def is_format_supported(self, filename: str) -> bool:
        """
        Check whether a file can actually be processed.

        Mirrors :meth:`process_file`'s routing: allowed, *and* handled by either
        Docling or a local fallback processor. Requiring Docling approval for
        every format (as this once did) wrongly rejected ``.txt``, which Docling
        does not accept but the local processor does.
        """
        extension = Path(filename).suffix.lower()
        if extension not in self.SUPPORTED_EXTENSIONS:
            return False
        return (
            self.docling_processor.is_format_supported(filename)
            or self._local_processor_for(extension) is not None
        )

    def is_supported_file(self, filename: str) -> bool:
        """Check if a file is supported (alias for is_format_supported for compatibility)."""
        return self.is_format_supported(filename)

    def get_ocr_status(self) -> bool:
        """Get current OCR fallback status."""
        return getattr(self.docling_processor, 'enable_ocr', False)
