"""
RAG-powered conversation engine.

Orchestrates retrieval, prompt assembly, caching, LLM invocation and confidence
scoring. The mechanics of each of those steps live in dedicated collaborators
(:mod:`response_cache`, :mod:`openai_client`, :mod:`response_factory` and
``ContextAssembler``) so this class stays an orchestrator.
"""

# Standard library imports
import asyncio
import hashlib
import logging
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

# Third-party imports
import openai
from openai import APIConnectionError, APIStatusError, APITimeoutError

# Local imports
from config.settings import Config
from core.infrastructure.audit import AuditTrailService, get_audit_trail_service
from models.audit_entry import AuditEntry
from models.responses import ChatResponse, ErrorResponse, StatusEnum
from ..confidence.confidence import ConfidenceScorer
from .openai_client import OpenAIClientProvider
from .prompts import PromptManager
from .query_rewriter import QueryRewriter
from .response_cache import ResponseCache
from .response_factory import ChatResponseFactory

logger = logging.getLogger(__name__)

#: User-facing failure text, kept in one place so wording stays consistent.
UNAVAILABLE_MESSAGE = (
    "I apologize, but the chat service is currently unavailable. Please try again later."
)
TIMEOUT_MESSAGE = (
    "The AI service is taking too long to respond. Please try again with a simpler question."
)
RATE_LIMIT_MESSAGE = "The AI service is currently busy. Please try again in a moment."
GENERIC_ERROR_MESSAGE = (
    "I apologize, but I encountered an error while processing your request. "
    "Please try again later."
)

#: Upper bound on conversation turns replayed into the prompt.
MAX_HISTORY_MESSAGES = 20


