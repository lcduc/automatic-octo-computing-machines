"""
RAG chat pipeline: answers one user message as a stream of events.

Order of work, cheapest first, so tokens are only spent when they can help:

1. Guardrails (rules + free moderation): block / small talk / human request.
2. Query rewrite with history (light model) and hybrid retrieval.
3. No relevant knowledge -> configured fallback (deny text or handoff), no LLM call.
4. Answer cache.
5. Grounded answer streamed from the LLM, then confidence and citations.

The pipeline knows nothing about HTTP or the database; ``ChatService``
persists what it yields.
"""

# Standard library imports
import asyncio
import hashlib
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Union

# Local imports
from config.settings import Config
from core.document_processing.chunking.chunker import section_label
from core.guardrails.input_guard import GuardAction, InputGuard
from core.guardrails.topic_matcher import matching_topic
from core.retrieval.context_builder import ContextAssembler
from core.retrieval.knowledge_index import KnowledgeIndex
from core.retrieval.retriever import ContextRetriever
from models.chat_turn import (
    FALLBACK_MODE_HANDOFF,
    ChatPolicy,
    HandoffReason,
    TurnDelta,
    TurnOutcome,
    TurnRequest,
    TurnResult,
    TurnUsage,
)
from models.intent import IntentType
from models.knowledge import RetrievedChunk
from models.llm import StreamDelta
from models.tool_context import ToolContext
from models.turn_trace import (
    ROUTE_CACHE,
    ROUTE_FALLBACK,
    ROUTE_GUARD,
    ROUTE_HUMAN,
    ROUTE_LOGIN,
    ROUTE_RAG,
    ROUTE_SMALLTALK,
    ROUTE_TOOL,
    ROUTE_TOPIC,
)
from .base_llm_provider import BaseLLMProvider
from .confidence import ConfidenceScorer
from .history import recent_history
from .intent_router import IntentRouter
from .prompts import AutoReplies, PromptManager
from .query_rewriter import QueryRewriter
from .response_cache import ResponseCache
from .tool_calling_agent import ToolCallingAgent

logger = logging.getLogger(__name__)

TurnEvent = Union[TurnDelta, TurnUsage, TurnResult]


def _or_default(value, default: Callable[[], Any]):
    """An admin-set policy value, or the env default when none was saved."""
    return default() if value is None else value


#: User-facing failure texts (Vietnamese, like the rest of the conversation).

#: Usage purposes recorded with token usage.
PURPOSE_ANSWER = "answer"
PURPOSE_REWRITE = "rewrite"
PURPOSE_INTENT = "intent"
PURPOSE_TOOL = "tool"


