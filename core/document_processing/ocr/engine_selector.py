"""
Selects which OCR engine backs document ingestion.

Local engines are auto-selected by GPU availability (PaddleOCR-VL on GPU,
PP-OCRv6 on CPU); the online Datalab engine is used only when explicitly
requested via ``OCR_PROVIDER=datalab``.
"""

# Standard library imports
import logging
import threading
from typing import Optional

# Local imports
from config.settings import Config
from .base import OCREngine
from .datalab_surya_engine import DatalabSuryaEngine
from .paddle_vl_engine import PaddleOCRVLEngine
from .pp_ocr_engine import PPOCRv6Engine

logger = logging.getLogger(__name__)

_local_engine: Optional[OCREngine] = None
_online_engine: Optional[OCREngine] = None
_lock = threading.Lock()


def _gpu_available() -> bool:
    """
    Whether the installed PaddlePaddle build can use a CUDA GPU.

    Checked against paddle's own API rather than torch's — the two libraries
    are installed independently (see Dockerfile), so a CPU-only torch build
    must not suppress GPU OCR when paddlepaddle-gpu is installed, and vice versa.
    """
    try:
        import paddle

        return bool(paddle.device.is_compiled_with_cuda()) and paddle.device.cuda.device_count() > 0
    except Exception:
        return False


def get_local_engine() -> OCREngine:
    """
    Get the process-wide local OCR engine.

    PaddleOCR-VL on GPU when a CUDA device is available, otherwise PP-OCRv6 on
    CPU. Built once and reused — both engines load multi-hundred-MB model
    weights that must not be reloaded per document.
    """
    global _local_engine
    if _local_engine is None:
        with _lock:
            if _local_engine is None:
                if _gpu_available():
                    logger.info("GPU detected: using PaddleOCR-VL for local OCR")
                    _local_engine = PaddleOCRVLEngine(device="gpu:0")
                else:
                    logger.info("No GPU detected: using PP-OCRv6 (CPU) for local OCR")
                    _local_engine = PPOCRv6Engine(device="cpu")
    return _local_engine


def get_online_engine() -> Optional[OCREngine]:
    """Get the Datalab Surya OCR engine, or ``None`` if no API key is configured."""
    global _online_engine
    if _online_engine is None:
        with _lock:
            if _online_engine is None:
                api_key = Config.OCR.DATALAB_API_KEY()
                if not api_key:
                    return None
                _online_engine = DatalabSuryaEngine(api_key=api_key)
    return _online_engine


def get_ocr_engine() -> OCREngine:
    """
    Get the OCR engine to use for this process, honoring ``OCR_PROVIDER``.

    ``auto`` (default) uses the local engine, GPU/CPU auto-detected.
    ``datalab`` forces the online engine, falling back to the local engine
    with a warning if ``DATALAB_API_KEY`` is not set.
    """
    if Config.OCR.OCR_PROVIDER() == "datalab":
        online_engine = get_online_engine()
        if online_engine is not None:
            return online_engine
        logger.warning(
            "OCR_PROVIDER=datalab but DATALAB_API_KEY is not set; falling back to local OCR"
        )
    return get_local_engine()
