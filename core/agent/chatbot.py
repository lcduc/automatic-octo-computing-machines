"""
RAG-powered conversation engine.

Orchestrates retrieval, prompt assembly, caching, LLM invocation and confidence
scoring. The mechanics of each of those steps live in dedicated collaborators
(:mod:`response_cache`, :mod:`base_llm_provider`, :mod:`response_factory` and
``ContextAssembler``) so this class stays an orchestrator.
"""

# Standard library imports
import asyncio
import hashlib
import logging
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

# Local imports
from config.settings import Config
from core.infrastructure.audit_trail_service import AuditTrailService, get_audit_trail_service
from models.audit_entry import AuditEntry
from models.intent import IntentType
from models.responses import ChatResponse, ErrorResponse, StatusEnum
from .confidence import ConfidenceScorer
from .base_llm_provider import BaseLLMProvider
from .intent_router import IntentRouter
from .openai_client import OpenAIClientProvider
from .provider_factory import LLMProviderFactory
from .prompts import PromptManager
from .query_rewriter import QueryRewriter
from .response_cache import ResponseCache
from .response_factory import ChatResponseFactory
from .tool_calling_agent import ToolCallingAgent
from .tools.current_time_tool import CurrentTimeTool
from .tools.registry import ToolRegistry

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

    A single instance is intended to be shared process-wide; it owns the
    active LLM provider's pooled clients and a response cache that must not
    be rebuilt per request.
    """

    def __init__(
        self,
        context_retriever=None,
        llm_provider: Optional[BaseLLMProvider] = None,
        response_cache: Optional[ResponseCache] = None,
        audit_trail: Optional[AuditTrailService] = None,
    ):
        """
        Args:
            context_retriever: Retriever used for hybrid search; created lazily
                from the default implementation when omitted.
            llm_provider: Owner of the chat-completion backend; built from
                ``Config.LLM.LLM_PROVIDER()`` via :class:`LLMProviderFactory`
                when omitted.
            response_cache: Cache of previously generated answers.
            audit_trail: Recorder for the per-turn audit log; defaults to the
                process-wide instance.
        """
        from core.retrieval.context_builder import ContextAssembler
        from core.retrieval.retriever import ContextRetriever

        self.context_retriever = context_retriever or ContextRetriever()
        self.prompt_manager = PromptManager()
        self.confidence_scorer = ConfidenceScorer()
        self.context_assembler = ContextAssembler()

        self._llm_provider = llm_provider or LLMProviderFactory.create()
        # Voice transcription only exists on OpenAI's API; reuse the active
        # provider's client when it already is one, otherwise a dedicated
        # instance is built lazily (see `_transcription_provider`) so a
        # non-OpenAI LLM_PROVIDER doesn't force an unrelated OpenAI client.
        self._dedicated_transcription_provider: Optional[OpenAIClientProvider] = None
        self.query_rewriter = QueryRewriter(self._llm_provider)
        self._tool_registry = ToolRegistry(tools=[CurrentTimeTool()])
        self._intent_router = IntentRouter(self._llm_provider, self._tool_registry)
        self._dedicated_tool_calling_provider: Optional[OpenAIClientProvider] = None
        self._cache = response_cache or ResponseCache(
            max_entries=Config.LLM.LLM_CACHE_MAX_ENTRIES(),
            ttl_seconds=Config.LLM.LLM_CACHE_TTL(),
        )
        self._audit_trail = audit_trail or get_audit_trail_service()
        self._responses = ChatResponseFactory(self.confidence_scorer)
        self._api_available = self._llm_provider.check_availability()

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
        """Whether the active provider's API was reachable at start-up."""
        return self._api_available

    def get_service_status(self) -> Dict[str, Any]:
        """Model configuration and cache counters for monitoring endpoints."""
        cache_stats = self._cache.get_stats()
        return {
            "service_available": self.api_available,
            "provider": Config.LLM.LLM_PROVIDER(),
            "model": Config.LLM.ACTIVE_MODEL(),
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
        """Release pooled HTTP connections held by the LLM clients."""
        self._llm_provider.close()
        if self._dedicated_transcription_provider is not None:
            self._dedicated_transcription_provider.close()
        if self._dedicated_tool_calling_provider is not None:
            self._dedicated_tool_calling_provider.close()
        logger.info("ChatbotService cleanup completed")

    # ------------------------------------------------------------------
    # Speech-to-text
    # ------------------------------------------------------------------

    def _transcription_provider(self) -> OpenAIClientProvider:
        """
        Return an OpenAI provider for transcription, regardless of ``LLM_PROVIDER``.

        Voice transcription only exists on OpenAI's API. When the active
        chat provider already is an ``OpenAIClientProvider`` it is reused
        directly; otherwise a dedicated instance is built lazily so choosing
        Anthropic or Gemini for chat doesn't require an unrelated OpenAI
        client to also be constructed up front.

        Raises:
            RuntimeError: ``OPENAI_API_KEY`` is not configured, so
                transcription cannot work under any provider choice.
        """
        if hasattr(self._llm_provider, "transcribe"):
            return self._llm_provider
        if self._dedicated_transcription_provider is None:
            self._dedicated_transcription_provider = OpenAIClientProvider()
        if not self._dedicated_transcription_provider.is_configured:
            raise RuntimeError("Transcription requires OPENAI_API_KEY to be configured.")
        return self._dedicated_transcription_provider

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
        duration of the upload and transcription. Always uses OpenAI's
        speech-to-text API regardless of the active chat ``LLM_PROVIDER``
        (see :meth:`_transcription_provider`).

        Args:
            audio_bytes: Raw audio file content.
            filename: Original filename; its extension hints the audio
                format to the API.
            content_type: MIME type reported by the client.

        Returns:
            The transcribed text.

        Raises:
            RuntimeError: ``OPENAI_API_KEY`` is not configured.
            openai.APITimeoutError, openai.RateLimitError, Exception: propagated
                from the API call so callers can map them to user-facing text.
        """
        provider = self._transcription_provider()
        logger.info("Transcribing audio upload %s (%d bytes)", filename, len(audio_bytes))
        text = await asyncio.to_thread(provider.transcribe, audio_bytes, filename, content_type)
        logger.debug("Transcription complete: %d chars", len(text))
        return text

    # ------------------------------------------------------------------
    # Action engine (tool-calling)
    # ------------------------------------------------------------------

    def _tool_calling_provider(self) -> OpenAIClientProvider:
        """
        Return an OpenAI provider for tool-calling, regardless of ``LLM_PROVIDER``.

        Tool-calling is only implemented against OpenAI's API today (see
        ``base_llm_provider.py``). When the active chat provider already is
        an ``OpenAIClientProvider`` it is reused directly; otherwise a
        dedicated instance is built lazily so choosing Anthropic or Gemini
        for chat doesn't force an unrelated OpenAI client to also be
        constructed up front.

        Raises:
            RuntimeError: ``OPENAI_API_KEY`` is not configured, so
                tool-calling cannot work under any provider choice.
        """
        if hasattr(self._llm_provider, "complete_with_tools_async"):
            return self._llm_provider
        if self._dedicated_tool_calling_provider is None:
            self._dedicated_tool_calling_provider = OpenAIClientProvider()
        if not self._dedicated_tool_calling_provider.is_configured:
            raise RuntimeError("Tool-calling requires OPENAI_API_KEY to be configured.")
        return self._dedicated_tool_calling_provider

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
            Exception: propagated from the active provider's API call so
                callers can map it to user-facing text via :meth:`_map_api_error`.
        """
        cache_key = ResponseCache.build_key(query, context, history)
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug("Cache hit for query %s", self._query_id(query))
            return cached, True

        messages = self._build_messages(query, context, history)
        response_text = self._llm_provider.complete(messages)
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
        response_text = await self._llm_provider.complete_async(messages)
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
    def _classify_error(exc: Exception) -> str:
        """
        Categorize a provider SDK exception without depending on any one
        SDK's exception hierarchy, so OpenAI, Anthropic and Gemini errors
        are all mapped to the same set of user-facing categories.

        Returns:
            One of ``"timeout"``, ``"rate_limit"``, ``"connection"``,
            ``"status"`` or ``"generic"``.
        """
        if isinstance(exc, (ConnectionResetError, OSError)):
            return "connection"
        exc_name = type(exc).__name__
        status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
        if "Timeout" in exc_name:
            return "timeout"
        if "RateLimit" in exc_name or status_code == 429:
            return "rate_limit"
        if "Connection" in exc_name:
            return "connection"
        if status_code is not None:
            return "status"
        return "generic"

    @staticmethod
    def _map_api_error(exc: Exception) -> str:
        """Translate a provider SDK exception into user-facing text."""
        category = ChatbotService._classify_error(exc)
        if category == "timeout":
            return TIMEOUT_MESSAGE
        if category == "rate_limit":
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
            "answer": None,
            "citations": [],
            "success": False,
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
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Stream an answer as JSON events, replaying conversation history.

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
            ``{"type": "delta", "answer": {"text": ...}}`` events as the
            answer is generated, followed by one ``{"type": "final", ...}``
            event carrying confidence and citations, or a single
            ``{"type": "error", "message": ...}`` event when generation fails.
        """
        if not self.api_available:
            yield self._responses.stream_error_event("Chat service unavailable.")
            return

        if Config.LLM.TOOL_CALLING_ENABLED():
            intent = await self._intent_router.classify(query, history)
            if intent == IntentType.ACTION:
                try:
                    tool_provider = self._tool_calling_provider()
                except RuntimeError as exc:
                    logger.warning(
                        "Tool-calling unavailable (%s); falling back to RAG for this turn", exc
                    )
                else:
                    agent = ToolCallingAgent(tool_provider, self._tool_registry, self.query_rewriter)
                    async for delta in agent.stream(query, history):
                        yield self._responses.stream_delta_event(delta)
                    yield {"type": "final", "answer": {"text": ""}, "citations": []}
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
                yield self._responses.stream_delta_event(cached_text)
                yield self._responses.stream_final_event(
                    cached_text, confidence, search_results, cached=True
                )
                return

            messages = self._build_messages(query, context, history)
            async for delta in self._llm_provider.stream(messages):
                chunks.append(delta)
                yield self._responses.stream_delta_event(delta)
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
            yield self._responses.stream_final_event(
                response_text, confidence, search_results, cached=False
            )
        except Exception as exc:
            logger.exception("Error during streaming")
            record_failure(str(exc))
            category = self._classify_error(exc)
            if category == "timeout":
                yield self._responses.stream_error_event(
                    "Request timeout - the AI service took too long to respond."
                )
            elif category == "connection":
                yield self._responses.stream_error_event(
                    f"Connection error: Could not reach the AI service. {exc}"
                )
            elif category in ("status", "rate_limit"):
                yield self._responses.stream_error_event(f"API error: {exc}")
            else:
                yield self._responses.stream_error_event(str(exc))
