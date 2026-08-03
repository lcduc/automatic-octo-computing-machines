"""
FastAPI dependency providers.

Retrieval and LLM components own multi-hundred-megabyte models and pooled HTTP
connections, so they are built once per process by :class:`ServiceContainer` and
shared across requests. Only the thin, per-request services are constructed on
each call.
"""

# Standard library imports
import logging
import threading
from typing import Optional

# Local imports
from core.ai_services import ChatbotService
from core.retrieval import ContextRetriever
from services import ChatService, DocumentService, UploadService, URLService

logger = logging.getLogger(__name__)


class ServiceContainer:
    """
    Lazily builds and caches the expensive, stateless-per-request collaborators.

    Instances are created on first use inside the running event loop, which
    keeps any loop-bound primitives attached to the loop that will use them.
    """

    def __init__(self):
        self._context_retriever: Optional[ContextRetriever] = None
        self._chatbot_service: Optional[ChatbotService] = None
        # RLock, not Lock: `chatbot_service` acquires this lock and, while
        # still holding it, reads `self.context_retriever` — a plain Lock
        # would deadlock a thread against itself on the very first request.
        self._lock = threading.RLock()

    @property
    def context_retriever(self) -> ContextRetriever:
        """Shared hybrid-search retriever (owns the cross-encoder reranker)."""
        if self._context_retriever is None:
            with self._lock:
                if self._context_retriever is None:
                    logger.info("Initializing shared ContextRetriever")
                    self._context_retriever = ContextRetriever()
        return self._context_retriever

    @property
    def chatbot_service(self) -> ChatbotService:
        """Shared LLM service (owns pooled OpenAI clients and the answer cache)."""
        if self._chatbot_service is None:
            with self._lock:
                if self._chatbot_service is None:
                    logger.info("Initializing shared ChatbotService")
                    self._chatbot_service = ChatbotService(
                        context_retriever=self.context_retriever
                    )
        return self._chatbot_service

    def shutdown(self) -> None:
        """Release resources held by the cached services."""
        if self._chatbot_service is not None:
            self._chatbot_service.cleanup()
            self._chatbot_service = None
        self._context_retriever = None


_container: Optional[ServiceContainer] = None
_container_lock = threading.Lock()


def get_service_container() -> ServiceContainer:
    """Get the process-wide service container."""
    global _container
    if _container is None:
        with _container_lock:
            if _container is None:
                _container = ServiceContainer()
    return _container


def get_document_service() -> DocumentService:
    """Get document service instance for document processing and management."""
    return DocumentService()


def get_chat_service() -> ChatService:
    """
    Get a chat service backed by the shared retrieval and LLM components.

    The ``ChatService`` wrapper itself is cheap and per-request, which keeps its
    conversation buffer scoped to a single caller.
    """
    return ChatService(chatbot_service=get_service_container().chatbot_service)


def get_upload_service() -> UploadService:
    """Get upload service instance for file upload and processing."""
    return UploadService()


def get_url_service() -> URLService:
    """Get URL service instance for web content extraction and processing."""
    return URLService()
