"""
MarkItDown-based document processor for enhanced document conversion to Markdown.
Uses existing processors as fallback and enables OCR fallback in PDFProcessor when needed.
"""

import io
import logging
import tempfile
import re
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import asyncio

# Third-party imports
from markitdown import MarkItDown

# Local imports
from models.metadata import MetadataBuilder, ProcessingMethod, SourceType, ProcessingStatus

# Local imports
from config.file.file_config import FileConfig
from config.ocr.ocr_config import OCRConfig
from config.rag.rag_config import RAGConfig

logger = logging.getLogger(__name__)


class MarkItDownProcessor:
    """
    Enhanced document processor using Microsoft's MarkItDown for superior document conversion.
    Falls back to existing processors when MarkItDown fails, with OCR toggle for PDFs.
    """

    def __init__(self, enable_ocr: bool = True, llm_client=None, llm_model: str = None):
        """
        Initialize MarkItDown processor with OCR and LLM capabilities.
        
        Args:
            enable_ocr: Whether to enable OCR fallback in PDFProcessor
            llm_client: OpenAI client for enhanced processing
            llm_model: LLM model to use for enhanced processing
        """
        self.enable_ocr = enable_ocr
        self.llm_client = llm_client
        self.llm_model = llm_model
        
        # Initialize MarkItDown with appropriate configuration
        self.markitdown = MarkItDown(
            enable_plugins=False,  # Disable plugins for now
            llm_client=llm_client,
            llm_model=llm_model
        )
        
        logger.info(f"MarkItDown processor initialized with OCR fallback: {enable_ocr}")

    async def process_document(
        self, 
        content: bytes, 
        filename: str,
        chunk_size: int = 1000,
        overlap: int = 200
    ) -> Dict[str, Any]:
        """
        Process document content using MarkItDown with fallback to existing processors.
        
        Args:
            content: Raw file content in bytes
            filename: Original filename for processing
            chunk_size: Maximum size of text chunks
            overlap: Overlap between chunks
            
        Returns:
            Dict containing processed documents, metadata, and processing info
        """
        start_time = time.time()  # Track processing time
        try:
            # Create a temporary file for MarkItDown processing
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(filename).suffix) as temp_file:
                temp_file.write(content)
                temp_file_path = temp_file.name
            
            try:
                # Step 1: Try MarkItDown first
                result = await self._process_with_markitdown(temp_file_path, filename)
                
                # Check if MarkItDown returned meaningful content using existing logic
                if self._is_content_meaningful(result.text_content):
                    # MarkItDown succeeded - use its result
                    chunks = self._chunk_markdown_content(
                        result.text_content, 
                        chunk_size, 
                        overlap
                    )
                    
                    # Create normalized metadata
                    metadata = (MetadataBuilder()
                        .set_source_info(
                            source_id=filename,
                            source_name=filename,
                            source_type=SourceType.FILE
                        )
                        .set_file_info(
                            file_extension=Path(filename).suffix.lower(),
                            file_size_bytes=len(content)
                        )
                        .set_processing_info(
                            method=ProcessingMethod.MARKITDOWN,
                            status=ProcessingStatus.SUCCESS,
                            processing_time=time.time() - start_time
                        )
                        .set_content_stats(
                            total_chunks=len(chunks),
                            total_characters=len(result.text_content)
                        )
                        .set_ocr_info(ocr_enabled=False, ocr_used=False)
                        .set_content_features(
                            has_tables="|" in result.text_content,
                            has_images="![" in result.text_content,
                            has_links="[" in result.text_content and "]" in result.text_content
                        )
                        .set_quality_metrics(conversion_success=True)
                        .add_custom_metadata("markdown_length", len(result.text_content))
                        .build()
                    )
                    
                    return {
                        "documents": chunks,
                        "metadata": metadata.dict(),
                        "processing_info": {
                            "processor": "markitdown",
                            "ocr_used": False,
                            "chunk_count": len(chunks),
                            "fallback_level": 1
                        }
                    }
                else:
                    # MarkItDown failed - try existing processors
                    logger.info(f"MarkItDown returned poor content for {filename}, trying existing processors...")
                    return await self._existing_processor_fallback(content, filename, chunk_size, overlap, start_time)
                
            finally:
                # Clean up temporary file
                Path(temp_file_path).unlink(missing_ok=True)
                
        except Exception as e:
            logger.error(f"MarkItDown processing failed for {filename}: {e}")
            # MarkItDown failed - try existing processors
            return await self._existing_processor_fallback(content, filename, chunk_size, overlap, start_time)

    def _is_content_meaningful(self, text: str) -> bool:
        """
        Check if the content returned by MarkItDown is meaningful.
        Uses the existing TextUtils.needs_ocr_fallback logic.
        """
        from utils.text_utils import TextUtils
        return not TextUtils.needs_ocr_fallback(text)

    async def _existing_processor_fallback(self, content: bytes, filename: str, chunk_size: int, overlap: int, start_time: float = None) -> Dict[str, Any]:
        """
        Fallback to existing document processing modules when MarkItDown fails.
        Existing processors handle their own OCR fallback logic.
        """
        if start_time is None:
            start_time = time.time()
        try:
            logger.info(f"Using existing processor fallback for {filename}")
            
            # Import existing processors
            from core.processing.processors import (
                PDFProcessor, DocumentProcessor, SpreadsheetProcessor, TextProcessor
            )
            
            file_ext = Path(filename).suffix.lower()
            
            # Choose appropriate existing processor
            if file_ext == '.pdf':
                processor = PDFProcessor(enable_ocr=self.enable_ocr)
                # PDFProcessor handles its own OCR fallback internally
                result = await processor.process(content, filename)
                # PDFProcessor returns (chunks, ocr_time) tuple
                if isinstance(result, tuple):
                    chunks, ocr_time = result
                else:
                    chunks, ocr_time = result, None
                
                # Check if OCR was used (PDFProcessor already handled this)
                ocr_used = ocr_time is not None
                
            elif file_ext in ['.docx', '.doc']:
                processor = DocumentProcessor()
                chunks = await processor.process(content, filename)
                ocr_used = False
                ocr_time = None
            elif file_ext in ['.csv', '.xlsx', '.xls']:
                processor = SpreadsheetProcessor()
                chunks = await processor.process(content, filename)
                ocr_used = False
                ocr_time = None
            elif file_ext == '.txt':
                processor = TextProcessor()
                chunks = await processor.process(content, filename)
                ocr_used = False
                ocr_time = None
            else:
                raise ValueError(f"No existing processor available for {file_ext}")
            
            if chunks and len(chunks) > 0:
                # Existing processor succeeded (with or without OCR fallback)
                # Create normalized metadata for fallback case
                metadata = (MetadataBuilder()
                    .set_source_info(
                        source_id=filename,
                        source_name=filename,
                        source_type=SourceType.FILE
                    )
                    .set_file_info(
                        file_extension=file_ext,
                        file_size_bytes=len(content)
                    )
                    .set_processing_info(
                        method=ProcessingMethod.EXISTING_PROCESSOR,
                        status=ProcessingStatus.SUCCESS,
                        processing_time=time.time() - start_time
                    )
                    .set_content_stats(total_chunks=len(chunks))
                    .set_ocr_info(
                        ocr_enabled=OCRConfig.OCR_ENABLED(),
                        ocr_used=ocr_used,
                        ocr_time=ocr_time
                    )
                    .set_quality_metrics(conversion_success=True)
                    .build()
                )
                
                return {
                    "documents": chunks,
                    "metadata": metadata.dict(),
                    "processing_info": {
                        "processor": "existing_processor_fallback",
                        "ocr_used": ocr_used,
                        "chunk_count": len(chunks),
                        "fallback_level": 2
                    }
                }
            else:
                # Existing processor returned empty result
                # Create normalized metadata for error case
                metadata = (MetadataBuilder()
                    .set_source_info(
                        source_id=filename,
                        source_name=filename,
                        source_type=SourceType.FILE
                    )
                    .set_file_info(
                        file_extension=file_ext,
                        file_size_bytes=len(content)
                    )
                    .set_processing_info(
                        method=ProcessingMethod.EXISTING_PROCESSOR,
                        status=ProcessingStatus.FAILED
                    )
                    .set_content_stats(total_chunks=0)
                    .set_quality_metrics(conversion_success=False, error_count=1)
                    .add_custom_metadata("error", "Existing processor returned empty result")
                    .build()
                )
                
                return {
                    "documents": [],
                    "metadata": metadata.dict(),
                    "processing_info": {
                        "processor": "existing_processor_fallback",
                        "ocr_used": False,
                        "error": "Empty result",
                        "fallback_level": 2
                    }
                }
                
        except Exception as e:
            logger.error(f"Existing processor fallback failed for {filename}: {e}")
            # Create normalized metadata for exception case
            metadata = (MetadataBuilder()
                .set_source_info(
                    source_id=filename,
                    source_name=filename,
                    source_type=SourceType.FILE
                )
                .set_file_info(
                    file_extension=file_ext,
                    file_size_bytes=len(content)
                )
                .set_processing_info(
                    method=ProcessingMethod.EXISTING_PROCESSOR,
                    status=ProcessingStatus.FAILED
                )
                .set_content_stats(total_chunks=0)
                .set_quality_metrics(conversion_success=False, error_count=1)
                .add_custom_metadata("error", f"Existing processor fallback failed: {str(e)}")
                .build()
            )
            
            return {
                "documents": [],
                "metadata": metadata.dict(),
                "processing_info": {
                    "processor": "existing_processor_fallback",
                    "ocr_used": False,
                    "error": str(e),
                    "fallback_level": 2
                }
            }

    async def _process_with_markitdown(self, file_path: str, filename: str) -> Any:
        """
        Process document using MarkItDown with appropriate settings.
        
        Args:
            file_path: Path to the temporary file
            filename: Original filename for context
            
        Returns:
            MarkItDown conversion result
        """
        try:
            # Convert the document to markdown
            result = self.markitdown.convert(file_path)
            
            if not result or not result.text_content:
                raise ValueError("MarkItDown conversion failed - no content returned")
            
            logger.info(f"Successfully converted {filename} to markdown ({len(result.text_content)} chars)")
            return result
            
        except Exception as e:
            logger.error(f"MarkItDown conversion error for {filename}: {e}")
            raise

    def _chunk_markdown_content(
        self, 
        markdown_content: str, 
        chunk_size: int, 
        overlap: int
    ) -> List[str]:
        """
        Chunk markdown content while preserving structure and formatting.
        Uses the existing chunking logic from TextUtils.
        
        Args:
            markdown_content: The markdown text to chunk
            chunk_size: Maximum size of each chunk
            overlap: Overlap between chunks
            
        Returns:
            List of markdown chunks
        """
        if not markdown_content:
            return []
        
        # Use existing chunking method from TextUtils
        from utils.text_utils import TextUtils
        
        return TextUtils.chunk_text(
            markdown_content,
            chunk_size=chunk_size,
            overlap=overlap
        )

    @staticmethod
    def group_chunks_into_spans(chunks: List[str], expansion_radius: int = None, max_spans: int = None) -> List[str]:
        """
        Group chunks into larger spans by extending each selected chunk with neighbors.
        This mirrors the neighbor extension used during retrieval to reduce fragmentation.
        """
        if not chunks:
            return []
        if expansion_radius is None:
            expansion_radius = RAGConfig.CONTEXT_EXPANSION_RADIUS()
        if max_spans is None:
            max_spans = RAGConfig.MAX_CONTEXT_CHUNKS()

        spans: List[str] = []
        used = set()
        for i in range(len(chunks)):
            if i in used:
                continue
            start = max(0, i - expansion_radius)
            end = min(len(chunks), i + expansion_radius + 1)
            for j in range(start, end):
                used.add(j)
            span_text = "\n".join(chunks[start:end])
            spans.append(span_text)
            if len(spans) >= max_spans:
                break
        return spans
    


    def get_supported_formats(self) -> List[str]:
        """Get list of supported file formats by MarkItDown."""
        return [
            '.pdf', '.docx', '.doc', '.pptx', '.ppt', '.xlsx', '.xls',
            '.txt', '.csv', '.json', '.xml', '.html', '.htm',
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff',
            '.mp3', '.wav', '.m4a', '.epub', '.zip'
        ]

    def is_format_supported(self, filename: str) -> bool:
        """Check if a file format is supported."""
        extension = Path(filename).suffix.lower()
        return extension in self.get_supported_formats()


class AsyncMarkItDownProcessor(MarkItDownProcessor):
    """
    Asynchronous wrapper for MarkItDown processor to maintain compatibility
    with the existing async processing pipeline.
    """
    
    async def process(
        self, 
        content: bytes, 
        filename: Optional[str] = None
    ) -> List[str]:
        """
        Async interface for document processing.
        
        Args:
            content: Raw file content in bytes
            filename: Original filename
            
        Returns:
            List of text chunks
        """
        result = await self.process_document(content, filename or "unknown")
        return result.get("documents", [])
