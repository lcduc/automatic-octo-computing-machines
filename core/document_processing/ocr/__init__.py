"""
OCR engines for scanned/image-only documents.

Three interchangeable engines: PP-OCRv6 (local, CPU), PaddleOCR-VL (local,
GPU) and Datalab's hosted Surya OCR (online). :func:`get_ocr_engine` selects
between them per ``OCR_PROVIDER`` / GPU availability.
"""

from .base import OCREngine
from .datalab_surya_engine import DatalabSuryaEngine
from .engine_selector import get_local_engine, get_ocr_engine, get_online_engine
from .paddle_vl_engine import PaddleOCRVLEngine
from .pp_ocr_engine import PPOCRv6Engine

__all__ = [
    "OCREngine",
    "PPOCRv6Engine",
    "PaddleOCRVLEngine",
    "DatalabSuryaEngine",
    "get_ocr_engine",
    "get_local_engine",
    "get_online_engine",
]
