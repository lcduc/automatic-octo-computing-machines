# Standard library imports
import logging
import time
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

# Third-party imports
import numpy as np

# Local imports
from config.settings import Config
from core.agent import ChatbotService
from core.infrastructure.cache_service import get_cache_service
from core.retrieval.context_builder import ContextAssembler
from core.storage import get_vector_store_provider
from utils.monitor import get_performance_monitor

logger = logging.getLogger(__name__)


class ChatService:
    """
    Enhanced chat service with RAG integration, performance monitoring, and robust error handling.
    Provides comprehensive chat functionality with knowledge base integration and service health tracking.
    """

    def __init__(self, chatbot_service=None, vector_store_provider=None):
        """
        Initialize chat service with core components and monitoring infrastructure.

        Args:
            chatbot_service: LLM-facing service; created on demand when omitted.
            vector_store_provider: Shared knowledge-base provider; defaults to
                the process-wide provider so ingestion updates are visible here.
        """
        # Initialize core components and monitoring
        if chatbot_service is None:
            self.chatbot_service = ChatbotService()
        else:
            self.chatbot_service = chatbot_service
        self.service_metrics = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "average_response_time": 0.0,
            "service_start_time": datetime.now().isoformat(),
        }

        # Shared knowledge base — invalidated by ingestion, not time-based
        self._vector_store_provider = vector_store_provider or get_vector_store_provider()
        self._context_assembler = ContextAssembler()

        # Use existing smart cache service
        self._smart_cache = get_cache_service()

        # Performance monitoring
        self._performance_monitor = get_performance_monitor()

    def _get_cached_vector_store(self):
        """
        Get the shared knowledge-base payload.

        Returns:
            The ``(index, embeddings, documents)`` tuple, or ``None`` if the
            store could not be loaded.
        """
        return self._vector_store_provider.get_data()

    def _update_average_response_time(self, response_time: float):
        """Update rolling average response time."""
        current_avg = self.service_metrics["average_response_time"]
        successful_requests = self.service_metrics["successful_requests"]

        if successful_requests == 1:
            self.service_metrics["average_response_time"] = response_time
        else:
            self.service_metrics["average_response_time"] = (
                current_avg * (successful_requests - 1) + response_time
            ) / successful_requests

    def get_knowledge_base_status(self) -> Dict[str, Any]:
        """
        Get comprehensive knowledge base status with OCR-level detail.

        Returns:
            Dict containing detailed knowledge base information
        """
        try:
            logger.debug("Checking knowledge base status...")
            vector_store_result = self._get_cached_vector_store()
            if vector_store_result is None:
                raise RuntimeError("Vector store could not be loaded")
            _, current_embeddings, current_documents = vector_store_result
            store = self._vector_store_provider.get_store()

            # Calculate additional metrics
            embedding_dimensions = 0
            if current_embeddings is not None and len(current_embeddings) > 0:
                embedding_dimensions = (
                    current_embeddings.shape[1]
                    if hasattr(current_embeddings, "shape")
                    else 0
                )

            status_info = {
                "available": bool(current_documents),
                "document_count": len(current_documents) if current_documents else 0,
                "embedding_count": (
                    len(current_embeddings) if current_embeddings is not None else 0
                ),
                "embedding_dimensions": embedding_dimensions,
                "status": "ready" if current_documents else "empty",
                "last_updated": datetime.now().isoformat(),
                "vector_store_path": getattr(store, "h5_path", None),
                "health": "healthy" if current_documents else "no_data",
            }

            logger.debug(
                f" Knowledge base status: {status_info['status']} ({status_info['document_count']} docs)"
            )
            return status_info

        except Exception as e:
            logger.exception("Error getting knowledge base status")
            return {
                "available": False,
                "document_count": 0,
                "embedding_count": 0,
                "embedding_dimensions": 0,
                "status": "error",
                "health": "unhealthy",
                "last_updated": datetime.now().isoformat(),
                "error": str(e),
            }

    def get_comprehensive_service_status(self) -> Dict[str, Any]:
        """
        Get comprehensive service status like OCR's service monitoring.

        Returns:
            Dict containing detailed service health and performance metrics
        """
        try:
            # Get knowledge base status
            kb_status = self.get_knowledge_base_status()

            # Get chatbot service status
            chatbot_status = self.chatbot_service.get_service_status()

            # Calculate success rate
            total_requests = self.service_metrics["total_requests"]
            success_rate = 0.0
            if total_requests > 0:
                success_rate = (
                    self.service_metrics["successful_requests"] / total_requests
                ) * 100

            # Determine overall health
            overall_health = "healthy"
            if not chatbot_status["service_available"]:
                overall_health = "unhealthy"
            elif not kb_status["available"]:
                overall_health = "no_data"
            elif (
                success_rate < Config.Health.SERVICE_SUCCESS_RATE_THRESHOLD()
                and total_requests > Config.Health.SERVICE_MIN_REQUESTS_FOR_HEALTH()
            ):
                overall_health = "degraded"

            return {
                "service_name": "ChatService",
                "overall_health": overall_health,
                "service_available": chatbot_status["service_available"],
                "knowledge_base": kb_status,
                "chatbot_service": chatbot_status,
                "service_metrics": {
                    **self.service_metrics,
                    "success_rate_percent": round(success_rate, 2),
                    "failure_rate_percent": round(100 - success_rate, 2),
                },
                "timestamp": datetime.now().isoformat(),
                "uptime_info": {
                    "service_start_time": self.service_metrics["service_start_time"],
                    "current_time": datetime.now().isoformat(),
                },
            }

        except Exception as e:
            logger.error(f" Error getting comprehensive service status: {e}")
            return {
                "service_name": "ChatService",
                "overall_health": "error",
                "service_available": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }

    def reset_metrics(self):
        """Reset service metrics for monitoring purposes."""
        logger.info("Resetting ChatService metrics")
        self.service_metrics = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "average_response_time": 0.0,
            "service_start_time": datetime.now().isoformat(),
        }

    def clear_cache(self) -> Dict[str, Any]:
        """Clear all caches including smart cache and local caches."""
        try:
            # Clear chatbot service cache
            chatbot_result = self.chatbot_service.clear_cache()

            # Clear smart cache
            self._smart_cache.clear()
            smart_cache_stats = self._smart_cache.get_stats()

            # Drop the shared knowledge-base payload so it reloads on next use
            self._vector_store_provider.invalidate()

            logger.info("🧹 All caches cleared successfully")
            return {
                "message": "All caches cleared successfully",
                "chatbot_cache": chatbot_result,
                "smart_cache_cleared": True,
                "smart_cache_stats": smart_cache_stats,
                "vector_store_cache_cleared": True,
                "timestamp": time.time()
            }
        except Exception as e:
            logger.error("Failed to clear cache: %s", e)
            return {
                "message": "Failed to clear cache",
                "error": str(e),
                "timestamp": time.time()
            }

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get comprehensive cache statistics from all cache layers."""
        try:
            # Get smart cache stats
            smart_cache_stats = self._smart_cache.get_stats()

            # Get chatbot cache stats
            chatbot_status = self.chatbot_service.get_service_status()

            return {
                "smart_cache": smart_cache_stats,
                "chatbot_cache": {
                    "size": chatbot_status.get("cache_size", 0),
                    "model": chatbot_status.get("model", "unknown"),
                    "available": chatbot_status.get("service_available", False)
                },
                "vector_store_cache": {
                    "cached": self._vector_store_provider.is_loaded,
                },
                "performance_metrics": self._performance_monitor.get_performance_stats(),
                "timestamp": time.time()
            }
        except Exception as e:
            logger.error("Failed to get cache stats: %s", e)
            return {
                "error": str(e),
                "timestamp": time.time()
            }

    def _load_knowledge_base(self) -> Optional[tuple]:
        """
        Fetch and normalize the current knowledge base.

        Returns:
            An ``(embeddings, documents)`` pair (both empty when the corpus is
            empty), or ``None`` if the vector store could not be loaded at all.
        """
        vector_store_result = self._get_cached_vector_store()
        if vector_store_result is None:
            return None

        _, embeddings, documents = vector_store_result
        if not documents:
            return np.array([]), []
        if embeddings is None:
            embeddings = np.array([])
        elif isinstance(embeddings, list):
            embeddings = np.array(embeddings)
        return embeddings, documents

    async def stream_chat_with_memory(
        self, query: str, custom_history: Optional[List[Dict[str, str]]] = None
    ) -> AsyncGenerator[str, None]:
        """
        Stream a chat response, replaying caller-supplied conversation history.

        There is no server-side session store: the caller sends its own
        history each turn (see ``ChatRequest.history``) and this method only
        applies a hard server-side cap (``MAX_HISTORY_TURNS``) so a
        misbehaving client cannot blow the prompt's token budget.

        Args:
            query: User query.
            custom_history: Prior turns as ``{"role", "content"}`` dicts, most
                recent last. ``None`` means no history is used for this turn.

        Yields:
            Answer text deltas, or a single ``[ERROR] ...`` token on failure.
        """
        start_time = time.time()
        self.service_metrics["total_requests"] += 1

        if not query or not query.strip():
            yield "[ERROR] Empty query provided."
            return
        if not self.chatbot_service.api_available:
            yield "[ERROR] Chat service is currently unavailable."
            return

        kb = self._load_knowledge_base()
        if kb is None:
            yield "[ERROR] Knowledge base unavailable"
            return
        current_embeddings, current_documents = kb

        max_messages = Config.Chat.MAX_HISTORY_TURNS() * 2
        history = (custom_history or [])[-max_messages:] if max_messages > 0 else []

        try:
            async for token in self.chatbot_service.stream_response_with_history(
                query,
                embeddings=current_embeddings,
                documents=current_documents,
                history=history,
            ):
                yield token
        except Exception:
            logger.exception("Streaming chat failed for query: %s...", query[:50])
            self.service_metrics["failed_requests"] += 1
            yield "[ERROR] An unexpected error occurred while generating the response."
            return

        self.service_metrics["successful_requests"] += 1
        processing_time = time.time() - start_time
        self._update_average_response_time(processing_time)
        self._performance_monitor.record_request(processing_time, cache_hit=False)

    async def batch_chat(self, queries: List[str]) -> List[Dict[str, Any]]:
        """
        Answer several independent queries concurrently, no shared history.

        Each query gets its own retrieval + generation + cache lookup; a
        failure in one query does not affect the others.

        Args:
            queries: Questions to answer.

        Returns:
            One result dict per input query, in the original order — see
            :class:`models.responses.BatchChatResult` for the shape.
        """
        self.service_metrics["total_requests"] += len(queries)

        if not self.chatbot_service.api_available:
            self.service_metrics["failed_requests"] += len(queries)
            return [
                {"query": q, "response": None, "success": False, "cached": False,
                 "confidence": None, "error": "Chat service is currently unavailable"}
                for q in queries
            ]

        kb = self._load_knowledge_base()
        if kb is None:
            self.service_metrics["failed_requests"] += len(queries)
            return [
                {"query": q, "response": None, "success": False, "cached": False,
                 "confidence": None, "error": "Knowledge base unavailable"}
                for q in queries
            ]
        embeddings, documents = kb

        start_time = time.time()
        results = await self.chatbot_service.async_get_batch_responses(queries, embeddings, documents)
        processing_time = time.time() - start_time

        successful = sum(1 for r in results if r.get("success"))
        self.service_metrics["successful_requests"] += successful
        self.service_metrics["failed_requests"] += len(queries) - successful
        if successful:
            self._update_average_response_time(processing_time / len(queries))
        return results

    async def transcribe_audio(
        self, audio_bytes: bytes, filename: str, content_type: str = "audio/wav"
    ) -> str:
        """
        Transcribe a recorded/uploaded voice query to text.

        Args:
            audio_bytes: Raw audio file content.
            filename: Original filename; its extension hints the audio
                format to the transcription API.
            content_type: MIME type reported by the client.

        Returns:
            The transcribed text.

        Raises:
            RuntimeError: The chat service is currently unavailable.
            Exception: Propagated from the transcription API on failure.
        """
        if not self.chatbot_service.api_available:
            raise RuntimeError("Chat service is currently unavailable")
        return await self.chatbot_service.transcribe_audio(audio_bytes, filename, content_type)
