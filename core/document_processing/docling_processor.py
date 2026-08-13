"""
Docling-based document processor for conversion and heading-aware chunking.

Uses Docling's DocumentConverter to convert a local file path and export
markdown, then chunks by markdown headings. PDFs with no extractable text
layer (scanned/image-only) are routed around Docling's own OCR: pages are
rendered to images and run through a separate OCR engine (see
core/document_processing/ocr/), then chunked as plain text instead of
markdown headings, since OCR output has no heading structure.
"""

# Standard library imports
import asyncio
import logging
import re
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

# Third-party imports
try:
    from docling.document_converter import DocumentConverter
    import fitz  # PyMuPDF
except Exception:  # defer hard failure to runtime path
    DocumentConverter = None  # type: ignore
    fitz = None  # type: ignore

# Local imports
from config.settings import Config
from .engine_selector import get_ocr_engine
from models.metadata import MetadataBuilder, ProcessingMethod, SourceType, ProcessingStatus
from utils.text_utils import TextUtils

logger = logging.getLogger(__name__)


class DoclingProcessor:
    """
    Document processor using Docling for multi-format conversion.
    Produces heading-based chunks from the exported markdown.
    """

    def __init__(self, enable_ocr: bool = False, llm_client=None, llm_model: str = None):
        """
        Initialize the Docling processor.

        - PDFs with an extractable text layer, and all other supported
          formats: normal Docling conversion (no OCR).
        - PDFs with no extractable text layer (or ``OCR_FORCE_ALL_PDFS``):
          routed through the configured OCR engine instead of Docling's own
          OCR — see ``core/document_processing/ocr``.

        Args:
            enable_ocr: Deprecated — OCR is applied automatically based on
                whether a PDF has an extractable text layer.
            llm_client: OpenAI client for enhanced processing.
            llm_model: LLM model to use for enhanced processing.
        """
        self.llm_client = llm_client
        self.llm_model = llm_model

        # Converter reuse for memory efficiency
        self._normal_converter = None
        self._converter_lock = asyncio.Lock()

        if DocumentConverter is None:
            logger.warning("Docling not available at import time; will raise on first use")

    def _clear_memory_caches(self):
        """Clear all memory caches to prevent memory accumulation."""
        try:
            import gc
            import torch

            # Clear Python garbage collection multiple times
            for _ in range(3):
                gc.collect()

            # Clear PyTorch GPU cache if available
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()

            # Force garbage collection with aggressive settings
            if hasattr(gc, 'set_threshold'):
                gc.set_threshold(100, 10, 10)  # More aggressive garbage collection

            # Clear any potential caches in Docling (safer approach)
            try:
                # Only clear caches for known safe objects to avoid torch warnings
                import sys
                for module_name, module in sys.modules.items():
                    if 'docling' in module_name.lower() and hasattr(module, '__dict__'):
                        for attr_name, attr_value in module.__dict__.items():
                            try:
                                if hasattr(attr_value, 'clear_cache') and callable(getattr(attr_value, 'clear_cache')):
                                    attr_value.clear_cache()
                            except (AttributeError, TypeError, Exception):
                                # Skip any problematic objects
                                pass
            except Exception:
                pass

        except Exception as e:
            logger.debug(f"Cache clearing warning: {e}")

    async def _get_normal_converter(self):
        """Get or create normal converter (thread-safe)."""
        if self._normal_converter is None:
            async with self._converter_lock:
                if self._normal_converter is None:
                    logger.info("Initializing normal converter...")
                    self._normal_converter = DocumentConverter()
                    logger.info(" Normal converter initialized and cached")
        return self._normal_converter

    #: Pages sampled from the front of a PDF when checking for a text layer.
    _TEXT_LAYER_SAMPLE_PAGES = 3
    #: Page render scale factor passed to PyMuPDF; higher improves OCR accuracy.
    _OCR_RENDER_SCALE = 2.0

    def _pdf_needs_ocr(self, pdf_path: Path) -> bool:
        """
        Decide whether a PDF has to be OCR'd.

        Args:
            pdf_path: Path to the PDF on disk.

        Returns:
            True when ``OCR_FORCE_ALL_PDFS`` is set, or when none of the first
            few pages have an extractable text layer (i.e. the PDF is a scan).
            Defaults to True on inspection failure so a broken/unreadable PDF
            still gets a chance via OCR rather than silently returning no text.
        """
        if Config.OCR.OCR_FORCE_ALL_PDFS():
            return True
        try:
            doc = fitz.open(str(pdf_path))
            try:
                sample = range(min(self._TEXT_LAYER_SAMPLE_PAGES, len(doc)))
                has_text = any(doc[i].get_text().strip() for i in sample)
                return not has_text
            finally:
                doc.close()
        except Exception:
            logger.exception("Failed to inspect PDF text layer for %s; assuming OCR is needed", pdf_path)
            return True

    def _render_page_to_temp_image(self, pdf_doc, page_num: int) -> Path:
        """
        Render one PDF page to a temporary PNG file for OCR.

        Args:
            pdf_doc: An open ``fitz.Document``.
            page_num: Zero-based page index.

        Returns:
            Path to the rendered image. Caller is responsible for deleting it.
        """
        page = pdf_doc[page_num]
        matrix = fitz.Matrix(self._OCR_RENDER_SCALE, self._OCR_RENDER_SCALE)
        pixmap = page.get_pixmap(matrix=matrix)

        temp_dir = Path(tempfile.gettempdir()) / "ocr_pages"
        temp_dir.mkdir(exist_ok=True)
        image_path = temp_dir / f"page_{page_num}_{uuid.uuid4().hex}.png"
        pixmap.save(str(image_path))
        return image_path

    async def _ocr_pdf(self, pdf_path: Path, engine) -> str:
        """
        Render every page of a PDF and run each through the given OCR engine.

        Pages are OCR'd concurrently, bounded by ``OCR_CONCURRENT_PAGES``.
        Each engine call is blocking (network I/O for the online engine, model
        inference for the local ones) and is run in a worker thread so it
        doesn't stall the event loop.

        Args:
            pdf_path: Path to the PDF on disk.
            engine: The OCR engine to use (see ``core/document_processing/ocr``).

        Returns:
            Extracted text for all pages, concatenated with page markers.
        """
        pdf_doc = fitz.open(str(pdf_path))
        total_pages = len(pdf_doc)
        semaphore = asyncio.Semaphore(Config.OCR.OCR_CONCURRENT_PAGES())

        async def ocr_page(page_num: int) -> str:
            async with semaphore:
                image_path = self._render_page_to_temp_image(pdf_doc, page_num)
                try:
                    return await asyncio.to_thread(engine.extract_text, str(image_path))
                finally:
                    image_path.unlink(missing_ok=True)

        try:
            page_texts = await asyncio.gather(
                *(ocr_page(i) for i in range(total_pages)), return_exceptions=True
            )
        finally:
            pdf_doc.close()

        pages = []
        for i, text in enumerate(page_texts):
            if isinstance(text, Exception):
                logger.error("OCR failed for page %d of %s: %s", i + 1, pdf_path.name, text)
                continue
            if text and text.strip():
                pages.append(f"--- Page {i + 1} ---\n{text}")

        logger.info("OCR completed: %d/%d pages produced text", len(pages), total_pages)
        return "\n\n".join(pages)

    async def process_document(
        self,
        content: bytes,
        filename: str,
    ) -> Dict[str, Any]:
        """
        Process document content using Docling with simple OCR configuration.
        Uses the exact same approach as the test file for optimal OCR quality.
        """
        start_time = time.time()
        if DocumentConverter is None:
            raise RuntimeError("Docling DocumentConverter is not available. Install 'docling'.")

        # Write to a temp file for Docling to consume
        suffix = Path(filename).suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_file.write(content)
            temp_path = Path(temp_file.name)

        text_md: str = ""
        ocr_used: bool = False
        ocr_engine_name: Optional[str] = None

        try:
            is_pdf = suffix.lower() == ".pdf"
            needs_ocr = (
                is_pdf
                and Config.OCR.DOCLING_OCR_ENABLED()
                and self._pdf_needs_ocr(temp_path)
            )

            if needs_ocr:
                engine = get_ocr_engine()
                ocr_engine_name = engine.name
                logger.info("PDF has no extractable text layer; OCR via %s", engine.name)
                text_md = await self._ocr_pdf(temp_path, engine)
                ocr_used = True
                chunks = TextUtils.chunk_text(
                    text_md,
                    chunk_size=Config.File.CHUNK_SIZE(),
                    overlap=Config.File.CHUNK_OVERLAP(),
                    language="vi",
                )
            else:
                converter = await self._get_normal_converter()
                doc = converter.convert(str(temp_path)).document
                text_md = doc.export_to_markdown()
                ocr_used = False
                logger.info(
                    "Processing %s with normal extraction (no OCR needed)", suffix or filename
                )
                chunks = self._chunk_markdown_by_headings(text_md)

            self._clear_memory_caches()

            # Build metadata
            metadata = (
                MetadataBuilder()
                .set_source_info(
                    source_id=filename,
                    source_name=filename,
                    source_type=SourceType.FILE,
                )
                .set_file_info(file_extension=suffix.lower(), file_size_bytes=len(content))
                .set_processing_info(
                    method=ProcessingMethod.DOCLING,
                    status=ProcessingStatus.SUCCESS,
                    processing_time=time.time() - start_time,
                )
                .set_content_stats(total_chunks=len(chunks), total_characters=len(text_md))
                .set_ocr_info(ocr_enabled=Config.OCR.DOCLING_OCR_ENABLED(), ocr_used=ocr_used)
                .add_custom_metadata("ocr_engine", ocr_engine_name)
                .add_custom_metadata("ocr_forced_all_pdfs", Config.OCR.OCR_FORCE_ALL_PDFS())
                .set_content_features(
                    has_tables="|" in text_md,
                    has_images="![" in text_md,
                    has_links="[" in text_md and "]" in text_md,
                )
                .set_quality_metrics(conversion_success=True)
                .add_custom_metadata("markdown_length", len(text_md))
                .build()
            )

            return {
                "documents": chunks,
                "metadata": metadata.model_dump() if hasattr(metadata, 'model_dump') else metadata.dict() if hasattr(metadata, 'dict') else dict(metadata),
            }
        except Exception as e:
            logger.error(f"Docling processing failed for {filename}: {e}")
            raise
        finally:
            try:
                temp_path.unlink(missing_ok=True)  # type: ignore[attr-defined]
            except Exception:
                pass
            # Clear memory after processing
            self._clear_memory_caches()

    def _chunk_markdown_by_headings(self, markdown_text: str) -> List[str]:
        """
        Split markdown by headings only - no size limits, no fallback chunking.
        - Recognizes headings starting with '#' (ATX-style) at any level.
        - Each heading and its content becomes one chunk.
        - No size limits - keeps content together under each heading.
        - If no headings found, returns entire document as one chunk.
        """
        if not markdown_text:
            return []

        lines = markdown_text.splitlines()

        # First, try to chunk by markdown headings
        sections: List[List[str]] = []
        current: List[str] = []
        heading_pattern = re.compile(r"^#{1,6}\s+")

        def push_current():
            if current:
                sections.append(current.copy())
                current.clear()

        for line in lines:
            if heading_pattern.match(line):
                push_current()
                current.append(line)
            else:
                current.append(line)
        push_current()

        # Convert sections to strings, trimming leading/trailing blank lines
        chunks: List[str] = []
        for block in sections:
            # Trim
            while block and not block[0].strip():
                block.pop(0)
            while block and not block[-1].strip():
                block.pop()
            chunk = "\n".join(block).strip()
            if chunk:
                chunks.append(chunk)

        # If no headings found, return the entire document as one chunk
        if not chunks:
            chunks = [markdown_text.strip()]

        logger.info(f"Created {len(chunks)} chunks based on headings only (no size limits)")
        return chunks

    def get_supported_formats(self) -> List[str]:
        """Expose file types supported by Docling."""
        return [
            '.pdf', '.docx', '.pptx', '.html', '.htm',
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif',
            '.csv', '.xlsx', '.md', '.asciidoc', '.vtt',
            '.mp3', '.wav', '.m4a', '.json'
        ]

    def is_format_supported(self, filename: str) -> bool:
        extension = Path(filename).suffix.lower()
        return extension in self.get_supported_formats()
