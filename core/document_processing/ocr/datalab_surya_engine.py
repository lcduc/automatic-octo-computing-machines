"""
Online OCR engine calling Datalab's hosted Surya OCR API.
"""

# Standard library imports
import logging
import time
from typing import Any, Dict, List, Optional

# Third-party imports
import httpx

# Local imports
from .base import OCREngine

logger = logging.getLogger(__name__)

#: Datalab's OCR endpoints. NOTE: as of this writing Datalab's docs mark
#: `/api/v1/ocr` deprecated ("will be removed in a future version"), but it is
#: the only endpoint that documents itself as Surya OCR specifically — the
#: newer /convert, /extract, /segment endpoints don't disclose which model
#: they use. Revisit this if Datalab removes the endpoint; see
#: docs/PRODUCTION_READINESS_REVIEW.md.
_BASE_URL = "https://www.datalab.to"
_SUBMIT_PATH = "/api/v1/ocr"
_POLL_PATH_TEMPLATE = "/api/v1/ocr/{request_id}"


class DatalabSuryaEngine(OCREngine):
    """Submits a page image to Datalab's Surya OCR API and polls for the result."""

    def __init__(
        self,
        api_key: str,
        poll_interval_seconds: float = 2.0,
        timeout_seconds: float = 120.0,
    ):
        """
        Args:
            api_key: Datalab API key, sent as the ``X-API-Key`` header.
            poll_interval_seconds: Delay between result-check polls.
            timeout_seconds: Give up waiting for a result after this long.
        """
        self._api_key = api_key
        self._poll_interval = poll_interval_seconds
        self._timeout = timeout_seconds

    @property
    def name(self) -> str:
        return "datalab_surya"

    def extract_text(self, image_path: str) -> str:
        headers = {"X-API-Key": self._api_key}
        try:
            with httpx.Client(base_url=_BASE_URL, timeout=30.0) as client:
                request_id = self._submit(client, headers, image_path)
                if request_id is None:
                    return ""
                return self._poll_for_text(client, headers, request_id)
        except Exception:
            logger.exception("Datalab Surya OCR request failed for %s", image_path)
            return ""

    def _submit(self, client: httpx.Client, headers: Dict[str, str], image_path: str) -> Optional[str]:
        """Upload the page image and return the request id, or None on failure."""
        with open(image_path, "rb") as f:
            response = client.post(_SUBMIT_PATH, headers=headers, files={"file": f})
        response.raise_for_status()
        submission = response.json()
        if not submission.get("success", True):
            logger.warning("Datalab OCR submission failed: %s", submission.get("error"))
            return None
        return submission["request_id"]

    def _poll_for_text(self, client: httpx.Client, headers: Dict[str, str], request_id: str) -> str:
        """Poll until the OCR job completes, then return its extracted text."""
        poll_path = _POLL_PATH_TEMPLATE.format(request_id=request_id)
        deadline = time.monotonic() + self._timeout

        while time.monotonic() < deadline:
            time.sleep(self._poll_interval)
            response = client.get(poll_path, headers=headers)
            response.raise_for_status()
            result = response.json()

            if result.get("status") != "complete":
                continue
            if not result.get("success", True):
                logger.warning("Datalab OCR failed: %s", result.get("error"))
                return ""
            return self._text_from_pages(result.get("pages") or [])

        logger.warning("Datalab OCR timed out waiting for request %s", request_id)
        return ""

    @staticmethod
    def _text_from_pages(pages: List[Dict[str, Any]]) -> str:
        """Flatten Surya's per-page text-line results into plain text."""
        lines = []
        for page in pages:
            for text_line in page.get("text_lines") or []:
                text = text_line.get("text")
                if text:
                    lines.append(text)
        return "\n".join(lines)
