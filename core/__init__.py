"""
Core functionality package for the RAG chatbot system.
Provides the main components for document processing, AI conversation, and knowledge management.
"""

# Import main components for easy access and simplified imports
from .llm import ChatbotService, PromptManager
from .processing import MainDocumentProcessor
from .rag import EmbeddingService, ContextRetriever
from .storage import VectorStore, DocumentStore

# Export all main components for convenient access
__all__ = [
    "ChatbotService",  # RAG-powered conversation engine
    "PromptManager",  # System prompt management
    "MainDocumentProcessor",  # Document processing pipeline
    "EmbeddingService",  # Text embedding generation
    "ContextRetriever",  # Document retrieval system
    "VectorStore",  # Vector storage management
    "DocumentStore",  # Document metadata storage
]
