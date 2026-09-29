"""
OCR engine that sends each rendered page to the model-server (which holds the GPU OCR model).
"""

# Standard library imports
import logging

# Local imports
from core.infrastructure.model_server_client import ModelServerClient, ModelServerError
from .ocr_base import OCREngine

logger = logging.getLogger(__name__)


class RemoteOCREngine(OCREngine):
    """Page OCR on the model-server's resident engine (one page at a time, behind chat traffic)."""

    def __init__(self, client: ModelServerClient):
        """
        Args:
            client: Model-server client.
        """
        self._client = client
        self._engine_name = "model-server"

    @property
    def name(self) -> str:
        """``model-server:<engine>`` once a page was recognised."""
        return self._engine_name

    def extract_text(self, image_path: str) -> str:
        """Recognise one page; an unreachable server yields no text (logged), like the local engines."""
        with open(image_path, "rb") as handle:
            image = handle.read()
        try:
            result = self._client.ocr(image)
        except ModelServerError:
            logger.exception("Remote OCR failed for %s", image_path)
            return ""
        self._engine_name = f"model-server:{result['engine']}"
        return result["text"]
