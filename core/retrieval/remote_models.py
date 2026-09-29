"""
Embedding service and reranker backed by the model-server, with the same
interface as the in-process :class:`EmbeddingService` and :class:`Reranker`.
"""

# Standard library imports
import logging
from typing import List, Optional

# Third-party imports
import numpy as np

# Local imports
from config.model_server_settings import ModelServerConfig
from config.settings import Config
from core.infrastructure.model_server_client import ModelServerClient, ModelServerError

logger = logging.getLogger(__name__)

#: Passages sent per /embed call.
PASSAGE_BATCH_SIZE = 128


class RemoteEmbeddingService:
    """Query and passage embeddings computed by the model-server (which also applies the query adapter)."""

    def __init__(self, client: ModelServerClient):
        """
        Args:
            client: Model-server client.
        """
        self._client = client

    @property
    def model_name(self) -> str:
        """Configured embedding model; must match the model-server's (checked at start-up)."""
        return Config.LLM.EMBEDDING_MODEL()

    def get_embedder(self) -> None:
        """
        Confirm the model-server serves the configured model (called at start-up).

        Raises:
            ModelServerError: Unreachable, or a different embedding model is loaded.
        """
        served = self._client.ready()["models"]["embedding"]
        if served != self.model_name:
            raise ModelServerError(f"model-server embeds with {served}, but EMBEDDING_MODEL is {self.model_name}")

    def load_query_adapter(self, _path: str) -> bool:
        """The model-server loads and applies the query adapter itself."""
        return False

    def embed_query(self, query: str) -> np.ndarray:
        """1-D L2-normalized float32 vector."""
        return np.asarray(self._client.embed([query], "query")[0], dtype=np.float32)

    def embed_passages(self, texts, batch_size: int = PASSAGE_BATCH_SIZE) -> np.ndarray:
        """``(len(texts), dim)`` L2-normalized float32 matrix."""
        texts = list(texts)
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        vectors: List[List[float]] = []
        for start in range(0, len(texts), batch_size):
            vectors.extend(self._client.embed(texts[start:start + batch_size], "passage"))
        return np.asarray(vectors, dtype=np.float32)


class RemoteReranker:
    """Cross-encoder scores from the model-server."""

    def __init__(self, client: ModelServerClient, available: bool):
        """
        Args:
            client: Model-server client.
            available: Whether the model-server has a reranker loaded.
        """
        self._client = client
        self._available = available

    def available(self) -> bool:
        """True when the model-server has a reranker."""
        return self._available

    def score(self, query: str, texts: List[str]) -> Optional[List[float]]:
        """Scores in [0, 1], or ``None`` so the retriever falls back to its own ranking."""
        if not texts or not self._available:
            return None
        try:
            return self._client.rerank(query, texts)
        except ModelServerError:
            logger.exception("Remote reranking failed; falling back to hybrid scores")
            return None


def embedding_service(client: Optional[ModelServerClient]):
    """The model-server's embedding service when a client is given, else the in-process one."""
    if client is not None:
        return RemoteEmbeddingService(client)
    from core.retrieval.embeddings import get_embedding_service

    return get_embedding_service()


def model_server_client() -> Optional[ModelServerClient]:
    """A client for ``MODEL_SERVER_URL``, or ``None`` when models run in this process."""
    return ModelServerClient.from_config() if ModelServerConfig.MODEL_SERVER_URL() else None
