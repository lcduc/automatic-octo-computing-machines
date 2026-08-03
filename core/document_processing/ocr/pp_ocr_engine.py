"""
CPU-first OCR engine backed by PaddleOCR's PP-OCRv6 pipeline.
"""

# Standard library imports
import logging
from typing import Any, Optional

# Local imports
from .base import OCREngine

logger = logging.getLogger(__name__)


class PPOCRv6Engine(OCREngine):
    """
    Lightweight local OCR using PaddleOCR's PP-OCRv6 unified multilingual model.

    PP-OCRv6 covers 50+ languages, including Vietnamese and English, with a
    single model — no per-language switching needed. The underlying
    ``paddleocr.PaddleOCR`` pipeline is loaded lazily on first use and reused
    across calls, since loading it is expensive.
    """

    def __init__(self, device: str = "cpu"):
        """
        Args:
            device: PaddleX device string, e.g. ``"cpu"`` or ``"gpu:0"``.
        """
        self._device = device
        self._pipeline: Optional[Any] = None

    @property
    def name(self) -> str:
        return f"pp_ocrv6[{self._device}]"

    def _get_pipeline(self):
        if self._pipeline is None:
            from paddleocr import PaddleOCR

            logger.info("Loading PP-OCRv6 pipeline on device=%s", self._device)
            self._pipeline = PaddleOCR(
                device=self._device,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        return self._pipeline

    def extract_text(self, image_path: str) -> str:
        try:
            pipeline = self._get_pipeline()
            results = pipeline.predict(image_path)
            lines = []
            for res in results:
                payload = res.json if hasattr(res, "json") else {}
                if isinstance(payload, dict):
                    # PaddleX pipeline results nest fields under "res" in some
                    # versions and expose them at the top level in others.
                    payload = payload.get("res", payload)
                    lines.extend(payload.get("rec_texts") or [])
            return "\n".join(lines)
        except Exception:
            logger.exception("PP-OCRv6 extraction failed for %s", image_path)
            return ""
