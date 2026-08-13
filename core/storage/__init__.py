"""
Storage Domain
Handles vector storage, document metadata, and data persistence.
"""

from .vector_store import VectorStore
from .vector_store_optimized import OptimizedVectorStore
from .provider import VectorStoreProvider, get_vector_store_provider
from .document_store import DocumentStore
from .metadata_store import MetadataStore

__all__ = [
    "VectorStore",
    "OptimizedVectorStore",
    "VectorStoreProvider",
    "get_vector_store_provider",
    "DocumentStore",
    "MetadataStore",
]