class ChatbotService:
    """
    Stateless-per-turn orchestrator shared by all requests.

    Heavy collaborators (models, provider clients, the index) are injected and
    shared; per-turn state lives only in local variables of :meth:`run`.
    """

    def __init__(
        self,
        llm_provider: BaseLLMProvider,
        retriever: ContextRetriever,
        index: KnowledgeIndex,
        guard: InputGuard,
        cache: ResponseCache,
        intent_router: Optional[IntentRouter] = None,
        tool_agent: Optional[ToolCallingAgent] = None,
    ):
        """
        Args:
            llm_provider: Active chat-completion provider.
            retriever: Hybrid retriever over the knowledge snapshot.
            index: Source of the current knowledge snapshot.
            guard: Input screening.
            cache: Answer cache.
            intent_router: Routes action requests to ``tool_agent``; both
                ``None`` disables tool calling.
            tool_agent: Tool-calling engine.
        """
        self._llm = llm_provider
        self._retriever = retriever
        self._index = index
        self._guard = guard
        self._cache = cache
        self._intent_router = intent_router
        self._tool_agent = tool_agent
        self._rewriter = QueryRewriter(llm_provider)
        self._prompts = PromptManager()
        self._assembler = ContextAssembler()
        self._confidence = ConfidenceScorer()
        # Retrieval (embedding + BM25 + cross-encoder) is GPU/CPU-bound; this
        # bounds concurrent runs so a burst cannot exhaust GPU memory.
        self._retrieval_slots = asyncio.Semaphore(Config.RAG.RETRIEVAL_MAX_CONCURRENCY())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def cache(self) -> ResponseCache:
        """The answer cache (for stats and clearing from the admin web)."""
        return self._cache

    async def run(self, request: TurnRequest) -> AsyncIterator[TurnEvent]:
        """
        Answer one message.

        Yields:
            ``TurnDelta`` text pieces, ``TurnUsage`` records and exactly one
            final ``TurnResult``. Never raises for provider/retrieval failures:
            they end the stream with an ``ERROR`` result carrying a safe message.
        """
        deadline = asyncio.get_running_loop().time() + Config.LLM.TURN_TIMEOUT_SECONDS()
        streamed: List[str] = []
        try:
            async for event in self._run(request, deadline):
                if isinstance(event, TurnDelta):
                    streamed.append(event.text)
                yield event
        except asyncio.TimeoutError:
            logger.warning("Chat turn exceeded %ss", Config.LLM.TURN_TIMEOUT_SECONDS())
            yield TurnResult(TurnOutcome.ERROR, "".join(streamed) or AutoReplies.TIMEOUT, guard_reason="timeout")
        except Exception as exc:
            logger.exception("Chat turn failed")
            message = AutoReplies.BUSY if self._is_rate_limit(exc) else AutoReplies.ERROR
            yield TurnResult(TurnOutcome.ERROR, "".join(streamed) or message, guard_reason="error")

    # ------------------------------------------------------------------
    # Stages
    # ------------------------------------------------------------------

    async def _run(self, request: TurnRequest, deadline: float) -> AsyncIterator[TurnEvent]:
        """The pipeline proper; exceptions are mapped by :meth:`run`."""
        policy = request.policy
        chat_model = _or_default(policy.chat_model, Config.LLM.ACTIVE_MODEL)
        light_model = _or_default(policy.light_model, Config.LLM.ACTIVE_LIGHT_MODEL)
        history = recent_history(request.history, Config.Chat.MAX_HISTORY_TURNS() * 2)
        trace = request.trace

        with trace.step("guard"):
            verdict = await self._guard.check(request.query)
        trace.route = ROUTE_SMALLTALK if verdict.action in (GuardAction.GREETING, GuardAction.THANKS) else ROUTE_GUARD
        if verdict.action == GuardAction.BLOCK:
            logger.info("Message blocked by guardrails (%s)", verdict.reason)
            yield TurnResult(TurnOutcome.BLOCKED, policy.guard_block_message, guard_reason=verdict.reason)
            return
        if verdict.action == GuardAction.GREETING:
            yield TurnResult(TurnOutcome.SMALLTALK, policy.greeting_message)
            return
        if verdict.action == GuardAction.THANKS:
            yield TurnResult(TurnOutcome.SMALLTALK, policy.thanks_message)
            return
        topic = matching_topic(request.query, policy.handoff_topics) if policy.fallback_mode == FALLBACK_MODE_HANDOFF else None
        if topic is not None:
            trace.route = ROUTE_TOPIC
            logger.info("Sensitive topic matched; handing off")
            yield TurnResult(TurnOutcome.HANDOFF, policy.handoff_message, handoff_reason=HandoffReason.SENSITIVE_TOPIC)
            return
        if verdict.action == GuardAction.HUMAN_REQUESTED:
            # An explicit ask for a person is never a knowledge question: with handoff
            # off, say so instead of searching and replying "no information".
            trace.route = ROUTE_HUMAN
            if policy.fallback_mode == FALLBACK_MODE_HANDOFF:
                yield TurnResult(
                    TurnOutcome.HANDOFF, policy.handoff_message, handoff_reason=HandoffReason.USER_REQUEST
                )
            else:
                yield TurnResult(TurnOutcome.DENIED, AutoReplies.HUMAN_UNAVAILABLE)
            return

        if self._intent_router is not None and self._tool_agent is not None:
            with trace.step("intent"):
                intent, intent_usage = await self._intent_router.classify(
                    request.query, history, light_model, request.context
                )
            trace.intent = intent.value
            if intent_usage is not None:
                yield TurnUsage(PURPOSE_INTENT, intent_usage)
            if intent == IntentType.LOGIN_REQUIRED:
                trace.route = ROUTE_LOGIN
                yield TurnResult(TurnOutcome.LOGIN_REQUIRED, AutoReplies.LOGIN_REQUIRED)
                return
            if intent == IntentType.ACTION:
                trace.route = ROUTE_TOOL
                async for event in self._run_tool_agent(request, history, deadline, chat_model, light_model):
                    yield event
                return

        trace.route = ROUTE_RAG
        with trace.step("rewrite"):
            search_query, rewrite_usage = await self._rewriter.rewrite(request.query, history, light_model)
        if rewrite_usage is not None:
            yield TurnUsage(PURPOSE_REWRITE, rewrite_usage)
        rewritten = search_query if search_query != request.query else None

        with trace.step("retrieval"):
            results = await self._retrieve(search_query, request.sources, policy, deadline, request.context, trace)
            matched = [item for item in results if item.matched]
            if not matched and rewritten is not None:
                # A bad rewrite (e.g. the light model replied instead of rewriting) must not
                # hide knowledge the user's own words would find.
                logger.info("Rewritten query matched nothing; retrying retrieval with the original query")
                results = await self._retrieve(request.query, request.sources, policy, deadline, request.context, trace)
                matched = [item for item in results if item.matched]
                if matched:
                    rewritten = None
        trace.record_chunks(results)
        if not matched:
            trace.route = ROUTE_FALLBACK
            yield self._fallback(request, rewritten)
            return

        documents_block = self._assembler.build(results, Config.LLM.MAX_CONTEXT_LENGTH())
        system_prompt = self._prompts.get_system_prompt(policy.assistant_instructions)
        trace.prompt_version = self._prompt_digest(system_prompt)
        cache_key = ResponseCache.build_key(
            request.query, documents_block, history, self._cache_namespace(chat_model, system_prompt)
        )
        citations = self._citations(matched)

        cached_answer = self._cache.get(cache_key)
        if cached_answer is not None:
            trace.route = ROUTE_CACHE
            yield TurnDelta(cached_answer)
            yield TurnResult(
                TurnOutcome.ANSWERED,
                cached_answer,
                citations=citations,
                confidence=self._score(cached_answer, request.query, documents_block, matched),
                cached=True,
                model=chat_model,
                rewritten_query=rewritten,
            )
            return

        messages = [
            {"role": "system", "content": system_prompt},
            *history,
            {"role": "user", "content": self._prompts.build_user_turn(request.query, documents_block)},
        ]
        pieces: List[str] = []
        with trace.step("generation"):
            async for delta in self._with_deadline(self._llm.stream(messages, model=chat_model), deadline):
                if delta.usage is not None:
                    yield TurnUsage(PURPOSE_ANSWER, delta.usage)
                if delta.text:
                    pieces.append(delta.text)
                    yield TurnDelta(delta.text)

        answer = "".join(pieces).strip()
        if not answer:
            # An empty completion (e.g. a provider-side safety block) is no answer.
            trace.route = ROUTE_FALLBACK
            yield self._fallback(request, rewritten)
            return
        self._cache.set(cache_key, answer)
        yield TurnResult(
            TurnOutcome.ANSWERED,
            answer,
            citations=citations,
            confidence=self._score(answer, request.query, documents_block, matched),
            model=chat_model,
            rewritten_query=rewritten,
        )

    async def _run_tool_agent(
        self, request: TurnRequest, history: List[Dict[str, str]], deadline: float, chat_model: str, light_model: str
    ) -> AsyncIterator[TurnEvent]:
        """Answer an action request through the tool-calling agent (never cached: results may be private)."""
        pieces: List[str] = []
        tool_failed = False
        # The tool agent always answers through OpenAI, so an admin-chosen chat model (which may be
        # another provider's) is not passed; its query rewrite runs on the chat provider's light model.
        stream = self._tool_agent.stream(request.query, history, light_model=light_model, context=request.context)
        async for delta in self._with_deadline(stream, deadline):
            tool_failed |= delta.tool_failed
            if delta.tool_call is not None:
                request.trace.tool_calls.append(delta.tool_call)
            if delta.usage is not None:
                yield TurnUsage(PURPOSE_TOOL, delta.usage)
            if delta.text:
                pieces.append(delta.text)
                yield TurnDelta(delta.text)
        handoff = HandoffReason.TOOL_ERROR if tool_failed and request.policy.fallback_mode == FALLBACK_MODE_HANDOFF else None
        yield TurnResult(TurnOutcome.ANSWERED, "".join(pieces).strip(), model=chat_model, handoff_reason=handoff)

    async def _retrieve(
        self, query: str, sources, policy: ChatPolicy, deadline: float, context: ToolContext, trace=None
    ) -> List[RetrievedChunk]:
        """
        Run hybrid search in a worker thread, bounded by the retrieval slots and the deadline.

        Tuning comes from the turn's policy (admin-editable), falling back to the env defaults.
        The filters in force are noted on ``trace`` (ADM-05).
        """
        snapshot = self._index.snapshot
        top_k = _or_default(policy.retrieval_top_k, Config.RAG.RETRIEVAL_TOP_K)
        threshold = _or_default(policy.similarity_threshold, Config.RAG.SIMILARITY_THRESHOLD)
        semantic_threshold = Config.RAG.SEMANTIC_THRESHOLD()
        today = datetime.now(ZoneInfo(Config.Server.APP_TIMEZONE())).date()
        if trace is not None:
            trace.filters = {
                "access_level": context.tier_level, "today": today.isoformat(), "sources": list(sources) if sources else None,
                "threshold": threshold, "semantic_threshold": semantic_threshold, "top_k": top_k,
                "knowledge_version": snapshot.version,
            }
        if snapshot.is_empty:
            return []
        async with self._retrieval_slots:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    self._retriever.search,
                    query,
                    snapshot,
                    top_k=top_k,
                    semantic_weight=_or_default(policy.semantic_weight, Config.RAG.SEMANTIC_WEIGHT),
                    threshold=threshold,
                    semantic_threshold=semantic_threshold,
                    max_context_chunks=_or_default(policy.max_context_chunks, Config.RAG.MAX_CONTEXT_CHUNKS),
                    expansion_radius=Config.RAG.CONTEXT_EXPANSION_RADIUS(),
                    sources=sources,
                    access_level=context.tier_level,
                    today=today,
                ),
                timeout=self._remaining(deadline),
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fallback(request: TurnRequest, rewritten: Optional[str]) -> TurnResult:
        """The configured no-knowledge reply: deny text or a handoff."""
        policy = request.policy
        if policy.fallback_mode == FALLBACK_MODE_HANDOFF:
            return TurnResult(
                TurnOutcome.HANDOFF,
                policy.handoff_message,
                rewritten_query=rewritten,
                handoff_reason=HandoffReason.NO_KNOWLEDGE,
            )
        return TurnResult(TurnOutcome.DENIED, policy.deny_message, rewritten_query=rewritten)

    @staticmethod
    def _prompt_digest(system_prompt: str) -> str:
        """Short, stable id of a system prompt (the trace's prompt version)."""
        return hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()[:16]

    def _cache_namespace(self, model: str, system_prompt: str) -> str:
        """Model + prompt + knowledge version, so a model switch or an edit never serves a stale answer."""
        return f"{model}|{self._prompt_digest(system_prompt)}|kb{self._index.snapshot.version}"

    @staticmethod
    def _citations(matched: List[RetrievedChunk]) -> List[Dict[str, object]]:
        """One citation per matched document, best first."""
        best: Dict[str, RetrievedChunk] = {}
        for item in matched:
            current = best.get(item.chunk.document_id)
            if current is None or item.relevance > current.relevance:
                best[item.chunk.document_id] = item
        ranked = sorted(best.values(), key=lambda item: item.relevance, reverse=True)
        return [
            {
                "document_id": item.chunk.document_id,
                "chunk_id": item.chunk.chunk_id,
                "title": item.chunk.document_title,
                "source": item.chunk.source,
                "url": item.chunk.metadata.get("url"),
                "section": section_label(item.chunk.metadata),
                "score": round(item.relevance, 3),
            }
            for item in ranked
        ]

    def _score(self, answer: str, query: str, context: str, matched: List[RetrievedChunk]) -> Optional[float]:
        """Heuristic answer confidence in [0, 1]; ``None`` if scoring failed."""
        try:
            breakdown = self._confidence.calculate_confidence(
                answer, query, context, [{"combined_score": item.relevance} for item in matched]
            )
            return round(float(breakdown.overall_score), 3)
        except Exception:
            logger.exception("Confidence scoring failed")
            return None

    @staticmethod
    def _remaining(deadline: float) -> float:
        """Seconds left before the turn deadline (raises when already passed)."""
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError()
        return remaining

    async def _with_deadline(self, stream: AsyncIterator[StreamDelta], deadline: float) -> AsyncIterator[StreamDelta]:
        """Re-yield ``stream``, failing with ``TimeoutError`` if the next item misses the deadline."""
        iterator = stream.__aiter__()
        while True:
            try:
                item = await asyncio.wait_for(iterator.__anext__(), timeout=self._remaining(deadline))
            except StopAsyncIteration:
                return
            yield item

    @staticmethod
    def _is_rate_limit(exc: Exception) -> bool:
        """True for provider 429 errors, regardless of which SDK raised them."""
        status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
        return "RateLimit" in type(exc).__name__ or status == 429
