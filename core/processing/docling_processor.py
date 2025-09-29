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
except Exception as _e:  # defer hard failure to runtime path
    DocumentConverter = None  # type: ignore

# Local imports
from models.metadata import MetadataBuilder, ProcessingMethod, SourceType, ProcessingStatus
from config.file.file_config import FileConfig
from config.ocr.ocr_config import OCRConfig

logger = logging.getLogger(__name__)


def _docling_convert_worker(args) -> str:
    """Subprocess worker to convert a file path with Docling and return markdown text.
    Args: (path_str, kwargs_dict)
    """
    import os as _os
    import time as _time
    try:
        # Re-import inside subprocess for isolation
        from docling.document_converter import DocumentConverter as _DC  # type: ignore
    except Exception as _e:  # pragma: no cover
        raise RuntimeError(f"Docling unavailable in worker: {_e}")

    path_str, kwargs = args
    start = _time.time()
    converter = None
    try:
        converter = _DC(**kwargs) if kwargs else _DC()
        result = converter.convert(path_str)
        # Prefer explicit export; fallback to attributes
        try:
            md = result.document.export_to_markdown()  # type: ignore[attr-defined]
        except Exception:
            md = getattr(result, "markdown", "") or getattr(result, "text", "")
        return md or ""
    finally:
        # Best-effort GPU/RAM release within subprocess
        try:
            import torch as _torch  # type: ignore
            if getattr(_torch, "cuda", None) and _torch.cuda.is_available():
                _torch.cuda.empty_cache()
        except Exception:
            pass
        del converter
        import gc as _gc
        _gc.collect()


