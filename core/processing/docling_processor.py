"""
Docling-based document processor for conversion and heading-aware chunking.
Uses Docling's DocumentConverter to convert a local file path, exports markdown,
then chunks by markdown headings (sections). Keeps a similar interface to
MarkItDownProcessor for drop-in replacement.
"""

# Standard library imports
import logging
import re
import tempfile
import time
import asyncio
from pathlib import Path
import os
from typing import List, Dict, Any, Optional

# Third-party imports
try:
    from docling.document_converter import DocumentConverter
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        PdfPipelineOptions, 
        TesseractOcrOptions,
        TesseractCliOcrOptions
    )
    from docling.document_converter import PdfFormatOption
except Exception as _e:  # defer hard failure to runtime path
    DocumentConverter = None  # type: ignore
    InputFormat = None  # type: ignore
    PdfPipelineOptions = None  # type: ignore
    TesseractOcrOptions = None  # type: ignore
    TesseractCliOcrOptions = None  # type: ignore
    PdfFormatOption = None  # type: ignore

# Local imports
from models.metadata import MetadataBuilder, ProcessingMethod, SourceType, ProcessingStatus
from config.file.file_config import FileConfig
from config.docling_config import DoclingConfig

logger = logging.getLogger(__name__)


class DoclingProcessor:
    """
    Document processor using Docling for multi-format conversion.
    Produces heading-based chunks from the exported markdown.
    """

    def __init__(self, enable_ocr: bool = False, llm_client=None, llm_model: str = None):
        """
        Initialize Docling processor with automatic OCR for PDFs and normal extraction for other formats.
        - PDFs: Always use OCR (like the test file)
        - Other formats: Use normal Docling extraction
        """
        self.llm_client = llm_client
        self.llm_model = llm_model
        
        try:
            if DocumentConverter is None:
                logger.warning("Docling not available at import time; will raise on first use")
                return
            
            # Set TESSDATA_PREFIX to project tessdata folder
            import os
            project_root = Path(__file__).parent.parent.parent
            tessdata_dir = project_root / "tessdata"
            os.environ['TESSDATA_PREFIX'] = str(tessdata_dir.absolute())
            
            # Also copy traineddata files to the default Tesseract tessdata directory
            tesseract_tessdata_dir = Path(DoclingConfig.TESSERACT_CMD()).parent / "tessdata"
            
            # Copy vie.traineddata
            vie_traineddata_src = tessdata_dir / "vie.traineddata"
            vie_traineddata_dst = tesseract_tessdata_dir / "vie.traineddata"
            
            if vie_traineddata_src.exists() and not vie_traineddata_dst.exists():
                try:
                    import shutil
                    shutil.copy2(vie_traineddata_src, vie_traineddata_dst)
                    logger.info(f"Copied vie.traineddata to {vie_traineddata_dst}")
                except Exception as e:
                    logger.warning(f"Failed to copy vie.traineddata: {e}")
            
            # Copy osd.traineddata
            osd_traineddata_src = tessdata_dir / "osd.traineddata"
            osd_traineddata_dst = tesseract_tessdata_dir / "osd.traineddata"
            
            if osd_traineddata_src.exists() and not osd_traineddata_dst.exists():
                try:
                    import shutil
                    shutil.copy2(osd_traineddata_src, osd_traineddata_dst)
                    logger.info(f"Copied osd.traineddata to {osd_traineddata_dst}")
                except Exception as e:
                    logger.warning(f"Failed to copy osd.traineddata: {e}")
            
            # Reset TESSDATA_PREFIX to default to avoid conflicts
            if 'TESSDATA_PREFIX' in os.environ:
                del os.environ['TESSDATA_PREFIX']
            
            # Check if Tesseract is available for PDF OCR
            tesseract_cmd = DoclingConfig.TESSERACT_CMD()
            self.tesseract_available = DoclingConfig.TESSERACT_CMD_EXISTS()
            
            if self.tesseract_available:
                logger.info(f"✅ Docling processor initialized with OCR support for PDFs")
                logger.info(f"   Tesseract path: {tesseract_cmd}")
                logger.info(f"   Tessdata directory: {project_root}")
            else:
                logger.warning(f"Tesseract not found at {tesseract_cmd}, PDFs will use basic extraction")
            
        except Exception as e:
            logger.warning(f"Failed to initialize Docling configuration: {e}")
            self.tesseract_available = False

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


    async def _process_pdf_page_by_page(self, content: bytes, filename: str) -> Dict[str, Any]:
        """
        Process PDFs with concurrent page processing to maximize performance while maintaining memory safety.
        Uses a semaphore to limit concurrent page processing and prevent memory exhaustion.
        """
        start_time = time.time()
        try:
            import fitz  # PyMuPDF
            import tempfile
            from pathlib import Path

            # Open PDF and get page count
            pdf_doc = fitz.open(stream=content, filetype="pdf")
            total_pages = len(pdf_doc)

            logger.info(f"Processing PDF with concurrent pages ({total_pages} pages) with optimized pipeline...")

            # Initialize pipeline once and reuse for all pages
            pipeline_options = PdfPipelineOptions()
            pipeline_options.do_ocr = True
            pipeline_options.do_table_structure = True  # Keep table structure for proper table extraction
            pipeline_options.table_structure_options.do_cell_matching = True

            # Use lower resolution OCR options
            ocr_options = TesseractCliOcrOptions(
                force_full_page_ocr=True,
                lang=["vie"],
                tesseract_cmd=DoclingConfig.TESSERACT_CMD()
            )
            pipeline_options.ocr_options = ocr_options

            # Create converter once and reuse
            converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(
                        pipeline_options=pipeline_options,
                    )
                }
            )

            logger.info("✅ Pipeline initialized once - reusing for all pages")

            # Create semaphore to limit concurrent page processing (configurable)
            max_concurrent_pages = DoclingConfig.OCR_CONCURRENT_PAGES()
            page_semaphore = asyncio.Semaphore(max_concurrent_pages)
            logger.info(f"Using {max_concurrent_pages} concurrent pages per PDF")
            
            async def process_single_page(page_num: int) -> tuple[int, str]:
                """Process a single page and return (page_num, text)"""
                async with page_semaphore:
                    logger.info(f"Processing page {page_num + 1} of {total_pages}")

                    # Create a temporary PDF with only this page
                    temp_pdf = fitz.open()
                    temp_pdf.insert_pdf(pdf_doc, from_page=page_num, to_page=page_num)

                    # Save temporary PDF to a more accessible location
                    temp_dir = Path(tempfile.gettempdir()) / "docling_ocr"
                    temp_dir.mkdir(exist_ok=True)
                    temp_path = temp_dir / f"page_{page_num}_{int(time.time())}_{id(asyncio.current_task())}.pdf"
                    temp_pdf.save(str(temp_path))

                    temp_pdf.close()

                    try:
                        # Process this single page using the reused converter
                        doc = converter.convert(str(temp_path)).document
                        page_text = doc.export_to_markdown()

                        # Clear memory after each page
                        self._clear_memory_caches()
                        logger.debug(f"Memory cleared after processing page {page_num + 1}")

                        return (page_num, page_text)

                    finally:
                        # Clean up temporary file
                        try:
                            if temp_path.exists():
                                temp_path.unlink(missing_ok=True)
                        except Exception as e:
                            logger.debug(f"Could not remove temp file {temp_path}: {e}")

            # Process all pages concurrently
            tasks = [process_single_page(page_num) for page_num in range(total_pages)]
            page_results = await asyncio.gather(*tasks, return_exceptions=True)

            pdf_doc.close()

            # Combine results in correct order
            total_text = ""
            processed_pages = 0
            
            for result in page_results:
                if isinstance(result, Exception):
                    logger.error(f"Page processing failed: {result}")
                    continue
                    
                page_num, page_text = result
                if page_text.strip():
                    total_text += f"\n\n--- Page {page_num + 1} ---\n\n" + page_text
                    processed_pages += 1

            # Chunk the combined text
            chunks = self._chunk_markdown_by_headings(total_text)

            logger.info(f"Concurrent page processing completed: {processed_pages}/{total_pages} pages processed")

            # Build proper metadata
            from models.metadata import MetadataBuilder, ProcessingMethod, SourceType, ProcessingStatus

            metadata = (
                MetadataBuilder()
                .set_source_info(
                    source_id=filename,
                    source_name=filename,
                    source_type=SourceType.FILE,
                )
                .set_file_info(file_extension=".pdf", file_size_bytes=len(content))
                .set_processing_info(
                    method=ProcessingMethod.DOCLING,
                    status=ProcessingStatus.SUCCESS,
                    processing_time=time.time() - start_time,
                )
                .set_content_stats(total_chunks=len(chunks), total_characters=len(total_text))
                .set_ocr_info(ocr_enabled=True, ocr_used=True)
                .set_content_features(
                    has_tables="|" in total_text,
                    has_images="![" in total_text,
                    has_links="[" in total_text and "]" in total_text,
                )
            ).build()

            # Add custom page-by-page info to metadata dict
            metadata_dict = metadata.model_dump() if hasattr(metadata, 'model_dump') else metadata.dict() if hasattr(metadata, 'dict') else dict(metadata)
            metadata_dict["total_pages"] = total_pages
            metadata_dict["processed_pages"] = processed_pages
            metadata_dict["processing_method"] = "concurrent_page_ocr"
            metadata_dict["concurrent_pages"] = max_concurrent_pages
            metadata_dict["concurrency_config"] = {
                "pages_per_pdf": max_concurrent_pages,
                "max_concurrent_files": DoclingConfig.OCR_MAX_CONCURRENT_FILES()
            }

            return {
                "documents": chunks,
                "metadata": metadata_dict
            }

        except Exception as e:
            logger.error(f"Concurrent page PDF processing failed: {e}")
            raise

    async def _process_large_pdf_in_chunks(self, content: bytes, filename: str) -> Dict[str, Any]:
        """
        Process large PDFs by splitting them into smaller chunks to prevent memory issues.
        This is a fallback method for PDFs that are too large for normal processing.
        """
        try:
            import fitz  # PyMuPDF
            import tempfile
            from pathlib import Path
            
            # Open PDF and get page count
            pdf_doc = fitz.open(stream=content, filetype="pdf")
            total_pages = len(pdf_doc)
            
            logger.info(f"Large PDF detected ({total_pages} pages), processing in chunks...")
            
            # Process in chunks of 3 pages to prevent memory issues (reduced from 5)
            chunk_pages = 3
            all_chunks = []
            total_text = ""
            
            for start_page in range(0, total_pages, chunk_pages):
                end_page = min(start_page + chunk_pages, total_pages)
                
                logger.info(f"Processing pages {start_page + 1}-{end_page} of {total_pages}")
                
                # Create a temporary PDF with only these pages
                temp_pdf = fitz.open()
                temp_pdf.insert_pdf(pdf_doc, from_page=start_page, to_page=end_page - 1)
                
                # Save temporary PDF to a more accessible location
                temp_dir = Path(tempfile.gettempdir()) / "docling_ocr"
                temp_dir.mkdir(exist_ok=True)
                temp_path = temp_dir / f"chunk_{start_page}_{end_page}_{int(time.time())}.pdf"
                temp_pdf.save(str(temp_path))
                
                temp_pdf.close()
                
                try:
                    # Process this chunk with Docling
                    pipeline_options = PdfPipelineOptions()
                    pipeline_options.do_ocr = True
                    pipeline_options.do_table_structure = True  # Keep table structure for proper table extraction
                    pipeline_options.table_structure_options.do_cell_matching = True

                    ocr_options = TesseractCliOcrOptions(
                        force_full_page_ocr=True,
                        lang=["vie"],
                        tesseract_cmd=DoclingConfig.TESSERACT_CMD()
                    )
                    pipeline_options.ocr_options = ocr_options

                    converter = DocumentConverter(
                        format_options={
                            InputFormat.PDF: PdfFormatOption(
                                pipeline_options=pipeline_options,
                            )
                        }
                    )
                    
                    # Process this chunk
                    doc = converter.convert(str(temp_path)).document
                    chunk_text = doc.export_to_markdown()
                    total_text += f"\n\n--- Page {start_page + 1}-{end_page} ---\n\n" + chunk_text
                    
                    # Clear memory after each chunk
                    self._clear_memory_caches()
                    logger.debug(f"Memory cleared after processing pages {start_page + 1}-{end_page}")
                    
                finally:
                    # Clean up temporary file
                    try:
                        if temp_path.exists():
                            temp_path.unlink(missing_ok=True)
                    except Exception as e:
                        logger.debug(f"Could not remove temp file {temp_path}: {e}")
            
            pdf_doc.close()
            
            # Chunk the combined text
            chunks = self._chunk_markdown_by_headings(total_text)
            
            return {
                "documents": chunks,
                "metadata": {
                    "total_pages": total_pages,
                    "chunks_processed": (total_pages + chunk_pages - 1) // chunk_pages,
                    "processing_method": "chunked_ocr"
                }
            }
            
        except Exception as e:
            logger.error(f"Chunked PDF processing failed: {e}")
            raise

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
        
        try:
            # Determine processing method based on file type
            is_pdf = suffix.lower() == '.pdf'
            
            if is_pdf and self.tesseract_available and TesseractCliOcrOptions and PdfPipelineOptions and InputFormat and PdfFormatOption:
                # Check PDF page count and choose processing method
                try:
                    import fitz
                    pdf_doc = fitz.open(stream=content, filetype="pdf")
                    page_count = len(pdf_doc)
                    pdf_doc.close()
                    
                    # Use page-by-page processing for all PDFs to minimize memory usage
                    if page_count > 0:
                        logger.info(f"PDF detected ({page_count} pages), using page-by-page processing...")
                        result = await self._process_pdf_page_by_page(content, filename)
                        return result
                    
                except Exception as e:
                    logger.warning(f"Could not determine PDF page count: {e}")
                
                # Fallback: PDF with OCR - use the exact same configuration as the test file
                pipeline_options = PdfPipelineOptions()
                pipeline_options.do_ocr = True
                pipeline_options.do_table_structure = True  # Keep table structure for proper table extraction
                pipeline_options.table_structure_options.do_cell_matching = True

                # Use the exact same OCR options as the test file
                ocr_options = TesseractCliOcrOptions(
                    force_full_page_ocr=True, 
                    lang=["vie"],
                    tesseract_cmd=DoclingConfig.TESSERACT_CMD()
                )

                pipeline_options.ocr_options = ocr_options

                converter = DocumentConverter(
                    format_options={
                        InputFormat.PDF: PdfFormatOption(
                            pipeline_options=pipeline_options,
                        )
                    }
                )
                
                logger.info("Processing PDF with OCR enabled (fallback method)...")
                doc = converter.convert(str(temp_path)).document
                text_md = doc.export_to_markdown()
                ocr_used = True
                
                # Clear memory immediately after OCR processing
                self._clear_memory_caches()
                logger.debug("Memory cleared after OCR processing")
                
            else:
                # Other file types or PDF without Tesseract - use normal Docling extraction
                converter = DocumentConverter()
                doc = converter.convert(str(temp_path)).document
                text_md = doc.export_to_markdown()
                ocr_used = False
                
                if is_pdf:
                    logger.info("Processing PDF with normal extraction (Tesseract not available)")
                else:
                    logger.info(f"Processing {suffix} file with normal extraction")

            # Heading-based chunking
            chunks = self._chunk_markdown_by_headings(text_md)

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
                .set_ocr_info(ocr_enabled=is_pdf and self.tesseract_available, ocr_used=ocr_used)
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

    def _chunk_text_intelligently(self, text: str) -> List[str]:
        """DEPRECATED: No longer used - chunking is now heading-only."""
        """
        Intelligently chunk text by paragraphs, sentences, and structure.
        Preserves text flow and prevents single-line chunks.
        """
        if not text or len(text.strip()) < 100:
            return [text.strip()] if text.strip() else []

        # First, try to split by double newlines (paragraphs)
        paragraphs = text.split('\n\n')
        
        chunks = []
        current_chunk = ""
        
        for paragraph in paragraphs:
            paragraph = paragraph.strip()
            if not paragraph:
                continue
                
            # If adding this paragraph would make chunk too large, start a new chunk
            if current_chunk and len(current_chunk) + len(paragraph) > 1500:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = paragraph
            else:
                if current_chunk:
                    current_chunk += "\n\n" + paragraph
                else:
                    current_chunk = paragraph
        
        # Add the last chunk
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        # If we still have very large chunks, split by sentences
        final_chunks = []
        for chunk in chunks:
            if len(chunk) > 2000:
                sentence_chunks = self._chunk_by_sentences(chunk)
                final_chunks.extend(sentence_chunks)
            else:
                final_chunks.append(chunk)
        
        return final_chunks

    def _chunk_by_sentences(self, text: str) -> List[str]:
        """DEPRECATED: No longer used - chunking is now heading-only."""
        """
        Split text by sentences while preserving text structure.
        """
        if not text or len(text) < 200:
            return [text] if text.strip() else []
        
        # Sentence endings
        sentence_endings = r'[.!?]+(?:\s|$)'
        sentences = re.split(sentence_endings, text)
        
        chunks = []
        current_chunk = ""
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
                
            # Add period if sentence doesn't end with punctuation
            if sentence and not re.search(r'[.!?]$', sentence):
                sentence += "."
            
            if current_chunk and len(current_chunk) + len(sentence) > 1000:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = sentence
            else:
                if current_chunk:
                    current_chunk += " " + sentence
                else:
                    current_chunk = sentence
        
        if current_chunk:
            chunks.append(current_chunk.strip())

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


class AsyncDoclingProcessor(DoclingProcessor):
    """Async wrapper to align with existing async pipeline interfaces."""

    async def process(self, content: bytes, filename: Optional[str] = None) -> List[str]:
        result = await self.process_document(content, filename or "unknown")
        return result.get("documents", [])