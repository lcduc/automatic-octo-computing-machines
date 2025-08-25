"""
RAG (Retrieval-Augmented Generation) package for context retrieval and similarity calculations.
Provides document embedding, semantic search, and context retrieval capabilities.
"""

# Import RAG components for document processing and search
from .embeddings import EmbeddingService
from .retriever import ContextRetriever
from .similarity import SimilarityCalculator

# Export all components and utilities for convenient access
__all__ = [
    "EmbeddingService",  # Text embedding generation
    "ContextRetriever",  # Document retrieval system
    "SimilarityCalculator",  # Similarity computation
]
