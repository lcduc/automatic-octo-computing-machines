"""
GPU-first OCR engine backed by PaddleOCR-VL, a vision-language model for
full-page document parsing.
"""

# Standard library imports
import logging
from typing import Any, Optional

# Local imports
from .base import OCREngine

logger = logging.getLogger(__name__)


class PaddleOCRVLEngine(OCREngine):
    """
    GPU-accelerated document parsing using PaddleOCR-VL.

    PaddleOCR-VL is a ~0.9B-parameter VLM that reads layout, text and tables
    in one pass and returns markdown; only the text is used here since the
    rest of the ingestion pipeline consumes plain chunks. Meant for GPU use —
    a 0.9B VLM is impractically slow on CPU compared to PP-OCRv6, so the
    engine selector only picks this when a CUDA GPU is available.
    """

    def __init__(self, device: str = "gpu:0"):
        """
        Args:
            device: PaddleX device string, e.g. ``"gpu:0"``.
        """
        self._device = device
        self._pipeline: Optional[Any] = None

    @property
    def name(self) -> str:
        return f"paddleocr_vl[{self._device}]"

    def _get_pipeline(self):
        if self._pipeline is None:
            from paddleocr import PaddleOCRVL

            logger.info("Loading PaddleOCR-VL pipeline on device=%s", self._device)
            self._pipeline = PaddleOCRVL(device=self._device)
        return self._pipeline

    def extract_text(self, image_path: str) -> str:
        try:
            pipeline = self._get_pipeline()
            results = pipeline.predict(image_path)
            texts = []
            for res in results:
                markdown = getattr(res, "markdown", None) or {}
                text = markdown.get("markdown_texts") if isinstance(markdown, dict) else None
                if text:
                    texts.append(text)
            return "\n\n".join(texts)
        except Exception:
            logger.exception("PaddleOCR-VL extraction failed for %s", image_path)
            return ""
