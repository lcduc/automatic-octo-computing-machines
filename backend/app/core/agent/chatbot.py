"""
Chat pipeline: decides how one user message is answered and streams the answer as events.

Order of work, cheapest first, so tokens are only spent when they can help:

1. Staff takeover, guardrails (rules + free moderation) and sensitive topics.
2. Embedding router: small talk, handoff requests, off-topic and vague messages get canned replies.
3. Intent router: action requests go to the tool-calling agent.
4. Everything else is answered from the knowledge base by :class:`KnowledgeAnswerer`.

The pipeline knows nothing about HTTP or the database; ``ChatService``
persists what it yields.
"""

# Standard library imports
import asyncio
import logging
from typing import AsyncIterator, Dict, List, Optional

# Local imports
from app.config.settings import Config
from app.core.guardrails.input_guard import GuardAction, InputGuard
from app.core.guardrails.topic_matcher import matching_topic
from app.core.retrieval.knowledge_index import KnowledgeIndex
from app.core.retrieval.retriever import ContextRetriever
from app.core.routing.embedding_router import EmbeddingRouter, RouteDecision, RouteIntent
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
from app.models.intent import IntentType
from app.models.turn_trace import (
    ROUTE_CLARIFY,
    ROUTE_GUARD,
    ROUTE_HUMAN,
    ROUTE_LOGIN,
    ROUTE_OFF_TOPIC,
    ROUTE_SMALLTALK,
    ROUTE_STAFF,
    ROUTE_TOOL,
    ROUTE_TOPIC,
)
from app.utils.text_utils import TextUtils
from .base_llm_provider import BaseLLMProvider
from .history import recent_history
from .intent_router import IntentRouter
from .knowledge_answerer import KnowledgeAnswerer
from .prompts import AutoReplies
from .response_cache import ResponseCache
from .tool_calling_agent import ToolCallingAgent
from .turn_deadline import TurnDeadline

logger = logging.getLogger(__name__)

#: Usage purposes recorded with token usage.
PURPOSE_INTENT = "intent"
PURPOSE_TOOL = "tool"


