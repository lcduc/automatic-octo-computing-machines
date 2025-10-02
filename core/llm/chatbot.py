"""
Simple, powerful chatbot service - RAG-powered conversation engine.
Handles query processing, context retrieval, and response generation with confidence scoring.
"""

import logging
import time
import asyncio
import hashlib
from typing import Dict, Any, List, Optional, AsyncGenerator, Union, cast
from core.caching import get_cache_service
from concurrent.futures import ThreadPoolExecutor, as_completed
import httpx
import openai
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from config.llm.llm_config import LLMConfig
from config.rag.rag_config import RAGConfig
from .prompts import PromptManager, SystemPrompts
from .confidence import ConfidenceScorer
from models.responses import ChatResponse, ErrorResponse, BaseResponse, StatusEnum

logger = logging.getLogger(__name__)


class ChatbotService:
    """
    RAG-powered chatbot service with smart caching, confidence scoring, and batch processing.
    Handles document retrieval, context building, and AI response generation.
    """

    def __init__(self, context_retriever=None):
        """
        Initialize ChatbotService with optional context retriever.
        
        Args:
            context_retriever: Optional ContextRetriever instance for RAG operations
        """
        from core.rag.retriever import ContextRetriever
        
        if context_retriever is None:
            self.context_retriever = ContextRetriever()
        else:
            self.context_retriever = context_retriever
        
        # Initialize missing components
        self.prompt_manager = PromptManager()
        self.confidence_scorer = ConfidenceScorer()
        
        # Initialize cache
        self._cache = {}
        self._cache_ttl = LLMConfig.LLM_CACHE_TTL()
        
        # Initialize async OpenAI client
        self.async_openai_client = AsyncOpenAI(api_key=LLMConfig.OPENAI_API_KEY())
        
        # Initialize thread pool workers
        self._max_workers = LLMConfig.LLM_MAX_WORKERS()
        
        # Test API availability on initialization
        self._api_available = self._test_api()

    @property
    def api_available(self) -> bool:
        """Check if the OpenAI API is available."""
        return self._api_available

    def _test_api(self) -> bool:
        """Test OpenAI API availability and connectivity."""
        if not LLMConfig.OPENAI_API_KEY():
            logger.warning("⚠️ OpenAI API key not configured")
            return False
        try:
            client = openai.OpenAI(api_key=LLMConfig.OPENAI_API_KEY())
            client.chat.completions.create(
                model=LLMConfig.OPENAI_MODEL(),
                messages=[{"role": "user", "content": "test"}],
                max_tokens=1
            )
            logger.info("✅ OpenAI API available")
            return True
        except Exception as e:
            logger.warning(f"⚠️ OpenAI API not available: {e}")
            return False

    def _create_error_response(self, query: str, error_msg: str) -> ErrorResponse:
        """Create standardized error response using ErrorResponse model."""
        return ErrorResponse(
            status=StatusEnum.ERROR,
            message=error_msg,
            error_code="LLM_ERROR",
            details={"query": query},
        )

    def get_response(self, query: str, embeddings=None, documents=None) -> Union[ChatResponse, ErrorResponse]:
        """
        Generate AI response using RAG system with context retrieval and confidence scoring.
        
        Args:
            query: User query to process
            embeddings: Document embeddings for semantic search
            documents: Document collection for context retrieval

        Returns:
            Dict containing response, confidence metrics, and search metadata
        """
        if not self.api_available:
            error_response = self._create_error_response(query, "I apologize, but the chat service is currently unavailable. Please try again later.")
            return error_response

        try:
            logger.info(f"🤖 [Request] Received query: '{query[:50]}...' (id={hashlib.md5(query.encode()).hexdigest()[:8]})")
            
            # Retrieve relevant context from documents using hybrid search
            context = ""
            search_results = []
            if documents is not None and embeddings is not None and len(documents) > 0:
                logger.info(f"\U0001f4da RAG enabled: {len(documents)} documents available")
                try:
                    # Use enhanced hybrid search with query expansion
                    search_results = self.context_retriever.hybrid_search(
                        query=query,
                        embeddings=embeddings,
                        documents=documents,
                        k=RAGConfig.RETRIEVAL_TOP_K(),
                        semantic_weight=RAGConfig.SEMANTIC_WEIGHT()
                    )
                    
                    # Assemble context from top-ranked chunks for precision
                    if search_results:
                        context_chunks = []
                        for result in search_results:
                            context_chunks.append(f"[Chunk {result['index']}]\n{result['document']}\n")
                        context = "\n".join(context_chunks)
                    else:
                        context = ""
                    
                    logger.info(f"📄 Retrieved context length: {len(context)} characters")
                    
                    # Log context preview for debugging
                    if context:
                        context_preview = context[:200].replace('\n', ' ').replace('\r', ' ')
                        logger.info(f"📄 Context preview: {context_preview}...")
                    else:
                        logger.warning("⚠️ No context retrieved from documents")
                    
                    # Optimize context length for performance
                    if context and len(context) > LLMConfig.MAX_CONTEXT_LENGTH():
                        original_length = len(context)
                        context = context[:LLMConfig.MAX_CONTEXT_LENGTH()]
                        logger.debug(f"🔧 Context truncated: {original_length} -> {len(context)} chars for performance")
                except Exception as e:
                    logger.warning(f"⚠️ Context retrieval failed: {e}")
                    context = ""
            else:
                logger.info("📚 RAG disabled: No documents or embeddings provided")

            logger.debug(f"🔍 [Context] Retrieved {len(search_results)} context chunks for query (id={hashlib.md5(query.encode()).hexdigest()[:8]})")

            # Build OpenAI messages with system prompt and user query
            messages = [
                {"role": "system", "content": str(self.prompt_manager.get_system_prompt(context=context))}
            ]
            messages.append({"role": "user", "content": str(query)})

            # Check cache for performance optimization
            cache_key = self._get_cache_key(query, context)
            cached_response = self._get_cached_response(cache_key)
            if cached_response:
                logger.debug(f"⚡ [Cache] Hit for query (id={hashlib.md5(query.encode()).hexdigest()[:8]})")
                # Calculate confidence for cached response
                confidence = self.confidence_scorer.calculate_confidence(
                    cached_response, query, context, search_results
                )
                return ChatResponse(
                    status=StatusEnum.SUCCESS,
                    message="Response generated successfully",
                    response=cached_response,
                    query=query,
                    confidence={
                        "score": confidence.overall_score,
                        "level": self.confidence_scorer.get_confidence_level(confidence.overall_score),
                        "details": {
                            "context_alignment": confidence.context_alignment,
                            "response_length_appropriateness": confidence.response_length_appropriateness,
                            "semantic_coherence": confidence.semantic_coherence,
                            "source_citation": confidence.source_citation,
                            "uncertainty_indicators": confidence.uncertainty_indicators,
                            "reasoning": confidence.reasoning
                        }
                    },
                    search_metadata={
                        "results_count": len(search_results),
                        "top_scores": [r.get("combined_score", 0) for r in search_results[:3] if r.get("combined_score", 0) > 0],
                        "cached_response": True
                    }
                )
            else:
                logger.debug(f"⚡ [Cache] Miss for query (id={hashlib.md5(query.encode()).hexdigest()[:8]})")

            # Get system prompt for context-aware responses
            system_prompt = self.prompt_manager.get_system_prompt(context=context)
            logger.debug(f"📝 System prompt length: {len(system_prompt)} characters")

            # Make optimized API call to OpenAI
            logger.info(f"🚀 [LLM] Calling OpenAI for query (id={hashlib.md5(query.encode()).hexdigest()[:8]})")
            logger.debug(f"📝 [LLM Payload] {messages}")
            client = openai.OpenAI(api_key=LLMConfig.OPENAI_API_KEY())
            response = client.chat.completions.create(
                model=LLMConfig.OPENAI_MODEL(),
                messages=messages,  # type: ignore
                max_tokens=LLMConfig.OPENAI_MAX_TOKENS(),
                temperature=LLMConfig.OPENAI_TEMPERATURE(),
                timeout=LLMConfig.OPENAI_TIMEOUT()
            )

            content = response.choices[0].message.content
            response_text = content.strip() if content else ""
            logger.info(f"✅ Response generated: {len(response_text)} characters")
            logger.debug(f"📝 [LLM Response] {response_text[:100]}... (id={hashlib.md5(query.encode()).hexdigest()[:8]})")

            # Calculate comprehensive confidence score
            confidence = self.confidence_scorer.calculate_confidence(
                response_text, query, context, search_results
            )
            
            logger.debug(f"🎯 [Confidence] Score for query (id={hashlib.md5(query.encode()).hexdigest()[:8]}): {confidence.overall_score}")

            # Cache the response for future requests
            self._cache_response(cache_key, response_text)

            logger.debug("✅ Response generated successfully")
            return ChatResponse(
                status=StatusEnum.SUCCESS,
                message="Response generated successfully",
                response=response_text,
                query=query,
                confidence={
                    "score": confidence.overall_score,
                    "level": self.confidence_scorer.get_confidence_level(confidence.overall_score),
                    "details": {
                        "context_alignment": confidence.context_alignment,
                        "response_length_appropriateness": confidence.response_length_appropriateness,
                        "semantic_coherence": confidence.semantic_coherence,
                        "source_citation": confidence.source_citation,
                        "uncertainty_indicators": confidence.uncertainty_indicators,
                        "reasoning": confidence.reasoning
                    }
                },
                search_metadata={
                    "results_count": len(search_results),
                    "top_scores": [r.get("combined_score", 0) for r in search_results[:3] if r.get("combined_score", 0) > 0],
                    "cached_response": False
                }
            )

        except Exception as e:
            logger.error(f"❌ [Error] {str(e)} (id={hashlib.md5(query.encode()).hexdigest()[:8]})", exc_info=True)
            return self._create_error_response(query, "I apologize, but I encountered an error while processing your request. Please try again later.")

    def get_batch_responses(self, queries: List[str], embeddings=None, documents=None) -> List[Dict[str, Any]]:
        """
        Process multiple queries in parallel for improved performance.
        Uses ThreadPoolExecutor for concurrent processing with configurable worker limits.

        Args:
            queries: List of user queries to process
            embeddings: Document embeddings for semantic search
            documents: Document collection for context retrieval

        Returns:
            List of response dictionaries with query, response, and metadata
        """
        if not self.api_available:
            error_response = self._create_error_response("batch_queries", "I apologize, but the chat service is currently unavailable. Please try again later.")
            return [{"query": q, "response": error_response, "success": False, "error": "Service unavailable"} for q in queries]

        if not queries:
            return []

        logger.info(f"🚀 Processing {len(queries)} queries in parallel")
        start_time = time.time()

        # Use ThreadPoolExecutor for parallel processing with configurable workers
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            # Submit all queries for parallel processing
            future_to_query = {
                executor.submit(self._process_single_query, query, embeddings, documents): query
                for query in queries
            }

            results = []
            completed_count = 0

            # Collect results as they complete
            for future in as_completed(future_to_query):
                query = future_to_query[future]
                completed_count += 1

                try:
                    result = future.result()
                    results.append(result)
                    logger.debug(f"✅ Query {completed_count}/{len(queries)} completed: {query[:30]}...")
                except Exception as e:
                    logger.error(f"❌ Error processing query '{query[:30]}...': {e}")
                    results.append({
                        "query": query,
                        "response": self._create_error_response(query, "I apologize, but I encountered an error while processing this request."),
                        "success": False,
                        "error": str(e)
                    })

        # Sort results to match input order for consistent response
        query_to_result = {r["query"]: r for r in results}
        ordered_results = [query_to_result.get(q, {
            "query": q,
            "response": self._create_error_response(q, "Error: Result not found"),
            "success": False,
            "error": "Processing failed"
        }) for q in queries]

        total_time = time.time() - start_time
        logger.info(f"✅ Batch processing completed: {len(queries)} queries in {total_time:.2f}s")

        return ordered_results

    def _process_single_query(self, query: str, embeddings=None, documents=None) -> Dict[str, Any]:
        """
        Process a single query for batch processing with timing and error handling.
        Returns structured result with processing metadata.
        """
        start_time = time.time()

        try:
            result = self.get_response(query, embeddings, documents)
            processing_time = time.time() - start_time

            from models.responses import ChatResponse
            return {
                "query": query,
                "response": result.response if isinstance(result, ChatResponse) else None,
                "confidence": result.confidence if isinstance(result, ChatResponse) else None,
                "confidence_level": result.confidence["level"] if isinstance(result, ChatResponse) and result.confidence else None,
                "confidence_details": result.confidence["details"] if isinstance(result, ChatResponse) and result.confidence else None,
                "search_results": result.search_metadata if isinstance(result, ChatResponse) else None,
                "success": result.status == StatusEnum.SUCCESS,
                "processing_time": processing_time,
                "error": result.message if result.status == StatusEnum.ERROR else None
            }
        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"❌ Error in _process_single_query: {e}")

            return {
                "query": query,
                "response": self._create_error_response(query, "I apologize, but I encountered an error while processing this request."),
                "confidence": 0.0,
                "confidence_level": "Very Low",
                "confidence_details": {},
                "search_results": {},
                "success": False,
                "processing_time": processing_time,
                "error": str(e)
            }

    def get_multi_document_response(self, query: str, document_chunks: List[str]) -> Dict[str, Any]:
        """
        Process query against multiple document chunks in parallel for large document handling.
        Combines responses from all chunks into a comprehensive answer.

        Args:
            query: User query to process
            document_chunks: List of document chunks to search through

        Returns:
            Combined response from all relevant chunks with processing metadata
        """
        if not self.api_available:
            return {
                "query": query,
                "response": self._create_error_response(query, "I apologize, but the chat service is currently unavailable. Please try again later."),
                "success": False,
                "error": "Service unavailable"
            }

        if not document_chunks:
            result = self.get_response(query)
            from models.responses import ChatResponse
            return {
                "query": query,
                "response": result.response if isinstance(result, ChatResponse) else None,
                "success": isinstance(result, ChatResponse) and result.status == StatusEnum.SUCCESS,
                "chunks_processed": 0
            }

        logger.info(f"🔍 Processing query against {len(document_chunks)} document chunks in parallel")
        start_time = time.time()

        # Create queries for each chunk with context
        chunk_queries = []
        for chunk in document_chunks:
            chunk_query = f"Based on this document section: {chunk}\n\nQuestion: {query}"
            chunk_queries.append(chunk_query)

        # Process all chunks in parallel using batch processing
        chunk_results = self.get_batch_responses(chunk_queries)

        # Combine successful responses from all chunks
        successful_responses = [r["response"] for r in chunk_results if r["success"]]

        if not successful_responses:
            return {
                "query": query,
                "response": self._create_error_response(query, "I apologize, but I couldn't process any of the document chunks successfully."),
                "success": False,
                "error": "All chunk processing failed",
                "chunks_processed": 0
            }

        # Create a summary prompt to combine all chunk responses
        combined_context = "\n\n".join(successful_responses)
        summary_query = f"Based on these responses from different document sections:\n\n{combined_context}\n\nProvide a comprehensive answer to: {query}"

        # Get final combined response from all chunks
        final_response = self.get_response(summary_query)

        processing_time = time.time() - start_time

        # Defensive: handle both ChatResponse and ErrorResponse
        return {
            "query": query,
            "response": getattr(final_response, "response", getattr(final_response, "message", "")),
            "confidence": getattr(final_response, "confidence", None),
            "confidence_level": getattr(final_response, "confidence_level", None),
            "confidence_details": getattr(final_response, "confidence_details", None),
            "search_results": getattr(final_response, "search_metadata", None),
            "success": getattr(final_response, "status", None) == StatusEnum.SUCCESS,
            "chunks_processed": len(successful_responses),
            "total_chunks": len(document_chunks),
            "processing_time": processing_time,
            "error": getattr(final_response, "message", None) if getattr(final_response, "status", None) == StatusEnum.ERROR else None
        }

    def _get_cache_key(self, query: str, context: str) -> str:
        """Generate MD5-based cache key from query and context for efficient caching."""
        content = f"{query}:{context}"
        return hashlib.md5(content.encode()).hexdigest()[:16]

    def _get_cached_response(self, cache_key: str) -> Optional[str]:
        """Retrieve cached response if available and not expired based on TTL configuration."""
        if cache_key in self._cache:
            cached_data = self._cache[cache_key]
            if time.time() - cached_data['timestamp'] < self._cache_ttl:
                return cached_data['response']
            else:
                del self._cache[cache_key]  # Remove expired
        return None

    def _cache_response(self, cache_key: str, response: str):
        """Cache response with simple LRU."""
        # Simple LRU: remove oldest if cache is full
        if len(self._cache) >= LLMConfig.LLM_CACHE_MAX_ENTRIES():
            oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k]['timestamp'])
            del self._cache[oldest_key]

        self._cache[cache_key] = {
            'response': response,
            'timestamp': time.time()
        }

    def get_service_status(self) -> Dict[str, Any]:
        """Get simple service status."""
        return {
            "service_available": self.api_available,
            "model": LLMConfig.OPENAI_MODEL(),
            "max_tokens": LLMConfig.OPENAI_MAX_TOKENS(),
            "cache_size": len(self._cache)
        }
    
    def clear_cache(self) -> Dict[str, Any]:
        """Clear the response cache."""
        cache_size = len(self._cache)
        self._cache.clear()
        logger.info(f"🧹 Cache cleared: {cache_size} entries removed")
        return {
            "message": "Cache cleared successfully",
            "cleared_entries": cache_size,
            "current_cache_size": 0
        }

    def get_response_with_history(self, query: str, embeddings=None, documents=None, history: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
        """
        Generate response from query with conversation history.
        Now includes confidence scoring, enhanced metadata, and conversation history.

        Args:
            query: User query
            embeddings: Document embeddings (optional)
            documents: Document list (optional)
            history: Conversation history (optional)

        Returns:
            Dict containing response text, confidence score, and metadata
        """
        if not self.api_available:
            error_response = self._create_error_response(query, "I apologize, but the chat service is currently unavailable. Please try again later.")
            return {
                "response": error_response,
                "confidence": 0.0,
                "confidence_level": "Very Low",
                "success": False,
                "error": "Service unavailable"
            }

        try:
            logger.info(f"🤖 Processing query with history: '{query[:50]}...'")
            logger.info(f"📚 History length: {len(history) if history else 0} messages")
            
            # Get context if documents provided
            context = ""
            search_results = []
            if documents is not None and embeddings is not None and len(documents) > 0:
                logger.info(f"📚 RAG enabled: {len(documents)} documents available")
                try:
                    # Use enhanced hybrid search with query expansion
                    search_results = self.context_retriever.hybrid_search(
                        query=query,
                        embeddings=embeddings,
                        documents=documents,
                        k=RAGConfig.RETRIEVAL_TOP_K(),
                        semantic_weight=RAGConfig.SEMANTIC_WEIGHT()
                    )
                    
                    # Assemble context from top-ranked chunks for precision
                    context_chunks = []
                    for result in search_results:
                        context_chunks.append(f"[Chunk {result['index']}]\n{result['document']}\n")
                    context = "\n".join(context_chunks)
                    
                    logger.info(f"📄 Retrieved context length: {len(context)} characters")
                    
                    # Log context preview
                    if context:
                        context_preview = context[:200].replace('\n', ' ').replace('\r', ' ')
                        logger.info(f"📄 Context preview: {context_preview}...")
                    else:
                        logger.warning("⚠️ No context retrieved from documents")
                    
                    # Optimize context length for speed
                    if context and len(context) > LLMConfig.MAX_CONTEXT_LENGTH():
                        original_length = len(context)
                        context = context[:LLMConfig.MAX_CONTEXT_LENGTH()]
                        logger.debug(f"🔧 Context truncated: {original_length} -> {len(context)} chars for performance")
                except Exception as e:
                    logger.warning(f"⚠️ Context retrieval failed: {e}")
                    context = ""
            else:
                logger.info("📚 RAG disabled: No documents or embeddings provided")

            # Build OpenAI messages with history
            messages = [
                {"role": "system", "content": self.prompt_manager.get_system_prompt(context=context)}
            ]
            
            # Add conversation history if provided
            if history:
                # Limit history to prevent token overflow
                max_history_messages = min(len(history), 20)  # Limit to last 20 messages
                history_to_include = history[-max_history_messages:]
                messages.extend(history_to_include)
                logger.info(f"📚 Included {len(history_to_include)} history messages")
            
            # Add current query
            messages.append({"role": "user", "content": query})

            # Check cache for speed (cache key includes history for uniqueness)
            cache_key = self._get_cache_key_with_history(query, context, history)
            cached_response = self._get_cached_response(cache_key)
            if cached_response:
                logger.debug("⚡ Using cached response")
                # Calculate confidence for cached response
                confidence = self.confidence_scorer.calculate_confidence(
                    cached_response, query, context, search_results
                )
                return {
                    "response": cached_response,
                    "confidence": confidence.overall_score,
                    "confidence_level": self.confidence_scorer.get_confidence_level(confidence.overall_score),
                    "confidence_details": {
                        "context_alignment": confidence.context_alignment,
                        "response_length_appropriateness": confidence.response_length_appropriateness,
                        "semantic_coherence": confidence.semantic_coherence,
                        "source_citation": confidence.source_citation,
                        "uncertainty_indicators": confidence.uncertainty_indicators,
                        "reasoning": confidence.reasoning
                    },
                    "success": True,
                    "cached": True
                }

            # Get system prompt
            system_prompt = self.prompt_manager.get_system_prompt(context=context)
            logger.debug(f"📝 System prompt length: {len(system_prompt)} characters")

            # Make optimized API call
            logger.info("🚀 Making API call to OpenAI...")
            client = openai.OpenAI(api_key=LLMConfig.OPENAI_API_KEY())
            response = client.chat.completions.create(
                model=LLMConfig.OPENAI_MODEL(),
                messages=messages,  # type: ignore
                max_tokens=LLMConfig.OPENAI_MAX_TOKENS(),
                temperature=LLMConfig.OPENAI_TEMPERATURE(),
                timeout=LLMConfig.OPENAI_TIMEOUT()
            )

            content = response.choices[0].message.content
            response_text = content.strip() if content else ""
            logger.info(f"✅ Response generated: {len(response_text)} characters")
            logger.debug(f"📝 Response preview: {response_text[:100]}...")

            # Calculate confidence score
            confidence = self.confidence_scorer.calculate_confidence(
                response_text, query, context, search_results
            )
            
            logger.info(f"🎯 Confidence score: {confidence.overall_score:.3f} ({self.confidence_scorer.get_confidence_level(confidence.overall_score)})")

            # Cache the response for speed
            self._cache_response(cache_key, response_text)

            logger.debug("✅ Response generated successfully")
            return {
                "response": response_text,
                "confidence": confidence.overall_score,
                "confidence_level": self.confidence_scorer.get_confidence_level(confidence.overall_score),
                "confidence_details": {
                    "context_alignment": confidence.context_alignment,
                    "response_length_appropriateness": confidence.response_length_appropriateness,
                    "semantic_coherence": confidence.semantic_coherence,
                    "source_citation": confidence.source_citation,
                    "uncertainty_indicators": confidence.uncertainty_indicators,
                    "reasoning": confidence.reasoning
                },
                "search_results": {
                    "count": len(search_results),
                    "top_scores": [r.get("combined_score", 0) for r in search_results[:3] if r.get("combined_score", 0) > 0]
                },
                "success": True,
                "cached": False
            }

        except Exception as e:
            logger.error(f"❌ Error generating response: {e}")
            error_response = self._create_error_response(query, "I apologize, but I encountered an error while processing your request. Please try again later.")
            return {
                "response": error_response,
                "confidence": 0.0,
                "confidence_level": "Very Low",
                "success": False,
                "error": str(e)
            }

    def _get_cache_key_with_history(self, query: str, context: str, history: Optional[List[Dict[str, str]]] = None) -> str:
        """Generate cache key including conversation history."""
        history_str = ""
        if history:
            # Create a hash of the history for the cache key
            history_content = "".join([msg.get("content", "") for msg in history])
            history_str = hashlib.md5(history_content.encode()).hexdigest()[:8]
        
        return hashlib.md5(f"{query}:{context}:{history_str}".encode()).hexdigest()

    async def async_get_response(self, query: str, embeddings=None, documents=None) -> Dict[str, Any]:
        """
        Async version of get_response using OpenAI's AsyncOpenAI client and async context retrieval.
        """
        if not self.api_available:
            error_response = self._create_error_response(query, "I apologize, but the chat service is currently unavailable. Please try again later.")
            return {
                "response": error_response,
                "confidence": 0.0,
                "confidence_level": "Very Low",
                "success": False,
                "error": "Service unavailable"
            }
        context = ""
        search_results = []
        # Async context retrieval if RAG enabled
        if documents is not None and embeddings is not None and len(documents) > 0:
            try:
                # Use hybrid search instead of simple semantic search for better results
                search_results = self.context_retriever.hybrid_search(
                    query=query,
                    embeddings=embeddings,
                    documents=documents,
                    k=RAGConfig.RETRIEVAL_TOP_K(),
                    semantic_weight=RAGConfig.SEMANTIC_WEIGHT()
                )
                
                # Build context from top-ranked chunks
                if search_results:
                    context_chunks = []
                    for result in search_results:
                        context_chunks.append(f"[Chunk {result['index']}]\n{result['document']}\n")
                    context = "\n".join(context_chunks)
            except Exception as e:
                logger.warning(f"⚠️ Hybrid search failed: {e}")
                context = ""
        # Build OpenAI messages with system prompt and user query
        messages: List[ChatCompletionMessageParam] = [
            {"role": "system", "content": str(self.prompt_manager.get_system_prompt(context=context))}
        ]
        messages.append({"role": "user", "content": str(query)})

        # Check cache for performance optimization
        cache_key = self._get_cache_key(query, context)
        cached_response = self._get_cached_response(cache_key)
        if cached_response:
            confidence = self.confidence_scorer.calculate_confidence(
                cached_response, query, context, search_results
            )
            return {
                "response": cached_response,
                "confidence": confidence.overall_score,
                "confidence_level": self.confidence_scorer.get_confidence_level(confidence.overall_score),
                "confidence_details": {
                    "context_alignment": confidence.context_alignment,
                    "response_length_appropriateness": confidence.response_length_appropriateness,
                    "semantic_coherence": confidence.semantic_coherence,
                    "source_citation": confidence.source_citation,
                    "uncertainty_indicators": confidence.uncertainty_indicators,
                    "reasoning": confidence.reasoning
                },
                "success": True,
                "cached": True
            }
        try:
            # Async OpenAI call using the shared AsyncOpenAI client
            response = await self.async_openai_client.chat.completions.create(
                model=LLMConfig.OPENAI_MODEL(),
                messages=messages,  # type: ignore
                max_tokens=LLMConfig.OPENAI_MAX_TOKENS(),
                temperature=LLMConfig.OPENAI_TEMPERATURE()
            )
            content = response.choices[0].message.content
            response_text = content.strip() if content else ""
            # Calculate confidence score
            confidence = self.confidence_scorer.calculate_confidence(
                response_text, query, context, search_results
            )
            # Cache the response for future requests
            self._cache_response(cache_key, response_text)
            return {
                "response": response_text,
                "confidence": confidence.overall_score,
                "confidence_level": self.confidence_scorer.get_confidence_level(confidence.overall_score),
                "confidence_details": {
                    "context_alignment": confidence.context_alignment,
                    "response_length_appropriateness": confidence.response_length_appropriateness,
                    "semantic_coherence": confidence.semantic_coherence,
                    "source_citation": confidence.source_citation,
                    "uncertainty_indicators": confidence.uncertainty_indicators,
                    "reasoning": confidence.reasoning
                },
                "search_results": {
                    "count": len(search_results),
                    "top_scores": [r.get("combined_score", 0) for r in search_results[:3]]
                },
                "success": True,
                "cached": False
            }
        except Exception as e:
            logger.error(f"❌ Error generating async response: {e}")
            error_response = self._create_error_response(query, "I apologize, but I encountered an error while processing your request. Please try again later.")
            return {
                "response": error_response,
                "confidence": 0.0,
                "confidence_level": "Very Low",
                "confidence_details": {},
                "search_results": {},
                "success": False,
                "cached": False,
                "error": str(e)
            }

    async def async_get_batch_responses(self, queries: List[str], embeddings=None, documents=None) -> List[Dict[str, Any]]:
        """
        Async batch processing of queries using asyncio.gather for concurrent LLM calls.
        """
        if not self.api_available:
            error_response = self._create_error_response("batch_queries", "I apologize, but the chat service is currently unavailable. Please try again later.")
            return [{"query": q, "response": error_response, "success": False, "error": "Service unavailable"} for q in queries]
        if not queries:
            return []
        logger.info(f"🚀 Processing {len(queries)} queries concurrently (async)")
        tasks = [self.async_get_response(query, embeddings, documents) for query in queries]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # Handle exceptions in results
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"❌ Error processing query '{queries[i][:30]}...': {result}")
                final_results.append({
                    "query": queries[i],
                    "response": self._create_error_response(queries[i], "I apologize, but I encountered an error while processing this request."),
                    "success": False,
                    "error": str(result)
                })
            else:
                if isinstance(result, dict):
                    result["query"] = queries[i]
                final_results.append(result)
        return final_results

    async def stream_response_with_history(self, query: str, embeddings=None, documents=None, history: Optional[List[Dict[str, str]]] = None) -> AsyncGenerator[str, None]:
        """
        Async generator that streams response tokens from OpenAI with conversation history.
        Uses AsyncOpenAI for better performance and async context retrieval.
        Yields each token as it is generated.
        """
        if not self.api_available:
            yield "[ERROR] Chat service unavailable."
            return

        try:
            # Async context retrieval if RAG enabled
            context = ""
            search_results = []
            if documents is not None and embeddings is not None and len(documents) > 0:
                try:
                    # Use hybrid search instead of simple semantic search for better results
                    search_results = self.context_retriever.hybrid_search(
                        query=query,
                        embeddings=embeddings,
                        documents=documents,
                        k=RAGConfig.RETRIEVAL_TOP_K(),
                        semantic_weight=RAGConfig.SEMANTIC_WEIGHT()
                    )
                    
                    # Build context from hybrid search results
                    if search_results:
                        context_chunks = []
                        for result in search_results:
                            context_chunks.append(f"[Chunk {result['index']}]\n{result['document']}\n")
                        context = "\n".join(context_chunks)
                    
                    if context and len(context) > LLMConfig.MAX_CONTEXT_LENGTH():
                        context = context[:LLMConfig.MAX_CONTEXT_LENGTH()]
                except Exception as e:
                    logger.warning(f"⚠️ Hybrid search failed: {e}")
                    context = ""
            
            # Build messages with proper OpenAI types
            openai_messages: List[ChatCompletionMessageParam] = [
                {"role": "system", "content": str(self.prompt_manager.get_system_prompt(context=context))}
            ]
            if history:
                max_history_messages = min(len(history), 20)
                history_to_include = history[-max_history_messages:]
                for msg in history_to_include:
                    # Ensure each message is a dict with 'role' and 'content' as str
                    if isinstance(msg, dict) and "role" in msg and "content" in msg:
                        openai_messages.append(cast(ChatCompletionMessageParam, {"role": str(msg["role"]), "content": str(msg["content"])}))
            openai_messages.append({"role": "user", "content": str(query)})

            # Use the shared AsyncOpenAI client for streaming
            response_stream = await self.async_openai_client.chat.completions.create(
                model=LLMConfig.OPENAI_MODEL(),
                messages=openai_messages,  # type: ignore
                max_tokens=LLMConfig.OPENAI_MAX_TOKENS(),
                temperature=LLMConfig.OPENAI_TEMPERATURE(),
                stream=True
            )
            async for chunk in response_stream:
                content = chunk.choices[0].delta.content
                if content is not None:
                    yield content
        except Exception as e:
            yield f"[ERROR] {str(e)}"