class ChatbotService:
    """
    RAG chatbot facade: retrieval, caching, generation and confidence scoring.

    A single instance is intended to be shared process-wide; it owns pooled
    OpenAI clients and a response cache that must not be rebuilt per request.
    """

    def __init__(
        self,
        context_retriever=None,
        client_provider: Optional[OpenAIClientProvider] = None,
        response_cache: Optional[ResponseCache] = None,
        audit_trail: Optional[AuditTrailService] = None,
    ):
        """
        Args:
            context_retriever: Retriever used for hybrid search; created lazily
                from the default implementation when omitted.
            client_provider: Owner of the OpenAI clients.
            response_cache: Cache of previously generated answers.
            audit_trail: Recorder for the per-turn audit log; defaults to the
                process-wide instance.
        """
        from core.retrieval.search.context_builder import ContextAssembler
        from core.retrieval.search.retriever import ContextRetriever

        self.context_retriever = context_retriever or ContextRetriever()
        self.prompt_manager = PromptManager()
        self.confidence_scorer = ConfidenceScorer()
        self.context_assembler = ContextAssembler()

        self._client_provider = client_provider or OpenAIClientProvider()
        self.query_rewriter = QueryRewriter(self._client_provider)
        self._cache = response_cache or ResponseCache(
            max_entries=Config.LLM.LLM_CACHE_MAX_ENTRIES(),
            ttl_seconds=Config.LLM.LLM_CACHE_TTL(),
        )
        self._audit_trail = audit_trail or get_audit_trail_service()
        self._responses = ChatResponseFactory(self.confidence_scorer)
        self._api_available = self._client_provider.check_availability()

        # Retrieval (embedding + BM25 + cross-encoder rerank) is CPU/GPU-bound
        # and synchronous; the async paths below run it in a worker thread so
        # one slow request cannot stall every other concurrent request's event
        # loop turn. The semaphore caps how many of those run at once so a
        # burst of concurrent chats cannot exceed the GPU's memory budget.
        self._retrieval_semaphore = asyncio.Semaphore(Config.RAG.RETRIEVAL_MAX_CONCURRENCY())

    # ------------------------------------------------------------------
    # Service state
    # ------------------------------------------------------------------

    @property
    def api_available(self) -> bool:
        """Whether the OpenAI API was reachable at start-up."""
        return self._api_available

    def get_service_status(self) -> Dict[str, Any]:
        """Model configuration and cache counters for monitoring endpoints."""
        cache_stats = self._cache.get_stats()
        return {
            "service_available": self.api_available,
            "model": Config.LLM.OPENAI_MODEL(),
            "max_tokens": Config.LLM.OPENAI_MAX_TOKENS(),
            "cache_size": cache_stats["size"],
            "cache_hits": cache_stats["hits"],
            "cache_misses": cache_stats["misses"],
            "cache_hit_rate": cache_stats["hit_rate"],
        }

    def clear_cache(self) -> Dict[str, Any]:
        """Empty the answer cache."""
        cleared = self._cache.clear()
        logger.info("Cache cleared: %d entries removed", cleared)
        return {
            "message": "Cache cleared successfully",
            "cleared_entries": cleared,
            "current_cache_size": 0,
        }

    def cleanup(self) -> None:
        """Release pooled HTTP connections held by the OpenAI clients."""
        self._client_provider.close()
        logger.info("ChatbotService cleanup completed")

    # ------------------------------------------------------------------
    # Speech-to-text
    # ------------------------------------------------------------------

    async def transcribe_audio(
        self,
        audio_bytes: bytes,
        filename: str,
        content_type: str = "audio/wav",
    ) -> str:
        """
        Transcribe a recorded/uploaded audio clip so it can be used as a query.

        Runs the OpenAI SDK's blocking call in a worker thread via
        ``asyncio.to_thread`` so it does not stall the event loop for the
        duration of the upload and transcription.

        Args:
            audio_bytes: Raw audio file content.
            filename: Original filename; its extension hints the audio
                format to the API.
            content_type: MIME type reported by the client.

        Returns:
            The transcribed text.

        Raises:
            openai.APITimeoutError, openai.RateLimitError, Exception: propagated
                from the API call so callers can map them to user-facing text.
        """
        logger.info("Transcribing audio upload %s (%d bytes)", filename, len(audio_bytes))
        text = await asyncio.to_thread(
            self._client_provider.transcribe, audio_bytes, filename, content_type
        )
        logger.debug("Transcription complete: %d chars", len(text))
        return text

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _query_id(query: str) -> str:
        """Short, stable identifier used to correlate log lines for one query."""
        return hashlib.md5(query.encode("utf-8")).hexdigest()[:8]

    def _create_error_response(self, query: str, error_msg: str) -> ErrorResponse:
        """Create the standardized error envelope for a failed query."""
        return ErrorResponse(
            status=StatusEnum.ERROR,
            message=error_msg,
            error_code="LLM_ERROR",
            details={"query": query},
        )

    def _retrieve_context(
        self,
        query: str,
        embeddings,
        documents,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> tuple[str, List[Dict[str, Any]], str]:
        """
        Run hybrid search and assemble the prompt context.

        The search string is condensed from ``history`` + ``query`` when
        history is present, so a follow-up like "còn cái kia thì sao?" is
        searched as a standalone question instead of literally. The original
        ``query`` is untouched — only the retrieval input changes.

        Returns:
            A ``(context, search_results, search_query)`` triple; ``context``
            and ``search_results`` are empty when RAG is not applicable or
            retrieval fails. ``search_query`` is what was actually searched
            for (== ``query`` when there was no history to rewrite from), so
            callers can record it for auditing.
        """
        if documents is None or embeddings is None or len(documents) == 0:
            logger.debug("RAG disabled: no documents or embeddings provided")
            return "", [], query

        search_query = self.query_rewriter.rewrite(query, history)

        try:
            search_results = self.context_retriever.hybrid_search(
                query=search_query,
                embeddings=embeddings,
                documents=documents,
                k=Config.RAG.RETRIEVAL_TOP_K(),
                semantic_weight=Config.RAG.SEMANTIC_WEIGHT(),
            )
            context = self.context_assembler.build(search_results)
            logger.info(
                "Retrieved %d chunks (%d context chars) for query %s",
                len(search_results),
                len(context),
                self._query_id(query),
            )
            return context, search_results, search_query
        except Exception:
            logger.exception("Context retrieval failed for query %s", self._query_id(query))
            return "", [], search_query

    async def _retrieve_context_async(
        self,
        query: str,
        embeddings,
        documents,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> tuple[str, List[Dict[str, Any]], str]:
        """
        Async wrapper around :meth:`_retrieve_context` for use on the event loop.

        Runs the blocking retrieval work in the default thread pool executor,
        bounded by ``_retrieval_semaphore``, so concurrent chat requests share
        the GPU/CPU without one request's retrieval blocking every other
        request's async I/O in the meantime.
        """
        async with self._retrieval_semaphore:
            return await asyncio.to_thread(
                self._retrieve_context, query, embeddings, documents, history
            )

    def _build_messages(
        self,
        query: str,
        context: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> List[Dict[str, str]]:
        """
        Assemble the OpenAI message list: system prompt, history, user turn.

        The system message is static (see :class:`SystemPrompts`), so it is
        a stable, cacheable prefix; retrieved context is appended to the
        user turn instead of the system message so it never invalidates
        that prefix.
        """
        messages: List[Dict[str, str]] = [
            {
                "role": "system",
                "content": self.prompt_manager.get_system_prompt(),
            }
        ]
        if history:
            for message in history[-MAX_HISTORY_MESSAGES:]:
                if isinstance(message, dict) and "role" in message and "content" in message:
                    messages.append(
                        {"role": str(message["role"]), "content": str(message["content"])}
                    )
        messages.append(
            {"role": "user", "content": self.prompt_manager.build_context_block(str(query), context)}
        )
        return messages

    def _complete(
        self,
        query: str,
        context: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> tuple[str, bool]:
        """
        Return an answer for the query, from cache when possible.

        Returns:
            A ``(response_text, was_cached)`` pair.

        Raises:
            openai.APITimeoutError, openai.RateLimitError, Exception: propagated
                from the API call so callers can map them to user-facing text.
        """
        cache_key = ResponseCache.build_key(query, context, history)
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug("Cache hit for query %s", self._query_id(query))
            return cached, True

        messages = self._build_messages(query, context, history)
        response_text = self._client_provider.complete(messages)
        self._cache.set(cache_key, response_text)
        return response_text, False

    async def _complete_async(
        self,
        query: str,
        context: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> tuple[str, bool]:
        """Async counterpart of :meth:`_complete`, for callers on the event loop."""
        cache_key = ResponseCache.build_key(query, context, history)
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug("Cache hit for query %s", self._query_id(query))
            return cached, True

        messages = self._build_messages(query, context, history)
        response_text = await self._client_provider.complete_async(messages)
        self._cache.set(cache_key, response_text)
        return response_text, False

    def _score(self, response_text: str, query: str, context: str, search_results):
        """Compute the confidence breakdown for a generated answer."""
        return self.confidence_scorer.calculate_confidence(
            response_text, query, context, search_results or []
        )

    def _record_audit(
        self,
        query: str,
        response_text: str,
        confidence,
        search_results: Optional[List[Dict[str, Any]]],
        cached: bool,
        latency_ms: float,
        success: bool,
        error: Optional[str] = None,
        rewritten_query: Optional[str] = None,
    ) -> None:
        """
        Record one audit trail entry for an answered (or failed) turn.

        Never raises: a logging problem here must not affect the response
        already produced for the user.
        """
        if not Config.Audit.ENABLED():
            return
        try:
            confidence_score = confidence.overall_score if confidence is not None else 0.0
            confidence_level = (
                self.confidence_scorer.get_confidence_level(confidence_score)
                if confidence is not None
                else "Unknown"
            )
            entry = AuditEntry(
                query_id=self._query_id(query),
                query=query,
                rewritten_query=(
                    rewritten_query if rewritten_query and rewritten_query != query else None
                ),
                response=response_text,
                confidence_score=confidence_score,
                confidence_level=confidence_level,
                source_count=len(search_results or []),
                cached=cached,
                latency_ms=latency_ms,
                success=success,
                error=error,
            )
            self._audit_trail.record(entry)
        except Exception:
            logger.exception("Failed to build audit entry for query %s", self._query_id(query))

    @staticmethod
    def _map_api_error(exc: Exception) -> str:
        """Translate an OpenAI SDK exception into user-facing text."""
        if isinstance(exc, openai.APITimeoutError):
            return TIMEOUT_MESSAGE
        if isinstance(exc, openai.RateLimitError):
            return RATE_LIMIT_MESSAGE
        return f"AI service error: {exc}"

    # ------------------------------------------------------------------
    # Query-only generation
    # ------------------------------------------------------------------

    def get_response_with_context(
        self,
        query: str,
        context: str,
        search_results: Optional[List[Dict[str, Any]]] = None,
    ) -> Union[ChatResponse, ErrorResponse]:
        """
        Generate an answer from a pre-built context (no retrieval performed).

        Args:
            query: User query.
            context: Context block already assembled by the caller.
            search_results: Retrieved chunks, used for confidence scoring.

        Returns:
            A ``ChatResponse`` on success, otherwise an ``ErrorResponse``.
        """
        if not self.api_available:
            return self._create_error_response(query, UNAVAILABLE_MESSAGE)

        start_time = time.perf_counter()

        try:
            response_text, cached = self._complete(query, context)
        except Exception as exc:
            logger.exception("OpenAI call failed for query %s", self._query_id(query))
            self._record_audit(
                query, "", None, search_results, cached=False,
                latency_ms=(time.perf_counter() - start_time) * 1000,
                success=False, error=str(exc),
            )
            return self._create_error_response(query, self._map_api_error(exc))

        try:
            confidence = self._score(response_text, query, context, search_results)
            self._record_audit(
                query, response_text, confidence, search_results, cached=cached,
                latency_ms=(time.perf_counter() - start_time) * 1000,
                success=True,
            )
            return self._responses.chat_response(
                query, response_text, confidence, search_results, cached
            )
        except Exception:
            logger.exception("Failed to assemble response for query %s", self._query_id(query))
            return self._create_error_response(query, GENERIC_ERROR_MESSAGE)

    def get_response(
        self, query: str, embeddings=None, documents=None
    ) -> Union[ChatResponse, ErrorResponse]:
        """
        Retrieve context for the query and generate an answer.

        Args:
            query: User query.
            embeddings: Corpus embeddings for semantic search.
            documents: Corpus documents aligned with ``embeddings``.

        Returns:
            A ``ChatResponse`` on success, otherwise an ``ErrorResponse``.
        """
        if not self.api_available:
            return self._create_error_response(query, UNAVAILABLE_MESSAGE)

        context, search_results, _ = self._retrieve_context(query, embeddings, documents)
        return self.get_response_with_context(query, context, search_results)

    # ------------------------------------------------------------------
    # Async generation (used by batch processing)
    # ------------------------------------------------------------------

    async def async_get_response(
        self, query: str, embeddings=None, documents=None
    ) -> Dict[str, Any]:
        """
        Async, cache-aware, one-shot RAG query — the building block for batches.

        Args:
            query: User query.
            embeddings: Corpus embeddings for semantic search.
            documents: Corpus documents aligned with ``embeddings``.

        Returns:
            The history payload dict shape, with ``cached`` reflecting cache use.
        """
        if not self.api_available:
            return ChatResponseFactory.history_error_payload(UNAVAILABLE_MESSAGE)

        context, search_results, _ = await self._retrieve_context_async(query, embeddings, documents)
        try:
            response_text, cached = await self._complete_async(query, context)
            confidence = self._score(response_text, query, context, search_results)
            return self._responses.history_payload(
                response_text, confidence, search_results, cached
            )
        except Exception as exc:
            logger.exception("Async generation failed for query %s", self._query_id(query))
            return ChatResponseFactory.history_error_payload(self._map_api_error(exc))

    def _batch_failure(self, query: str, error: str) -> Dict[str, Any]:
        """Build the batch result entry for a query that could not be answered at all."""
        return {
            "query": query,
            "response": None,
            "success": False,
            "cached": False,
            "confidence": None,
            "error": error,
        }

    async def async_get_batch_responses(
        self, queries: List[str], embeddings=None, documents=None
    ) -> List[Dict[str, Any]]:
        """
        Answer several queries concurrently on the event loop.

        Args:
            queries: Queries to answer.
            embeddings: Corpus embeddings for semantic search.
            documents: Corpus documents aligned with ``embeddings``.

        Returns:
            One result dict per input query, in the original order.
        """
        if not queries:
            return []
        if not self.api_available:
            return [self._batch_failure(query, "Service unavailable") for query in queries]

        logger.info("Processing %d queries concurrently (async)", len(queries))
        tasks = [self.async_get_response(query, embeddings, documents) for query in queries]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        payloads: List[Dict[str, Any]] = []
        for query, result in zip(queries, results):
            if isinstance(result, Exception):
                logger.error("Error processing query '%s...': %s", query[:30], result)
                payloads.append(self._batch_failure(query, str(result)))
            else:
                result["query"] = query
                payloads.append(result)
        return payloads

    async def stream_response_with_history(
        self,
        query: str,
        embeddings=None,
        documents=None,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Stream an answer token-by-token, replaying conversation history.

        Checks the answer cache first (keyed on query + context + history): on
        a hit the cached text is yielded immediately instead of calling the
        LLM, which is the only place a repeated question actually saves a
        request, since this is the sole path the live ``/chat/`` route uses.

        Args:
            query: User query.
            embeddings: Corpus embeddings for semantic search.
            documents: Corpus documents aligned with ``embeddings``.
            history: Prior conversation turns.

        Yields:
            Text deltas, or a single ``[ERROR] ...`` string when generation fails.
        """
        if not self.api_available:
            yield "[ERROR] Chat service unavailable."
            return

        start_time = time.perf_counter()
        search_results: List[Dict[str, Any]] = []
        search_query = query
        chunks: List[str] = []

        def record_failure(error_text: str) -> None:
            """Audit a failed turn, capturing any partial text already streamed out."""
            self._record_audit(
                query,
                "".join(chunks),
                None,
                search_results,
                cached=False,
                latency_ms=(time.perf_counter() - start_time) * 1000,
                success=False,
                error=error_text,
                rewritten_query=search_query,
            )

        try:
            context, search_results, search_query = await self._retrieve_context_async(
                query, embeddings, documents, history
            )

            cache_key = ResponseCache.build_key(query, context, history)
            cached_text = self._cache.get(cache_key)
            if cached_text is not None:
                logger.debug("Cache hit for query %s", self._query_id(query))
                confidence = self._score(cached_text, query, context, search_results)
                self._record_audit(
                    query,
                    cached_text,
                    confidence,
                    search_results,
                    cached=True,
                    latency_ms=(time.perf_counter() - start_time) * 1000,
                    success=True,
                    rewritten_query=search_query,
                )
                yield cached_text
                return

            messages = self._build_messages(query, context, history)
            async for delta in self._client_provider.stream(messages):
                chunks.append(delta)
                yield delta
            response_text = "".join(chunks)
            self._cache.set(cache_key, response_text)

            confidence = self._score(response_text, query, context, search_results)
            self._record_audit(
                query,
                response_text,
                confidence,
                search_results,
                cached=False,
                latency_ms=(time.perf_counter() - start_time) * 1000,
                success=True,
                rewritten_query=search_query,
            )
        except APITimeoutError as exc:
            logger.exception("OpenAI API timeout during streaming")
            record_failure(str(exc))
            yield "[ERROR] Request timeout - the AI service took too long to respond."
        except APIStatusError as exc:
            logger.exception("OpenAI API status error during streaming")
            record_failure(str(exc))
            yield f"[ERROR] API error: {exc}"
        except (APIConnectionError, ConnectionResetError, OSError) as exc:
            logger.exception("Connection error during streaming")
            record_failure(str(exc))
            yield f"[ERROR] Connection error: Could not reach the AI service. {exc}"
        except Exception as exc:
            logger.exception("Unexpected error in stream_response_with_history")
            record_failure(str(exc))
            yield f"[ERROR] {exc}"