class ChatbotService:
    """
    Stateless-per-turn router shared by all requests.

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
        router: Optional[EmbeddingRouter] = None,
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
            router: Embedding router for small talk, handoff requests, off-topic and vague
                messages; ``None`` sends everything the guard allows to retrieval.
        """
        self._guard = guard
        self._cache = cache
        self._intent_router = intent_router
        self._tool_agent = tool_agent
        self._router = router
        self._answerer = KnowledgeAnswerer(llm_provider, retriever, index, cache)

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
        deadline = TurnDeadline.after(Config.LLM.TURN_TIMEOUT_SECONDS())
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
    # Routing
    # ------------------------------------------------------------------

    async def _run(self, request: TurnRequest, deadline: TurnDeadline) -> AsyncIterator[TurnEvent]:
        """Route the message to a canned reply, the tool agent or the knowledge base; exceptions are mapped by :meth:`run`."""
        policy = request.policy
        chat_model = or_default(policy.chat_model, Config.LLM.ACTIVE_MODEL)
        light_model = or_default(policy.light_model, Config.LLM.ACTIVE_LIGHT_MODEL)
        history = recent_history(request.history, Config.Chat.MAX_HISTORY_TURNS() * 2)
        trace = request.trace

        if request.staff_active:
            trace.route = ROUTE_STAFF
            yield TurnResult(TurnOutcome.HANDOFF, AutoReplies.STAFF_ACTIVE)
            return

        with trace.step("guard"):
            verdict = self._guard.classify_rules(request.query)
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
            trace.route = ROUTE_HUMAN
            yield self._human_request(policy)
            return

        # Routing and search read chat shorthands written out ("có dc ko" -> "có được không"); the
        # answer prompt keeps the visitor's own words.
        search_text = TextUtils.expand_chat_abbreviations(request.query)
        decision: Optional[RouteDecision] = None
        if self._router is not None:
            with trace.step("router"):
                decision = await asyncio.to_thread(self._router.classify, search_text)
            early = self._route_reply(decision, request, history)
            if early is not None:
                yield early
                return

        # Moderation is a network call: it overlaps routing, rewrite and retrieval, and is only
        # awaited right before an answer is generated. Canned replies above never pay for it.
        # ceiling: an un-awaited call still completes in the background on paths that need no answer.
        moderation = asyncio.create_task(self._guard.is_flagged(request.query)) if self._guard.moderates else None

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
                blocked = await self._moderation_block(moderation, request)
                if blocked is not None:
                    yield blocked
                    return
                async for event in self._run_tool_agent(request, history, deadline, chat_model, light_model):
                    yield event
                return

        async for event in self._answerer.answer(
            request,
            history=history,
            search_text=search_text,
            decision=decision,
            deadline=deadline,
            chat_model=chat_model,
            light_model=light_model,
            before_generation=lambda: self._moderation_block(moderation, request),
        ):
            yield event

    async def _run_tool_agent(
        self, request: TurnRequest, history: List[Dict[str, str]], deadline: TurnDeadline, chat_model: str, light_model: str
    ) -> AsyncIterator[TurnEvent]:
        """Answer an action request through the tool-calling agent (never cached: results may be private)."""
        pieces: List[str] = []
        tool_failed = False
        # The tool agent always answers through OpenAI, so an admin-chosen chat model (which may be
        # another provider's) is not passed; its query rewrite runs on the chat provider's light model.
        stream = self._tool_agent.stream(request.query, history, light_model=light_model, context=request.context)
        async for delta in deadline.guard(stream):
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

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _moderation_block(moderation: Optional["asyncio.Task[bool]"], request: TurnRequest) -> Optional[TurnResult]:
        """Wait for the moderation verdict; the blocked reply when the message was flagged, else ``None``."""
        if moderation is None:
            return None
        with request.trace.step("moderation"):
            flagged = await moderation
        if not flagged:
            return None
        logger.info("Message flagged by moderation")
        request.trace.route = ROUTE_GUARD
        return TurnResult(TurnOutcome.BLOCKED, request.policy.guard_block_message, guard_reason="moderation_flagged")

    @staticmethod
    def _human_request(policy: ChatPolicy) -> TurnResult:
        """
        Reply to an explicit ask for a person. It is never a knowledge question: with handoff
        off, say so instead of searching and replying "no information".
        """
        if policy.fallback_mode == FALLBACK_MODE_HANDOFF:
            return TurnResult(TurnOutcome.HANDOFF, policy.handoff_message, handoff_reason=HandoffReason.USER_REQUEST)
        return TurnResult(TurnOutcome.DENIED, AutoReplies.HUMAN_UNAVAILABLE)

    def _route_reply(
        self, decision: RouteDecision, request: TurnRequest, history: List[Dict[str, str]]
    ) -> Optional[TurnResult]:
        """
        The canned reply for a message the router is sure about, or ``None`` to carry on to retrieval.

        A vague opener ("cho em hỏi") gets one clarifying question; the next vague message goes to staff.
        Vagueness is only judged at the start of a conversation or right after our question, because
        a short follow-up ("khoảng bao nhiêu một tháng?") is meaningful given the history.
        """
        policy, trace = request.policy, request.trace
        intent = decision.intent
        if intent == RouteIntent.GREETING:
            trace.route = ROUTE_SMALLTALK
            return TurnResult(TurnOutcome.SMALLTALK, policy.greeting_message)
        if intent == RouteIntent.THANKS:
            trace.route = ROUTE_SMALLTALK
            return TurnResult(TurnOutcome.SMALLTALK, policy.thanks_message)
        if intent == RouteIntent.HANDOFF_REQUEST:
            trace.route = ROUTE_HUMAN
            return self._human_request(policy)
        if intent == RouteIntent.OFF_TOPIC:
            trace.route = ROUTE_OFF_TOPIC
            return TurnResult(TurnOutcome.DENIED, AutoReplies.OFF_TOPIC)
        if intent == RouteIntent.AMBIGUOUS:
            # ceiling: the previous clarification is recognised by its fixed text; add a CLARIFY
            # outcome if admins need to see clarifications as their own outcome.
            asked_already = bool(history) and history[-1].get("content") == AutoReplies.CLARIFY
            if history and not asked_already:
                return None
            trace.route = ROUTE_CLARIFY
            if not asked_already:
                return TurnResult(TurnOutcome.SMALLTALK, AutoReplies.CLARIFY)
            if policy.fallback_mode == FALLBACK_MODE_HANDOFF:
                return TurnResult(
                    TurnOutcome.HANDOFF, policy.handoff_message, handoff_reason=HandoffReason.AMBIGUOUS_REPEATED
                )
            return TurnResult(TurnOutcome.DENIED, policy.deny_message)
        return None

    @staticmethod
    def _is_rate_limit(exc: Exception) -> bool:
        """True for provider 429 errors, regardless of which SDK raised them."""
        status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
        return "RateLimit" in type(exc).__name__ or status == 429