class DoclingProcessor:
    """
    Document processor using Docling for multi-format conversion.
    Produces heading-based chunks from the exported markdown.
    """

    def __init__(self, enable_ocr: bool = True, llm_client=None, llm_model: str = None):
        self.enable_ocr = enable_ocr
        self.llm_client = llm_client
        self.llm_model = llm_model
        if DocumentConverter is None:
            logger.warning("Docling not available at import time; will raise on first use")

        # Prepare OCR-friendly kwargs variants for subprocess converter
        self.converter_kwargs_variants: List[Dict[str, Any]] = []
        if DocumentConverter is not None:
            # Use configuration from OCRConfig
            try:
                from config.ocr.ocr_config import OCRConfig
                
                # Set environment variables based on config
                os.environ.setdefault("DOCLING_OCR_ENABLED", str(OCRConfig.DOCLING_OCR_ENABLED()).lower())
                os.environ.setdefault("DOCLING_OCR_LANGS", ",".join(OCRConfig.DOCLING_OCR_LANGS()))
                os.environ.setdefault("DOCLING_OCR_DPI", str(OCRConfig.DOCLING_OCR_DPI()))
                os.environ.setdefault("DOCLING_OCR_GPU", str(OCRConfig.DOCLING_OCR_GPU()).lower())
                os.environ.setdefault("DOCLING_OCR_TIMEOUT_SEC", str(OCRConfig.DOCLING_OCR_TIMEOUT_SEC()))
                os.environ.setdefault("DOCLING_OCR_SUBPROCESS", str(OCRConfig.DOCLING_OCR_SUBPROCESS()).lower())
                
                # Get configuration values
                ocr_enabled = OCRConfig.DOCLING_OCR_ENABLED()
                ocr_langs = OCRConfig.DOCLING_OCR_LANGS()
                ocr_dpi = OCRConfig.DOCLING_OCR_DPI()
                ocr_gpu = OCRConfig.DOCLING_OCR_GPU()
                
            except Exception as e:
                logger.warning(f"Failed to load OCR config, using defaults: {e}")
                ocr_enabled = True
                ocr_langs = ["vi", "en"]
                ocr_dpi = 300
                ocr_gpu = False

            # Docling DocumentConverter doesn't accept OCR parameters in constructor
            # OCR is handled automatically based on file format and content
            ocr_kwargs_variants: List[Dict[str, Any]] = [
                # Empty kwargs - Docling handles OCR automatically
                {},
            ]
            # We don't keep a persistent converter to allow process-isolated runs
            self.converter_kwargs_variants = ocr_kwargs_variants

        logger.info(f"Docling processor initialized with OCR preference flag: {enable_ocr}")

    async def process_document(
        self,
        content: bytes,
        filename: str,
        chunk_size: int = 1000,
        overlap: int = 0,
    ) -> Dict[str, Any]:
        """
        Process document content using Docling. We export to markdown and then
        chunk by headings so each top-level/section becomes a chunk.
        chunk_size/overlap are accepted for compatibility but not used when
        heading-based chunking is enabled.
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
            # Convert using isolated subprocess to release RAM/GPU after each job
            from concurrent.futures import ProcessPoolExecutor, TimeoutError as _Timeout
            text_md = ""
            # Get timeout and subprocess settings from config
            try:
                from config.ocr.ocr_config import OCRConfig
                timeout_s = float(OCRConfig.DOCLING_OCR_TIMEOUT_SEC())
                use_subprocess = OCRConfig.DOCLING_OCR_SUBPROCESS()
            
                # For debugging, try in-process first for PDFs
                if filename.lower().endswith('.pdf'):
                    logger.debug("PDF detected, trying in-process conversion first")
                    use_subprocess = False
            except Exception:
                timeout_s = 0.0
                use_subprocess = True
            with ProcessPoolExecutor(max_workers=1) as _pool:
                # Try each kwargs variant until one succeeds
                for kwargs in self.converter_kwargs_variants or [{}]:
                    if use_subprocess:
                        # On Windows, prefer standalone worker to avoid importing FastAPI in child.
                        try:
                            import subprocess, json as _json, sys as _sys
                            cmd = [
                                _sys.executable,
                                "-m",
                                "core.processing.docling_worker",
                                str(temp_path),
                                _json.dumps(kwargs),
                            ]
                            logger.debug(f"Launching docling worker: {' '.join(cmd)}")
                            logger.debug(f"Temp file path: {temp_path}")
                            logger.debug(f"Temp file exists: {temp_path.exists()}")
                            logger.debug(f"Temp file size: {temp_path.stat().st_size if temp_path.exists() else 'N/A'} bytes")
                            proc = await asyncio.create_subprocess_exec(
                                *cmd,
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE,
                            )
                            if timeout_s and timeout_s > 0:
                                try:
                                    await asyncio.wait_for(proc.wait(), timeout=timeout_s)
                                except asyncio.TimeoutError:
                                    proc.kill()
                                    await proc.communicate()
                                    logger.warning("⚠️ Docling OCR subprocess timed out; trying next variant")
                                    continue
                            else:
                                await proc.wait()
                            out, err = await proc.communicate()
                            err_text = err.decode("utf-8", errors="ignore").strip()
                            if proc.returncode == 0:
                                if err_text:
                                    logger.debug(f"Docling worker stderr: {err_text}")
                                text_md = out.decode("utf-8", errors="ignore")
                            else:
                                logger.warning(f"⚠️ Docling worker error (rc={proc.returncode}): {err_text}")
                                logger.debug(f"Full stderr: {err_text}")
                                logger.debug(f"Full stdout: {out.decode('utf-8', errors='ignore')}")
                                continue
                        except Exception as _e:
                            logger.warning(f"⚠️ Docling OCR subprocess failed with {kwargs}: {_e}")
                            logger.debug(f"Exception details: {type(_e).__name__}: {_e}")
                            continue
                    else:
                        # Direct (in-process) conversion for debugging visibility
                        try:
                            logger.debug(f"Running in-process Docling with kwargs={kwargs}")
                            conv = DocumentConverter(**kwargs) if kwargs else DocumentConverter()
                            rs = conv.convert(str(temp_path))
                            try:
                                text_md = rs.document.export_to_markdown()  # type: ignore[attr-defined]
                            except Exception:
                                text_md = getattr(rs, "markdown", "") or getattr(rs, "text", "")
                            logger.info(f"✅ In-process Docling conversion success with kwargs: {kwargs}")
                            if text_md and text_md.strip():
                                break
                        except Exception as _e:
                            logger.warning(f"⚠️ In-process Docling failed with {kwargs}: {_e}")
                            logger.debug(f"Exception details: {type(_e).__name__}: {_e}")
                            continue

            # If Docling returns empty/very short content, try in-process conversion as fallback
            if not text_md or not text_md.strip():
                logger.warning("⚠️ Subprocess conversion failed, trying in-process conversion...")
                try:
                    conv = DocumentConverter()
                    rs = conv.convert(str(temp_path))
                    try:
                        text_md = rs.document.export_to_markdown()  # type: ignore[attr-defined]
                    except Exception:
                        text_md = getattr(rs, "markdown", "") or getattr(rs, "text", "")
                    logger.info("✅ In-process conversion succeeded")
                except Exception as e:
                    logger.error(f"❌ In-process conversion also failed: {e}")
                    raise ValueError("Docling returned empty markdown content")

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
                    method=ProcessingMethod.MARKITDOWN,  # keep enum compatibility if no DOCILING enum
                    status=ProcessingStatus.SUCCESS,
                    processing_time=time.time() - start_time,
                )
                .set_content_stats(total_chunks=len(chunks), total_characters=len(text_md))
                .set_ocr_info(ocr_enabled=self.enable_ocr, ocr_used=ocr_used)
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
                "metadata": metadata.dict(),
                "processing_info": {
                    "processor": "docling",
                    "ocr_used": ocr_used,
                    "chunk_count": len(chunks),
                    "fallback_level": 0,
                },
            }
        except Exception as e:
            logger.error(f"Docling processing failed for {filename}: {e}")
            raise
        finally:
            try:
                temp_path.unlink(missing_ok=True)  # type: ignore[attr-defined]
            except Exception:
                pass
            # Parent-side cleanup hints
            try:
                import torch as _torch
                if getattr(_torch, "cuda", None) and _torch.cuda.is_available():
                    _torch.cuda.empty_cache()
            except Exception:
                pass
            import gc as _gc
            _gc.collect()

    def _chunk_markdown_by_headings(self, markdown_text: str) -> List[str]:
        """
        Split markdown by headings so each section (including its heading) becomes a chunk.
        - Recognizes headings starting with '#' (ATX-style) at any level.
        - Merges consecutive non-heading content into the preceding heading; if the file
          starts without a heading, the initial content becomes its own chunk.
        """
        if not markdown_text:
            return []

        lines = markdown_text.splitlines()
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


