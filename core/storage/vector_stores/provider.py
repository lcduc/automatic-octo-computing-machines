"""
Process-wide provider for the active vector store.

Every consumer (retrieval, chat, ingestion, warm-up) must go through this
provider instead of instantiating its own ``OptimizedVectorStore``. Sharing a
single instance guarantees that:

* the HDF5/FAISS payload is read from disk once per process, not per request;
* the FAISS index is actually populated when retrieval asks for it;
* a rebuild triggered by ingestion is immediately visible to the chat path.
"""

# Standard library imports
import logging
import threading
from typing import Any, List, Optional, Tuple

# Third-party imports
import numpy as np

# Local imports
from .vector_store_optimized import OptimizedVectorStore

logger = logging.getLogger(__name__)

VectorStoreData = Tuple[Optional[Any], np.ndarray, List[str]]


class VectorStoreProvider:
    """
    Owns the single ``OptimizedVectorStore`` instance used by the application.

    The loaded ``(index, embeddings, documents)`` tuple is cached until
    :meth:`invalidate` is called, which ingestion does after every rebuild.
    """

    def __init__(self, store: Optional[OptimizedVectorStore] = None):
        """
        Args:
            store: Optional pre-built store, mainly for tests. When omitted a
                default ``OptimizedVectorStore`` is created lazily on first use.
        """
        self._store = store
        self._data: Optional[VectorStoreData] = None
        self._lock = threading.RLock()

    @property
    def is_loaded(self) -> bool:
        """True when the vector store payload is cached in memory."""
        return self._data is not None

    def get_store(self) -> OptimizedVectorStore:
        """Return the shared vector store instance, creating it if needed."""
        with self._lock:
            if self._store is None:
                self._store = OptimizedVectorStore()
            return self._store

    def get_data(self, force_reload: bool = False) -> Optional[VectorStoreData]:
        """
        Return the cached ``(index, embeddings, documents)`` tuple.

        Args:
            force_reload: Re-read from disk even when a cached payload exists.

        Returns:
            The loaded tuple, or ``None`` when loading failed.
        """
        with self._lock:
            if self._data is not None and not force_reload:
                return self._data
            try:
                self._data = self.get_store().load_vector_store()
                document_count = len(self._data[2]) if self._data[2] else 0
                logger.info("Vector store loaded into provider: %d documents", document_count)
                return self._data
            except Exception:
                logger.exception("Failed to load vector store")
                self._data = None
                return None

    def invalidate(self) -> None:
        """
        Drop the cached payload so the next read reflects on-disk changes.

        Called after ingestion rebuilds the store; the shared instance itself is
        kept so its FAISS index and metadata stay wired to the same object.
        """
        with self._lock:
            self._data = None
            logger.info("Vector store cache invalidated")

    def refresh(self) -> Optional[VectorStoreData]:
        """Invalidate and immediately reload, returning the fresh payload."""
        self.invalidate()
        return self.get_data()


_provider: Optional[VectorStoreProvider] = None
_provider_lock = threading.Lock()


def get_vector_store_provider() -> VectorStoreProvider:
    """Get the process-wide vector store provider."""
    global _provider
    if _provider is None:
        with _provider_lock:
            if _provider is None:
                _provider = VectorStoreProvider()
    return _provider
