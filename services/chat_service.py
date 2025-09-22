# Standard library imports
import logging
from typing import Dict, Any, Optional, List, AsyncGenerator
import time
from datetime import datetime
import numpy as np
import asyncio

# Local imports
from core.llm import ChatbotService
from core.storage import vector_store
from config.server.health_config import HealthConfig
from config.llm.llm_config import LLMConfig
from models.responses import ErrorResponse, BaseResponse, StatusEnum

logger = logging.getLogger(__name__)


class ChatService:
    """
    Enhanced chat service with RAG integration, performance monitoring, and robust error handling.
    Provides comprehensive chat functionality with knowledge base integration and service health tracking.
    """

    def __init__(self, chatbot_service=None):
        """
        Initialize chat service with core components and monitoring infrastructure.
        Sets up chatbot service, request tracking, and performance metrics.
        """
        # Initialize core components and monitoring
        if chatbot_service is None:
            self.chatbot_service = ChatbotService()
        else:
            self.chatbot_service = chatbot_service
        self.request_history = []
        self._history_lock = asyncio.Lock()
        self.service_metrics = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "average_response_time": 0.0,
            "service_start_time": datetime.now().isoformat(),
        }

    async def chat_with_memory(
        self, query: str, custom_history: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """
        Unified chat method: always uses history memory, configurable length.
        If custom_history is provided, use it; otherwise, use global history.
        """
        start_time = time.time()
        request_id = f"chat_{int(time.time() * 1000)}"
        logger.info(f"🔍 Processing chat request {request_id}: {query[:50]}...")
        await self._history_lock.acquire()
        try:
            # Update request metrics for monitoring
            self.service_metrics["total_requests"] += 1

            # Validate input query for processing
            if not query or not query.strip():
                return self._create_error_response(
                    query, "Empty query provided", request_id, start_time
                ).dict()

            # Check chatbot service availability before processing
            if not self.chatbot_service.api_available:
                logger.error("❌ ChatbotService not available")
                return self._create_error_response(
                    query,
                    "Chat service is currently unavailable",
                    request_id,
                    start_time,
                ).dict()

            # Load vector store with error handling for knowledge base access
            try:
                _, current_embeddings, current_documents = (
                    vector_store.load_vector_store()
                )
            except Exception as e:
                logger.error(f"❌ Error loading vector store: {e}")
                return self._create_error_response(
                    query,
                    "Knowledge base is currently unavailable",
                    request_id,
                    start_time,
                ).dict()

            # Handle empty knowledge base gracefully with universal prompt
            if not current_documents:
                logger.info(
                    "💬 No documents in knowledge base - using universal prompt"
                )
                current_embeddings = np.array([])
                current_documents = []
            else:
                logger.info(
                    f"📚 Knowledge base loaded: {len(current_documents)} documents"
                )
                if current_embeddings is None:
                    current_embeddings = np.array([])
                elif isinstance(current_embeddings, list):
                    current_embeddings = np.array(current_embeddings)

            # Prepare history
            if custom_history is not None:
                history = custom_history[-LLMConfig.LLM_HISTORY_LENGTH() :]
            else:
                history = self.request_history[-LLMConfig.LLM_HISTORY_LENGTH() :]
            # Note: Don't add current query to history here - it will be added in get_response_with_history

            # Generate response using chatbot service with history
            try:
                result = self.chatbot_service.get_response_with_history(
                    query,
                    embeddings=current_embeddings,
                    documents=current_documents,
                    history=history,
                )
                # Calculate total processing time for performance monitoring
                processing_time = time.time() - start_time
                # Update service metrics for health monitoring
                self.service_metrics["successful_requests"] += 1
                self._update_average_response_time(processing_time)
                logger.info(
                    f"✅ Request {request_id} completed successfully in {processing_time:.2f}s"
                )
                # Extract response and metadata from result for comprehensive response
                response_text = result.get("response", "")
                confidence_score = result.get("confidence", 0.0)
                confidence_level = result.get("confidence_level", "Unknown")
                confidence_details = result.get("confidence_details", {})
                search_results = result.get("search_results", {})
                is_cached = result.get("cached", False)
                # Update global history (append user and assistant turns)
                if custom_history is None:
                    self.request_history.append({"role": "user", "content": query})
                    self.request_history.append(
                        {"role": "assistant", "content": response_text}
                    )
                    # Trim to max history length
                    self.request_history = self.request_history[
                        -(LLMConfig.LLM_HISTORY_LENGTH() * 2) :
                    ]
                return BaseResponse(
                    status=StatusEnum.SUCCESS,
                    response=response_text,
                    query=query,
                    request_id=request_id,
                    document_count=len(current_documents),
                    processing_time=processing_time,
                    confidence={
                        "score": confidence_score,
                        "level": confidence_level,
                        "details": confidence_details,
                    },
                    search_metadata={
                        "results_count": search_results.get("count", 0),
                        "top_scores": search_results.get("top_scores", []),
                        "cached_response": is_cached,
                    },
                    error=None,
                ).dict()
            except Exception as e:
                logger.error(
                    f"❌ Error in chatbot service for request {request_id}: {e}"
                )
                self.service_metrics["failed_requests"] += 1
                return self._create_error_response(
                    query,
                    f"Error generating response: {str(e)}",
                    request_id,
                    start_time,
                    document_count=len(current_documents),
                ).dict()
        finally:
            self._history_lock.release()

    def _create_error_response(
        self,
        query: str,
        error_msg: str,
        request_id: str,
        start_time: float,
        document_count: int = 0,
    ) -> ErrorResponse:
        """Create standardized error response using ErrorResponse model."""
        processing_time = time.time() - start_time
        return ErrorResponse(
            status=StatusEnum.ERROR,
            message=error_msg,
            error_code="CHAT_ERROR",
            details={
                "query": query,
                "request_id": request_id,
                "document_count": document_count,
                "processing_time": processing_time,
            },
        )

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
            logger.debug("🔍 Checking knowledge base status...")
            _, current_embeddings, current_documents = vector_store.load_vector_store()

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
                "vector_store_path": vector_store.vector_store_path,
                "health": "healthy" if current_documents else "no_data",
            }

            logger.debug(
                f"✅ Knowledge base status: {status_info['status']} ({status_info['document_count']} docs)"
            )
            return status_info

        except Exception as e:
            logger.error(f"❌ Error getting knowledge base status: {str(e)}")
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
                success_rate < HealthConfig.SERVICE_SUCCESS_RATE_THRESHOLD()
                and total_requests > HealthConfig.SERVICE_MIN_REQUESTS_FOR_HEALTH()
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
            logger.error(f"❌ Error getting comprehensive service status: {e}")
            return {
                "service_name": "ChatService",
                "overall_health": "error",
                "service_available": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }

    def reset_metrics(self):
        """Reset service metrics for monitoring purposes."""
        logger.info("🔄 Resetting ChatService metrics")
        self.service_metrics = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "average_response_time": 0.0,
            "service_start_time": datetime.now().isoformat(),
        }
        self.request_history.clear()

    def clear_cache(self) -> Dict[str, Any]:
        """Clear the chatbot service cache."""
        try:
            result = self.chatbot_service.clear_cache()
            logger.info(f"🧹 Chat service cache cleared: {result}")
            return result
        except Exception as e:
            logger.error(f"Failed to clear cache: {e}")
            return {
                "message": "Failed to clear cache",
                "error": str(e),
                "cleared_entries": 0,
                "current_cache_size": 0,
            }

    async def stream_chat_with_memory(
        self, query: str, custom_history: Optional[List[Dict[str, str]]] = None
    ) -> AsyncGenerator[str, None]:
        """
        Async generator for streaming chat responses with memory/history support.
        Calls the streaming method on ChatbotService and yields tokens.
        """
        await self._history_lock.acquire()
        try:
            # Validate input query
            if not query or not query.strip():
                yield "[ERROR] Empty query provided."
                return
            if not self.chatbot_service.api_available:
                yield "[ERROR] Chat service is currently unavailable."
                return
            # Load vector store
            try:
                _, current_embeddings, current_documents = (
                    vector_store.load_vector_store()
                )
            except Exception as e:
                yield f"[ERROR] Knowledge base unavailable: {str(e)}"
                return
            if not current_documents:
                current_embeddings = np.array([])
                current_documents = []
            else:
                if current_embeddings is None:
                    current_embeddings = np.array([])
                elif isinstance(current_embeddings, list):
                    current_embeddings = np.array(current_embeddings)
            # Prepare history
            if custom_history is not None:
                history = custom_history[-LLMConfig.LLM_HISTORY_LENGTH() :]
            else:
                history = self.request_history[-LLMConfig.LLM_HISTORY_LENGTH() :]
            # Note: Don't add current query to history here - it will be added in stream_response_with_history
            # Stream response from chatbot_service
            async for token in self.chatbot_service.stream_response_with_history(
                query,
                embeddings=current_embeddings,
                documents=current_documents,
                history=history,
            ):
                yield token
            # Optionally update global history (not done here to avoid race conditions in streaming)
        finally:
            self._history_lock.release()
