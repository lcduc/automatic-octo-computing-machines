"""
Client of the model-server, used by api and ingestion-worker when ``MODEL_SERVER_URL`` is set.

Blocking (httpx sync client, one connection pool shared by every thread):
its callers already run model calls in worker threads.
"""

# Standard library imports
import logging
from typing import Any, Dict, List, Optional

# Third-party imports
import httpx

# Local imports
from config.model_server_settings import ModelServerConfig

logger = logging.getLogger(__name__)


class ModelServerError(RuntimeError):
    """The model-server refused a call or could not be reached."""


class ModelServerClient:
    """Calls ``/embed``, ``/rerank``, ``/ocr`` and ``/ready`` with the service token."""

    def __init__(self, base_url: str, token: str, chat_timeout: float, ingestion_timeout: float,
                 transport: Optional[httpx.BaseTransport] = None):
        """
        Args:
            base_url: e.g. ``http://model-server:8600``.
            token: ``MODEL_SERVER_TOKEN``.
            chat_timeout: Seconds allowed for chat-path calls.
            ingestion_timeout: Seconds allowed for OCR and passage embedding.
            transport: Replaces the network (tests).
        """
        self._chat_timeout = chat_timeout
        self._ingestion_timeout = ingestion_timeout
        self._client = httpx.Client(base_url=base_url, headers={"X-Service-Token": token}, transport=transport)

    @classmethod
    def from_config(cls) -> "ModelServerClient":
        """The client described by the ``MODEL_SERVER_*`` settings."""
        return cls(
            ModelServerConfig.MODEL_SERVER_URL(), ModelServerConfig.MODEL_SERVER_TOKEN(),
            ModelServerConfig.MODEL_SERVER_TIMEOUT_SECONDS(), ModelServerConfig.MODEL_SERVER_INGESTION_TIMEOUT_SECONDS(),
        )

    def _call(self, method: str, path: str, timeout: float, **kwargs: Any) -> Dict[str, Any]:
        """
        Raises:
            ModelServerError: Network failure or a non-2xx answer.
        """
        try:
            response = self._client.request(method, path, timeout=timeout, **kwargs)
        except httpx.HTTPError as exc:
            logger.exception("Model-server %s failed", path)
            raise ModelServerError(f"model-server unreachable: {type(exc).__name__}") from exc
        if response.status_code >= 300:
            raise ModelServerError(f"model-server {path} answered HTTP {response.status_code}: {response.text[:200]}")
        return response.json()

    def embed(self, texts: List[str], kind: str) -> List[List[float]]:
        """Embed ``query`` or ``passage`` texts."""
        timeout = self._chat_timeout if kind == "query" else self._ingestion_timeout
        return self._call("POST", "/embed", timeout, json={"texts": texts, "kind": kind})["vectors"]

    def rerank(self, query: str, texts: List[str]) -> Optional[List[float]]:
        """Cross-encoder scores, or ``None`` when the server has no reranker."""
        return self._call("POST", "/rerank", self._chat_timeout, json={"query": query, "texts": texts})["scores"]

    def ocr(self, image: bytes) -> Dict[str, str]:
        """``{"engine", "text"}`` for one page image."""
        return self._call("POST", "/ocr", self._ingestion_timeout, content=image,
                          headers={"Content-Type": "application/octet-stream"})

    def ready(self) -> Dict[str, Any]:
        """Loaded models, free VRAM and load."""
        return self._call("GET", "/ready", self._chat_timeout)

    def close(self) -> None:
        """Release the connection pool."""
        self._client.close()
