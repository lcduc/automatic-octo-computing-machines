"""
Embedding service for text vectorization using sentence transformers.
Provides GPU/CPU fallback and the query/passage prompts a model was trained with.
"""

# Standard library imports
import functools
import logging
import threading

# Third-party imports
try:
    import torch
except Exception:
    torch = None
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# Lazy loading to avoid network issues during import
embedder = None
_embedding_service_instance = None
_embedding_service_lock = threading.Lock()

#: Chunks embedded per forward pass during ingestion (fits comfortably in 12GB VRAM).
PASSAGE_BATCH_SIZE = 32
#: Single-query embeddings kept in memory (least recently used evicted), so repeated questions skip the model.
QUERY_CACHE_SIZE = 1000

#: E5 is trained with these prefixes; its model card reports a quality drop without them.
E5_PROMPTS = {"query": "query: ", "document": "passage: "}
#: Prompts of models that need them but do not ship them; any other model uses its own (usually none).
MODEL_PROMPTS = {
    "intfloat/multilingual-e5-small": E5_PROMPTS,
    "intfloat/multilingual-e5-base": E5_PROMPTS,
    "intfloat/multilingual-e5-large": E5_PROMPTS,
}


class EmbeddingService:
    """
    Optimized service for handling text embeddings generation with GPU/CPU fallback.
    Supports multiple embedding models with automatic device selection, caching, and batch processing.
    """

    def __init__(self):
        # Lazy initialization to avoid loading models until needed
        self.embedder = None
        # Request threads share this service: one load at a time, and a cache that
        # stays coherent under concurrent use (functools.lru_cache is thread-safe).
        self._load_lock = threading.Lock()
        self._encode_single_query = functools.lru_cache(maxsize=QUERY_CACHE_SIZE)(self._encode_uncached_query)

    def get_embedder(self):
        """
        Get the embedder instance with automatic GPU/CPU fallback.
        Loads the best available model with device optimization, once per service.
        """
        if self.embedder is None:
            with self._load_lock:
                if self.embedder is None:
                    self.embedder = self._load_embedder()
        return self.embedder

    @staticmethod
    def _load_embedder():
        """Load ``EMBEDDING_MODEL`` on the GPU when there is one, else on the CPU."""
        from config.settings import Config

        gpu_available = bool(torch) and torch.cuda.is_available()
        logger.info("GPU availability for embeddings: %s", gpu_available)

        model_name = Config.LLM.EMBEDDING_MODEL()
        cache_folder = Config.Paths.MODELS_DIR()

        # No fallback model: stored vectors live in EMBEDDING_MODEL's space, and
        # any other model (even one of the same dimension) would return garbage.
        for device in ("cuda", "cpu") if gpu_available else ("cpu",):
            try:
                # fp16 halves the weights on GPU; CPU keeps fp32 (half is slow and lossy there).
                precision = {"model_kwargs": {"dtype": torch.float16}} if device == "cuda" else {}
                model = SentenceTransformer(
                    model_name,
                    device=device,
                    cache_folder=cache_folder,
                    prompts=MODEL_PROMPTS.get(model_name),
                    **precision,
                )
                logger.info("Embedding model '%s' loaded on %s", model_name, device)
                return model
            except Exception:
                logger.exception("Failed to load embedding model '%s' on %s", model_name, device)

        raise RuntimeError(f"Failed to load embedding model '{model_name}'")

    def _encode_query(self, texts, convert_to_numpy=True):
        """
        Encode search queries (with the model's query prompt), caching single texts.

        Args:
            texts: Query string or list of query strings.
            convert_to_numpy: Whether to return numpy arrays (default: True)

        Returns:
            Query embeddings, not normalized.
        """
        # Normalize a bare string to a one-element list so the cache lookup and
        # the encoder below both see the same shape.
        if isinstance(texts, str):
            texts = [texts]
        if len(texts) == 1:
            return self._encode_single_query(texts[0], convert_to_numpy)
        return self.get_embedder().encode_query(texts, convert_to_numpy=convert_to_numpy)

    def _encode_uncached_query(self, text: str, convert_to_numpy: bool):
        """Encode one query; reached through the LRU cache built in ``__init__``."""
        return self.get_embedder().encode_query([text], convert_to_numpy=convert_to_numpy)

    def query_cache_info(self) -> functools._CacheInfo:
        """Hits, misses and size of the single-query embedding cache."""
        return self._encode_single_query.cache_info()

    @property
    def model_name(self) -> str:
        """Configured embedding model; recorded on every stored chunk embedding."""
        from config.settings import Config

        return Config.LLM.EMBEDDING_MODEL()

    def embed_passages(self, texts, batch_size: int = PASSAGE_BATCH_SIZE):
        """
        Embed knowledge chunks for storage.

        Args:
            texts: Chunk texts.
            batch_size: Texts encoded per forward pass.

        Returns:
            ``np.ndarray`` of shape ``(len(texts), dim)``, L2-normalized float32.
        """
        import numpy as np

        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        logger.info("Embedding %d passages", len(texts))
        vectors = self.get_embedder().encode_document(
            list(texts),
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vectors.astype(np.float32)

    def embed_query(self, query: str):
        """
        Embed a search query, applying the optional query adapter.

        Returns:
            1-D L2-normalized float32 vector.
        """
        import numpy as np

        vector = np.asarray(self._encode_query([query], convert_to_numpy=True), dtype=np.float32)
        vector = np.asarray(self.apply_query_adapter(vector), dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm > 0 else vector

    # Query adapter (closed-form) support
    _query_adapter_matrix = None
    _adapter_loaded_path = None
    _adapter_loaded_mtime = None

    def load_query_adapter(self, path: str) -> bool:
        """
        Load a query adapter matrix from disk (NumPy .npy), returning True if loaded.
        """
        try:
            import numpy as np  # local import to avoid import-time overhead
            from pathlib import Path
            import os
            p = Path(path)
            if not p.exists():
                return False
            # Skip reload if unchanged
            mtime = os.path.getmtime(str(p))
            if (
                EmbeddingService._adapter_loaded_path == str(p)
                and EmbeddingService._adapter_loaded_mtime == mtime
                and EmbeddingService._query_adapter_matrix is not None
            ):
                return True
            EmbeddingService._query_adapter_matrix = np.load(str(p))
            EmbeddingService._adapter_loaded_path = str(p)
            EmbeddingService._adapter_loaded_mtime = mtime
            logger.info("Loaded query adapter from %s", path)
            return True
        except Exception:
            logger.exception("Failed to load query adapter from %s", path)
            return False

    def apply_query_adapter(self, query_embedding):
        """
        Apply the query adapter matrix if available. Returns transformed embedding.
        Accepts list/np.ndarray; returns np.ndarray.
        """
        try:
            import numpy as np
            if EmbeddingService._query_adapter_matrix is None:
                return query_embedding if isinstance(query_embedding, np.ndarray) else np.array(query_embedding)
            emb = query_embedding if isinstance(query_embedding, np.ndarray) else np.array(query_embedding)
            # Handle 1D vs 2D shapes; we expect shape (1, d)
            if emb.ndim == 1:
                emb = emb.reshape(1, -1)
            adapter = EmbeddingService._query_adapter_matrix
            if adapter.ndim == 1:
                # Interpret as diagonal scaling vector
                adapter = np.diag(adapter)
            transformed = emb @ adapter
            return transformed
        except Exception:
            # Fail open: return original embedding
            return query_embedding

    @classmethod
    def clear_query_adapter(cls) -> None:
        """
        Drop any loaded query adapter so subsequent queries are untransformed.

        The adapter matrix is process-wide (see the class attributes above),
        so a fresh :class:`ContextRetriever` re-loading from the same
        ``QUERY_ADAPTER_PATH`` would otherwise leave a previously loaded
        adapter in place. Used by the config-comparison eval harness to get a
        clean vector-only baseline in the same process as an adapter-enabled run.
        """
        cls._query_adapter_matrix = None
        cls._adapter_loaded_path = None
        cls._adapter_loaded_mtime = None

    def get_device_info(self):
        """
        Get information about the embedding model device and configuration.
        Useful for debugging and performance monitoring.
        """
        if self.embedder is None:
            return {"status": "Not loaded", "device": "Unknown", "gpu_available": bool(torch) and torch.cuda.is_available()}

        try:
            device = str(self.embedder.device)
            model_name = (
                self.embedder._modules["0"].__class__.__name__
                if hasattr(self.embedder, "_modules")
                else "Unknown"
            )
            return {
                "status": "Loaded",
                "device": device,
                "model": model_name,
                "gpu_available": bool(torch) and torch.cuda.is_available(),
            }
        except Exception:
            logger.exception("Could not read embedder device info")
            return {"status": "Loaded", "device": "Unknown", "model": "Unknown", "gpu_available": bool(torch) and torch.cuda.is_available()}

    def reset_embedder(self):
        """
        Reset the embedder to force reinitialization.
        Useful when GPU becomes available after initial CPU fallback.
        """
        if self.embedder is not None:
            # Clear the embedder to force reinitialization
            self.embedder = None
            logger.info("Embedder reset - will reinitialize on next use")


# Global functions for backward compatibility and convenience
def get_embedding_service():
    """The process-wide embedding service: one model in memory, however many threads ask at once."""
    global _embedding_service_instance
    if _embedding_service_instance is None:
        with _embedding_service_lock:
            if _embedding_service_instance is None:
                _embedding_service_instance = EmbeddingService()
    return _embedding_service_instance

def reset_embedding_service():
    """Reset the global embedding service to force reinitialization."""
    global _embedding_service_instance
    if _embedding_service_instance is not None:
        _embedding_service_instance.reset_embedder()
    else:
        _embedding_service_instance = None


def get_embedder():
    """Get the global embedder instance for legacy code compatibility."""
    service = get_embedding_service()
    return service.get_embedder()


def get_device_info():
    """Get information about the embedding model device for monitoring."""
    service = get_embedding_service()
    return service.get_device_info()
