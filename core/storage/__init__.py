"""
Storage package for vector and document storage management.
Provides persistent storage for embeddings, documents, and metadata.
"""

# Import storage components for different data types
from .vector_store import VectorStore, FaissVectorStore
from .document_store import DocumentStore
from .metadata_store import MetadataStore
import os

# Create global singleton instances to avoid repeated initialization
backend = os.getenv("VECTOR_STORE_BACKEND", "file").lower()
if backend == "faiss":
    vector_store = FaissVectorStore()
else:
    vector_store = VectorStore()
document_store = DocumentStore()
metadata_store = MetadataStore()

# Export all storage components and global instances
__all__ = [
    "VectorStore",  # Vector embedding storage
    "DocumentStore",  # Document content storage
    "MetadataStore",  # Document metadata storage
    "vector_store",  # Global vector store instance
    "document_store",  # Global document store instance
    "metadata_store",  # Global metadata store instance
]
