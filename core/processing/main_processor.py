"""
Main document processor for orchestrating specialized file processors.
Provides unified interface for processing various file formats with metadata generation.
Now uses Docling for enhanced document conversion with heading-aware chunking.
"""

# Standard library imports
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

# Local imports
from setting import Config
from config.file.file_config import FileConfig
from config.docling_config import DoclingConfig
from .docling_processor import DoclingProcessor, AsyncDoclingProcessor
from .file_manager import FileManager


class MainDocumentProcessor:
    """
    Main document processor that orchestrates all specialized processors.
    Now uses Docling for enhanced document conversion with heading-aware chunking.
    Provides unified interface for processing various file formats with comprehensive metadata.
    """

    SUPPORTED_EXTENSIONS = set(FileConfig.ALLOWED_EXTENSIONS())

    def __init__(
        self,
        file_manager=None,
        enable_ocr: bool = None,
        llm_client=None,
        llm_model: str = None,
    ):
        """
        Initialize main processor with file manager and Docling processor.
        Sets up processor for different file extensions with heading-aware chunking.
        Uses Docling with embedded EasyOCR for document processing.
        
        Args:
            file_manager: File manager for handling file operations
            enable_ocr: Whether to enable OCR processing (defaults to config setting)
            llm_client: OpenAI client for enhanced processing
            llm_model: LLM model to use for enhanced processing
        """
        self.file_manager = file_manager if file_manager is not None else FileManager()
        
        # Use provided OCR setting or default from config
        if enable_ocr is None:
            enable_ocr = DoclingConfig.DOCLING_OCR_ENABLED()
        
        # Initialize Docling processor with embedded EasyOCR
        self.docling_processor = DoclingProcessor(
            enable_ocr=enable_ocr,
            llm_client=llm_client,
            llm_model=llm_model
        )
        
        # Create async wrapper for compatibility
        self.async_processor = AsyncDoclingProcessor(
            enable_ocr=enable_ocr,
            llm_client=llm_client,
            llm_model=llm_model
        )
        
        logger = __import__('logging').getLogger(__name__)
        logger.info(f"MainDocumentProcessor initialized with Docling and embedded EasyOCR (OCR flag: {enable_ocr})")

    async def process_file(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        """
        Process file content using Docling with heading-based chunking and extract text content with comprehensive metadata.
        Handles file validation, processing, and chunk storage.

        Args:
            file_content: Raw file content in bytes
            filename: Original filename for processing and metadata

        Returns:
            Dict containing processed documents and comprehensive metadata
        """
        file_ext = Path(filename).suffix.lower()

        # Validate file extension against supported types
        if file_ext not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported file type: {file_ext}")

        # Check if Docling supports this format
        if not self.docling_processor.is_format_supported(filename):
            raise ValueError(f"Docling does not support {file_ext} files")

        try:
            # Process the file using Docling with heading-aware chunking
            result = await self.docling_processor.process_document(
                file_content, 
                filename,
                chunk_size=FileConfig.CHUNK_SIZE() if hasattr(FileConfig, 'CHUNK_SIZE') else 1000,
                overlap=FileConfig.CHUNK_OVERLAP() if hasattr(FileConfig, 'CHUNK_OVERLAP') else 0
            )

            # Validate that content was successfully extracted
            if not result.get("documents"):
                raise ValueError(f"No content could be extracted from {filename}")

            # Save chunks to files for persistence and debugging
            chunks_dir = await self.file_manager.save_chunks_to_files(
                result["documents"], filename
            )

            # Return comprehensive metadata and processed documents
            return {
                "documents": result["documents"],
                "metadata": {
                    **result["metadata"],
                    "chunks_directory": chunks_dir,
                    "processing_timestamp": datetime.now().isoformat(),
                    "processor_version": result["processing_info"]["processor"],
                    "chunk_size": FileConfig.CHUNK_SIZE() if hasattr(FileConfig, 'CHUNK_SIZE') else 1000,
                    "chunk_overlap": FileConfig.CHUNK_OVERLAP() if hasattr(FileConfig, 'CHUNK_OVERLAP') else 0,
                },
                "processing_info": result["processing_info"]
            }

        except Exception as e:
            logger = __import__('logging').getLogger(__name__)
            logger.error(f"Error processing file {filename}: {e}")
            raise

    def get_supported_formats(self) -> List[str]:
        """Get list of supported file formats."""
        return list(self.SUPPORTED_EXTENSIONS)

    def is_format_supported(self, filename: str) -> bool:
        """Check if a file format is supported."""
        extension = Path(filename).suffix.lower()
        return extension in self.SUPPORTED_EXTENSIONS and self.docling_processor.is_format_supported(filename)

    def is_supported_file(self, filename: str) -> bool:
        """Check if a file is supported (alias for is_format_supported for compatibility)."""
        return self.is_format_supported(filename)

    def get_ocr_status(self) -> bool:
        """Get current OCR fallback status."""
        return getattr(self.docling_processor, 'enable_ocr', False)
