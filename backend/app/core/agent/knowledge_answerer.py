"""
Answers a question from the knowledge base: rewrite, retrieve, then a grounded, cited answer.

Cheapest first, so tokens are only spent when they can help:

1. Query rewrite with history (light model) and hybrid retrieval.
2. No relevant knowledge -> configured fallback (deny text or handoff), no LLM call.
3. Answer cache.
4. Grounded answer streamed from the LLM, then confidence and citations.
"""

# Standard library imports
import asyncio
import hashlib
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import AsyncIterator, Awaitable, Callable, Dict, List, Optional, Sequence

# Local imports
from app.config.settings import Config
from app.core.document_processing.chunking.chunker import section_label
from app.core.retrieval.context_assembler import ContextAssembler
from app.core.retrieval.knowledge_index import KnowledgeIndex
from app.core.retrieval.retriever import ContextRetriever
from app.core.routing.embedding_router import RouteDecision
from app.models.chat_turn import (
    FALLBACK_MODE_HANDOFF,
    ChatPolicy,
    HandoffReason,
    TurnDelta,
    TurnEvent,
    TurnOutcome,
    TurnRequest,
    TurnResult,
    TurnUsage,
    or_default,
)
from app.models.knowledge import RetrievalResults, RetrievedChunk
from app.models.tool_context import ToolContext
from app.models.turn_trace import ROUTE_CACHE, ROUTE_FALLBACK, ROUTE_OFF_TOPIC, ROUTE_RAG, TurnTrace
from .answer_marker import NoAnswerFilter
from .base_llm_provider import BaseLLMProvider
from .confidence import ConfidenceScorer
from .prompts import AutoReplies, PromptManager, SystemPrompts
from .query_rewriter import QueryRewriter
from .response_cache import ResponseCache
from .turn_deadline import TurnDeadline

logger = logging.getLogger(__name__)

#: Usage purposes recorded with token usage.
PURPOSE_ANSWER = "answer"
PURPOSE_REWRITE = "rewrite"

#: Checked right before the answer is generated; a result ends the turn instead.
GenerationGate = Callable[[], Awaitable[Optional[TurnResult]]]


