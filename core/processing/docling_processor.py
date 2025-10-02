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
from config.docling_config import DoclingConfig

logger = logging.getLogger(__name__)


def _docling_convert_worker(args) -> str:
    """Subprocess worker to convert a file path with Docling and return markdown text.
    Args: (path_str, kwargs_dict)
    """
    import os as _os
    import time as _time
    try:
        # Configure PyTorch for GPU usage in subprocess
        import torch as _torch
        if _torch.cuda.is_available():
            _torch.cuda.set_device(0)  # Use first GPU
            # Suppress pin_memory warnings
            _torch.backends.cudnn.benchmark = True
    except Exception:
        pass
    
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
                _torch.cuda.synchronize()  # Ensure all operations complete
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
            # Use configuration from DoclingConfig
            try:
                from config.docling_config import DoclingConfig
                
                # Set environment variables based on config
                os.environ.setdefault("DOCLING_OCR_ENABLED", str(DoclingConfig.DOCLING_OCR_ENABLED()).lower())
                os.environ.setdefault("DOCLING_OCR_LANGS", ",".join(DoclingConfig.DOCLING_OCR_LANGS()))
                os.environ.setdefault("DOCLING_OCR_DPI", str(DoclingConfig.DOCLING_OCR_DPI()))
                os.environ.setdefault("DOCLING_OCR_GPU", str(DoclingConfig.DOCLING_OCR_GPU()).lower())
                os.environ.setdefault("DOCLING_OCR_TIMEOUT_SEC", str(DoclingConfig.DOCLING_OCR_TIMEOUT_SEC()))
                os.environ.setdefault("DOCLING_OCR_SUBPROCESS", str(DoclingConfig.DOCLING_OCR_SUBPROCESS()).lower())
                
                # Configure EasyOCR specifically for Vietnamese with optimizations
                os.environ.setdefault("EASYOCR_LANG", "vi,en")  # Vietnamese first, then English
                os.environ.setdefault("EASYOCR_GPU", str(DoclingConfig.DOCLING_OCR_GPU()).lower())
                os.environ.setdefault("EASYOCR_MODEL_STORAGE_DIR", DoclingConfig.DOCLING_OCR_MODEL_STORAGE())
                
                # Vietnamese-specific EasyOCR optimizations
                os.environ.setdefault("EASYOCR_CONFIDENCE_THRESHOLD", str(DoclingConfig.DOCLING_OCR_CONFIDENCE_THRESHOLD()))
                os.environ.setdefault("EASYOCR_PARAGRAPH", str(DoclingConfig.DOCLING_OCR_PARAGRAPH_MODE()).lower())
                os.environ.setdefault("EASYOCR_BATCH_SIZE", str(DoclingConfig.DOCLING_OCR_BATCH_SIZE()))
                
                # Configure PyTorch for better GPU utilization and reduce warnings
                if DoclingConfig.DOCLING_OCR_GPU():
                    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")  # Use first GPU
                    os.environ.setdefault("TORCH_CUDA_ALLOC_CONF", "max_split_size_mb:512")
                    # Disable pin_memory warning by setting it appropriately
                    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "max_split_size_mb:512")
                
                # Get configuration values
                ocr_enabled = DoclingConfig.DOCLING_OCR_ENABLED()
                ocr_langs = DoclingConfig.DOCLING_OCR_LANGS()
                ocr_dpi = DoclingConfig.DOCLING_OCR_DPI()
                ocr_gpu = DoclingConfig.DOCLING_OCR_GPU()
                
            except Exception as e:
                logger.warning(f"Failed to load OCR config, using defaults: {e}")
                ocr_enabled = True
                ocr_langs = ["vi", "en"]
                ocr_dpi = 300
                ocr_gpu = False

            # Configure Docling DocumentConverter with proper GPU settings
            # Docling handles OCR automatically, but we can configure device settings
            ocr_kwargs_variants: List[Dict[str, Any]] = []
            
            # Try to configure for GPU if available and enabled
            if ocr_gpu:
                try:
                    import torch
                    if torch.cuda.is_available():
                        # Docling automatically uses GPU when available, no device parameter needed
                        # Set CUDA device for the current process
                        torch.cuda.set_device(0)
                        torch.backends.cudnn.benchmark = True
                        
                        # Configure for Vietnamese OCR with specific settings
                        ocr_kwargs_variants.append({
                            "ocr_engine": "easyocr",
                            "ocr_languages": ocr_langs,  # Use configured languages
                            "ocr_dpi": ocr_dpi,
                            "ocr_gpu": True
                        })
                        logger.info(f"Configured Docling for GPU processing with Vietnamese OCR: {ocr_langs}")
                    else:
                        logger.warning("GPU requested but not available, falling back to CPU")
                        ocr_kwargs_variants.append({
                            "ocr_engine": "easyocr",
                            "ocr_languages": ocr_langs,
                            "ocr_dpi": ocr_dpi,
                            "ocr_gpu": False
                        })
                except Exception as e:
                    logger.warning(f"Failed to configure GPU settings: {e}, using defaults")
                    ocr_kwargs_variants.append({
                        "ocr_engine": "easyocr",
                        "ocr_languages": ocr_langs,
                        "ocr_dpi": ocr_dpi
                    })
            else:
                # CPU-only configuration with Vietnamese support
                ocr_kwargs_variants.append({
                    "ocr_engine": "easyocr",
                    "ocr_languages": ocr_langs,
                    "ocr_dpi": ocr_dpi,
                    "ocr_gpu": False
                })
            
            # Fallback to empty kwargs if no variants configured
            if not ocr_kwargs_variants:
                ocr_kwargs_variants = [{}]
                
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
                from config.docling_config import DoclingConfig
                timeout_s = float(DoclingConfig.DOCLING_OCR_TIMEOUT_SEC())
                use_subprocess = DoclingConfig.DOCLING_OCR_SUBPROCESS()
            
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
            

            # Apply Vietnamese text quality enhancement (lightweight post-processing)
            if text_md and DoclingConfig.DOCLING_OCR_PREPROCESSING() != "false":
                text_md = self._enhance_vietnamese_text_quality(text_md)
                logger.info("✅ Applied Vietnamese text quality enhancement")

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

    def _is_content_quality_poor(self, text: str) -> bool:
        """
        Check if the OCR content quality is poor, especially for Vietnamese text.
        Looks for common OCR errors like garbled characters, missing diacritics, etc.
        """
        if not text or len(text.strip()) < 10:
            return True
        
        import re
        
        # Check for specific Vietnamese OCR error patterns
        vietnamese_ocr_errors = [
            r'[a-z][A-Z][a-z]',  # Mixed case within words (e.g., "kiOm", "thkng")
            r'[a-zA-Z]{1,2}[0-9]',  # Letters followed by numbers (e.g., "8.2Bài")
            r'[0-9][a-zA-Z]{1,2}',  # Numbers followed by letters
            r'[a-zA-Z]"[a-zA-Z]',  # Letters with quotes in middle (e.g., "th"c")
            r'[a-zA-Z]w[a-zA-Z]',  # Letters with 'w' in middle (e.g., "nhw")
            r'[a-zA-Z]k[a-zA-Z]',  # Letters with 'k' in middle (e.g., "thk")
            r'[a-zA-Z]u[a-zA-Z]',  # Letters with 'u' in middle (e.g., "Iwu")
            r'[a-zA-Z]í[a-zA-Z]',  # Letters with 'í' in middle (e.g., "tuong íng")
        ]
        
        # Count suspicious patterns
        suspicious_count = 0
        for pattern in vietnamese_ocr_errors:
            matches = len(re.findall(pattern, text))
            suspicious_count += matches
        
        # Check for excessive non-Vietnamese characters
        non_vietnamese_chars = len(re.findall(r'[^\w\s\u00C0-\u1EF9\u0102\u0103\u00C2\u00E2\u00CA\u00EA\u00D4\u00F4\u01A0\u01A1\u01AF\u01B0\u00C1\u00E1\u00C9\u00E9\u00CD\u00ED\u00D3\u00F3\u00DA\u00FA\u00DD\u00FD]', text))
        
        # Calculate quality metrics
        text_length = len(text.replace(' ', '').replace('\n', ''))
        if text_length == 0:
            return True
        
        # If more than 5% of the text has suspicious patterns, consider it poor quality
        if (suspicious_count / text_length) > 0.05:
            return True
        
        # If more than 15% of characters are non-Vietnamese, consider it poor quality
        if (non_vietnamese_chars / text_length) > 0.15:
            return True
        
        # Check for very short words or excessive single characters
        words = text.split()
        if len(words) > 0:
            short_words = sum(1 for word in words if len(word.strip()) <= 2)
            if (short_words / len(words)) > 0.4:  # More than 40% very short words
                return True
        
        # Check for specific Vietnamese OCR error indicators
        error_indicators = ['kiOm', 'nhw', 'thk', 'th"c', 'Iwu', 'í', 'bng', 'tiéng']
        error_count = sum(1 for indicator in error_indicators if indicator in text)
        if error_count > 2:  # More than 2 error indicators
            return True
        
        return False

    def _preprocess_image_for_vietnamese(self, image_bytes: bytes, filename: str = "") -> bytes:
        """
        Memory-efficient preprocessing optimized for Vietnamese scanned documents.
        Uses adaptive processing based on document characteristics and quality mode.
        """
        preprocessing_mode = DoclingConfig.DOCLING_OCR_PREPROCESSING()
        quality_mode = DoclingConfig.DOCLING_OCR_QUALITY_MODE()
        
        # Skip preprocessing if disabled or in fast mode
        if preprocessing_mode == "false" or quality_mode == "fast":
            return image_bytes
            
        try:
            from PIL import Image, ImageEnhance
            import io
            
            # Load image and check size for memory management
            image = Image.open(io.BytesIO(image_bytes))
            width, height = image.size
            image_size_mb = (width * height * 3) / (1024 * 1024)  # Rough RGB size in MB
            
            # Memory limit check
            memory_limit_mb = DoclingConfig.DOCLING_OCR_MEMORY_LIMIT_MB()
            if image_size_mb > memory_limit_mb:
                logger.warning(f"⚠️ Image too large ({image_size_mb:.1f}MB > {memory_limit_mb}MB), skipping preprocessing")
                return image_bytes
            
            # Convert to RGB if necessary
            if image.mode != 'RGB':
                image = image.convert('RGB')
            
            # Auto-detect if preprocessing is needed
            needs_preprocessing = self._should_preprocess_image(image, preprocessing_mode)
            
            if not needs_preprocessing and preprocessing_mode == "auto":
                logger.info("✅ Image quality good, skipping preprocessing to save memory")
                return image_bytes
            
            # Apply minimal, memory-efficient preprocessing
            processed = False
            
            # Lightweight contrast enhancement for Vietnamese diacritics
            contrast_mode = DoclingConfig.DOCLING_OCR_CONTRAST_ENHANCE()
            if contrast_mode == "true" or (contrast_mode == "auto" and self._needs_contrast_enhancement(image)):
                enhancer = ImageEnhance.Contrast(image)
                image = enhancer.enhance(1.1)  # Minimal 10% increase
                processed = True
            
            # Deskewing only if really needed
            deskew_mode = DoclingConfig.DOCLING_OCR_DESKEW()
            if deskew_mode == "true" or (deskew_mode == "auto" and self._needs_deskewing(image)):
                image = self._lightweight_deskew(image)
                processed = True
            
            # Light denoising only if enabled
            if DoclingConfig.DOCLING_OCR_DENOISE():
                from PIL import ImageFilter
                image = image.filter(ImageFilter.SMOOTH_MORE)  # Lighter than MedianFilter
                processed = True
            
            if processed:
                # Convert back to bytes with optimized settings
                output_buffer = io.BytesIO()
                image.save(output_buffer, format='JPEG', optimize=True, quality=85)  # JPEG for smaller size
                logger.info("✅ Applied lightweight Vietnamese preprocessing")
                return output_buffer.getvalue()
            else:
                return image_bytes
            
        except Exception as e:
            logger.warning(f"⚠️ Image preprocessing failed: {e}, using original image")
            return image_bytes

    def _should_preprocess_image(self, image, preprocessing_mode: str) -> bool:
        """
        Determine if image needs preprocessing based on quality analysis.
        """
        if preprocessing_mode == "true":
            return True
        elif preprocessing_mode == "false":
            return False
        elif preprocessing_mode == "auto":
            # Simple quality checks
            try:
                import numpy as np
                
                # Convert to grayscale for analysis
                gray = image.convert('L')
                img_array = np.array(gray)
                
                # Check contrast (low contrast may need enhancement)
                contrast = img_array.std()
                
                # Check if image is very dark or very bright
                mean_brightness = img_array.mean()
                
                # Needs preprocessing if low contrast or poor brightness
                needs_processing = contrast < 50 or mean_brightness < 100 or mean_brightness > 200
                
                return needs_processing
                
            except Exception:
                # If analysis fails, be conservative and preprocess
                return True
        
        return False

    def _needs_contrast_enhancement(self, image) -> bool:
        """
        Check if image needs contrast enhancement for better diacritic recognition.
        """
        try:
            import numpy as np
            gray = image.convert('L')
            img_array = np.array(gray)
            
            # Low contrast images benefit from enhancement
            contrast = img_array.std()
            return contrast < 60
            
        except Exception:
            return True  # Conservative approach

    def _needs_deskewing(self, image) -> bool:
        """
        Quick check if image appears skewed and needs deskewing.
        """
        try:
            # Simple heuristic: if image dimensions suggest scanning issues
            width, height = image.size
            aspect_ratio = width / height
            
            # Most documents have reasonable aspect ratios
            # Extreme ratios might indicate skewing
            return aspect_ratio < 0.5 or aspect_ratio > 3.0
            
        except Exception:
            return False  # Skip if analysis fails

    def _lightweight_deskew(self, image):
        """
        Lightweight deskewing using simple rotation detection.
        Much more memory-efficient than full Hough transform.
        """
        try:
            from PIL import Image
            import numpy as np
            
            # Convert to grayscale for analysis
            gray = image.convert('L')
            img_array = np.array(gray)
            
            # Simple edge-based skew detection
            # Look for dominant horizontal lines
            height, width = img_array.shape
            
            # Sample a few horizontal strips
            strips = []
            for y in range(height // 4, 3 * height // 4, height // 8):
                if y < height:
                    strips.append(img_array[y, :])
            
            if strips:
                # Find the most common edge pattern
                # This is a simplified approach that's much lighter than Hough transform
                angles = []
                for strip in strips:
                    # Simple gradient analysis
                    gradient = np.gradient(strip.astype(float))
                    if len(gradient) > 10:
                        # Estimate skew from gradient pattern
                        # This is a heuristic approach
                        peak_indices = np.where(np.abs(gradient) > np.std(gradient))[0]
                        if len(peak_indices) > 2:
                            # Estimate angle from peak distribution
                            angle_estimate = (peak_indices[-1] - peak_indices[0]) / width * 2  # Simplified
                            if -5 < angle_estimate < 5:  # Reasonable range
                                angles.append(angle_estimate)
                
                if angles:
                    avg_angle = np.mean(angles)
                    if abs(avg_angle) > 0.5:  # Only rotate if significant
                        return image.rotate(-avg_angle, expand=True, fillcolor='white')
            
            return image
            
        except Exception as e:
            logger.warning(f"⚠️ Lightweight deskewing failed: {e}, using original image")
            return image

    def _enhance_vietnamese_text_quality(self, text: str) -> str:
        """
        Post-process Vietnamese text to fix common OCR errors and improve quality.
        """
        if not text or not text.strip():
            return text
            
        try:
            # Common Vietnamese OCR corrections
            corrections = {
                # Common diacritic confusions
                'à': ['a`', 'a\\', 'à'],
                'á': ['a\'', 'a/', 'á'],
                'ả': ['a?', 'a~', 'ả'],
                'ã': ['a~', 'ã'],
                'ạ': ['a.', 'ạ'],
                'ă': ['ă', 'a^'],
                'ằ': ['ă`', 'ằ'],
                'ắ': ['ă\'', 'ắ'],
                'ẳ': ['ă?', 'ẳ'],
                'ẵ': ['ă~', 'ẵ'],
                'ặ': ['ă.', 'ặ'],
                'â': ['a^', 'â'],
                'ầ': ['â`', 'ầ'],
                'ấ': ['â\'', 'ấ'],
                'ẩ': ['â?', 'ẩ'],
                'ẫ': ['â~', 'ẫ'],
                'ậ': ['â.', 'ậ'],
                # Add more common corrections as needed
                'đ': ['d-', 'đ', 'ð'],
                'Đ': ['D-', 'Đ', 'Ð'],
            }
            
            # Apply corrections
            corrected_text = text
            for correct, variants in corrections.items():
                for variant in variants:
                    if variant != correct:
                        corrected_text = corrected_text.replace(variant, correct)
            
            # Remove excessive whitespace while preserving Vietnamese text structure
            import re
            corrected_text = re.sub(r'\s+', ' ', corrected_text)
            corrected_text = corrected_text.strip()
            
            return corrected_text
            
        except Exception as e:
            logger.warning(f"⚠️ Vietnamese text enhancement failed: {e}")
            return text

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