class KnowledgeAnswerer:
    """
    The knowledge-base path of a chat turn, shared by all requests.

    Heavy collaborators (provider client, retriever, index) are injected and
    shared; per-turn state lives only in local variables of :meth:`answer`.
    """

    def __init__(
        self, llm_provider: BaseLLMProvider, retriever: ContextRetriever, index: KnowledgeIndex, cache: ResponseCache
    ):
        """
        Args:
            llm_provider: Active chat-completion provider.
            retriever: Hybrid retriever over the knowledge snapshot.
            index: Source of the current knowledge snapshot.
            cache: Answer cache.
        """
        self._llm = llm_provider
        self._retriever = retriever
        self._index = index
        self._cache = cache
        self._rewriter = QueryRewriter(llm_provider)
        self._prompts = PromptManager()
        self._assembler = ContextAssembler()
        self._confidence = ConfidenceScorer()
        # Retrieval (embedding + BM25 + cross-encoder) is GPU/CPU-bound; this
        # bounds concurrent runs so a burst cannot exhaust GPU memory.
        self._retrieval_slots = asyncio.Semaphore(Config.RAG.RETRIEVAL_MAX_CONCURRENCY())

    async def answer(
        self,
        request: TurnRequest,
        *,
        history: List[Dict[str, str]],
        search_text: str,
        decision: Optional[RouteDecision],
        deadline: TurnDeadline,
        chat_model: str,
        light_model: str,
        before_generation: GenerationGate,
    ) -> AsyncIterator[TurnEvent]:
        """
        Answer ``request`` from the knowledge base.

        Args:
            request: The turn being answered.
            history: Recent prior messages, oldest first.
            search_text: The query with chat shorthands written out, for rewrite and search.
            decision: The embedding router's verdict, if it ran (judges off-topic misses).
            deadline: The turn's time budget.
            chat_model: Model that writes the answer.
            light_model: Model that rewrites the query.
            before_generation: Awaited before tokens are spent on an answer (moderation);
                a result it returns is yielded instead.

        Yields:
            ``TurnDelta`` text pieces, ``TurnUsage`` records and exactly one ``TurnResult``.
        """
        trace = request.trace
        trace.route = ROUTE_RAG
        with trace.step("rewrite"):
            search_query, rewrite_usage = await self._rewriter.rewrite(search_text, history, light_model)
        if rewrite_usage is not None:
            yield TurnUsage(PURPOSE_REWRITE, rewrite_usage)
        rewritten = search_query if search_query != search_text else None

        with trace.step("retrieval"):
            results = await self._retrieve(search_query, request.sources, request.policy, deadline, request.context, trace)
            matched = [item for item in results if item.matched]
            if not matched and rewritten is not None:
                # A bad rewrite (e.g. the light model replied instead of rewriting) must not
                # hide knowledge the user's own words would find.
                logger.info("Rewritten query matched nothing; retrying retrieval with the original query")
                results = await self._retrieve(search_text, request.sources, request.policy, deadline, request.context, trace)
                matched = [item for item in results if item.matched]
                if matched:
                    rewritten = None
        trace.record_chunks(results)
        if not matched:
            yield self._unanswered(request, decision, rewritten, results.best_rerank)
            return

        documents_block = self._assembler.build(results, Config.LLM.MAX_CONTEXT_LENGTH())
        system_prompt = self._prompts.get_system_prompt(request.policy.assistant_instructions)
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

        blocked = await before_generation()
        if blocked is not None:
            yield blocked
            return

        messages = [
            {"role": "system", "content": system_prompt},
            *history,
            {"role": "user", "content": self._prompts.build_user_turn(request.query, documents_block)},
        ]
        pieces: List[str] = []
        no_answer = NoAnswerFilter()
        with trace.step("generation"):
            async for delta in deadline.guard(self._llm.stream(messages, model=chat_model)):
                if delta.usage is not None:
                    yield TurnUsage(PURPOSE_ANSWER, delta.usage)
                shown = no_answer.feed(delta.text) if delta.text else ""
                if shown:
                    pieces.append(shown)
                    yield TurnDelta(shown)
            tail = no_answer.finish()
            if tail:
                pieces.append(tail)
                yield TurnDelta(tail)

        answer = "".join(pieces).strip()
        if no_answer.no_answer or SystemPrompts.NO_ANSWER_MARKER in answer:
            # The documents did not answer the question: staff take it, nothing hedged is shown.
            logger.info("The model found no answer in the retrieved documents")
            yield self._unanswered(request, decision, rewritten, results.best_rerank)
            return
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

    async def _retrieve(
        self,
        query: str,
        sources: Optional[Sequence[str]],
        policy: ChatPolicy,
        deadline: TurnDeadline,
        context: ToolContext,
        trace: Optional[TurnTrace] = None,
    ) -> RetrievalResults:
        """
        Run hybrid search in a worker thread, bounded by the retrieval slots and the deadline.

        Tuning comes from the turn's policy (admin-editable), falling back to the env defaults.
        The filters in force are noted on ``trace`` (ADM-05).
        """
        snapshot = self._index.snapshot
        top_k = or_default(policy.retrieval_top_k, Config.RAG.RETRIEVAL_TOP_K)
        threshold = Config.RAG.SIMILARITY_THRESHOLD()
        semantic_threshold = Config.RAG.SEMANTIC_THRESHOLD()
        today = datetime.now(ZoneInfo(Config.Server.APP_TIMEZONE())).date()
        if trace is not None:
            trace.filters = {
                "access_level": context.tier_level, "today": today.isoformat(), "sources": list(sources) if sources else None,
                "threshold": threshold, "semantic_threshold": semantic_threshold, "top_k": top_k,
                "knowledge_version": snapshot.version,
            }
        if snapshot.is_empty:
            return RetrievalResults()
        async with self._retrieval_slots:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    self._retriever.search,
                    query,
                    snapshot,
                    top_k=top_k,
                    semantic_weight=or_default(policy.semantic_weight, Config.RAG.SEMANTIC_WEIGHT),
                    threshold=threshold,
                    semantic_threshold=semantic_threshold,
                    max_context_chunks=or_default(policy.max_context_chunks, Config.RAG.MAX_CONTEXT_CHUNKS),
                    expansion_radius=Config.RAG.CONTEXT_EXPANSION_RADIUS(),
                    sources=sources,
                    access_level=context.tier_level,
                    today=today,
                ),
                timeout=deadline.remaining(),
            )

    def _unanswered(
        self, request: TurnRequest, decision: Optional[RouteDecision], rewritten: Optional[str],
        best_rerank: Optional[float],
    ) -> TurnResult:
        """
        Reply when nothing in the knowledge base answers the question.

        A message that is off topic (see :meth:`RouteDecision.is_off_topic`) is refused and opens no
        ticket; anything else is on topic, so it takes the configured fallback (handoff or deny).
        """
        if decision is not None and decision.is_off_topic(best_rerank):
            request.trace.route = ROUTE_OFF_TOPIC
            return TurnResult(TurnOutcome.DENIED, AutoReplies.OFF_TOPIC, rewritten_query=rewritten)
        request.trace.route = ROUTE_FALLBACK
        return self._fallback(request, rewritten)

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
