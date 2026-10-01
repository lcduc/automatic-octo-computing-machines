"""
One chat turn end to end: quotas, redaction, conversation state, the pipeline
and persistence of everything the turn produced.
"""

# Standard library imports
import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence, Set, Tuple

# Local imports
from config.settings import Config
from core.agent.chatbot import ChatbotService
from core.agent.prompts import AutoReplies
from core.guardrails.pii_redactor import PiiRedactor
from core.storage.conversation_repository import ConversationRepository
from core.storage.database import Database
from core.storage.tables.base import utc_now
from core.storage.tables.conversation_tables import (
    CONVERSATION_STATUS_STAFF_ACTIVE,
    HANDOFF_ACTIVE_STATUSES,
    Conversation,
    HandoffRequest,
    Message,
    TokenUsage,
)
from core.storage.tables.observability_tables import MessageTrace
from models.caller import ChatCaller
from models.chat_turn import FALLBACK_MODE_HANDOFF, HandoffReason, TurnDelta, TurnOutcome, TurnRequest, TurnResult, TurnUsage
from models.tool_context import ToolContext
from utils.text_utils import TextUtils
from .errors import NotFoundError, RateLimitedError, ServiceUnavailableError
from .handoff_service import HandoffService
from .live_feed_service import LiveFeedService
from .pricing_service import PricingService
from .settings_service import SettingsService
from .usage_service import BudgetVerdict, UsageService

logger = logging.getLogger(__name__)

#: Outcome stored when the visitor disconnected before the answer finished.
ABORTED_GUARD_REASON = "client_disconnected"


@dataclass
class PreparedTurn:
    """A validated turn whose user message is already stored."""

    caller: ChatCaller
    conversation_id: uuid.UUID
    assistant_message_id: uuid.UUID
    request: TurnRequest
    started_at: float
    usages: List[TurnUsage] = field(default_factory=list)
    #: The conversation's previous answer (outcome, confidence), for the repeated-no-answer trigger.
    previous_answer: Optional[Tuple[Optional[str], Optional[float]]] = None


#: Answers below this confidence count as unhelpful for the repeated-no-answer trigger.
LOW_CONFIDENCE = 0.35


def _unhelpful(outcome: Optional[str], confidence: Optional[float]) -> bool:
    """Out of scope, or an answer the confidence scorer doubts."""
    if outcome == TurnOutcome.BLOCKED.value:
        return True
    return outcome == TurnOutcome.ANSWERED.value and confidence is not None and confidence < LOW_CONFIDENCE


class ChatService:
    """Runs chat turns for authenticated callers and records their results."""

    def __init__(
        self,
        database: Database,
        pipeline: ChatbotService,
        settings: SettingsService,
        usage: UsageService,
        handoffs: HandoffService,
        pricing: PricingService,
        live_feed: LiveFeedService,
        redactor: Optional[PiiRedactor],
    ):
        """
        Args:
            database: Connected database.
            pipeline: The RAG chat pipeline.
            settings: Runtime chat and usage policy.
            usage: Request limits, token budgets and the spend cap.
            handoffs: Creates handoff requests.
            pricing: Model prices (cost of each recorded call).
            live_feed: Admin dashboards' live feed.
            redactor: PII redactor, or ``None`` when redaction is disabled.
        """
        self._database = database
        self._pipeline = pipeline
        self._settings = settings
        self._usage = usage
        self._handoffs = handoffs
        self._pricing = pricing
        self._live_feed = live_feed
        self._redactor = redactor
        self._slots = asyncio.Semaphore(Config.Security.MAX_CONCURRENT_CHATS())
        self._pending_writes: Set[asyncio.Task] = set()

    # ------------------------------------------------------------------
    # Turn preparation
    # ------------------------------------------------------------------

    def _redact(self, text: str) -> str:
        """Mask personal data when redaction is enabled."""
        return self._redactor.redact(text).text if self._redactor is not None else text

    async def prepare(
        self,
        caller: ChatCaller,
        message: str,
        conversation_id: Optional[uuid.UUID],
        sources: Optional[Sequence[str]],
    ) -> PreparedTurn:
        """
        Check quotas, resolve the conversation and store the user's message.

        Raises:
            RateLimitedError: Too many messages, a used-up daily token budget
                (the caller's or their IP's), or the monthly spend cap.
            ServiceUnavailableError: Every generation slot is busy.
            NotFoundError: ``conversation_id`` does not belong to this visitor.
        """
        policy = self._settings.usage_policy()
        retry_after = await self._usage.hit_request_limits(caller, policy)
        if retry_after is not None:
            raise RateLimitedError(AutoReplies.RATE_LIMITED, retry_after)
        verdict = await self._usage.budget_verdict(caller, policy)
        if verdict == BudgetVerdict.TOKENS_EXHAUSTED:
            raise RateLimitedError(AutoReplies.BUDGET_EXCEEDED, self._usage.seconds_until(verdict))
        if verdict == BudgetVerdict.SPEND_PAUSED:
            message = AutoReplies.SPEND_PAUSED if caller.logged_in else AutoReplies.SPEND_PAUSED_ANONYMOUS
            raise RateLimitedError(message, self._usage.seconds_until(verdict))
        if self._slots.locked():
            raise ServiceUnavailableError("Hệ thống đang bận, vui lòng thử lại sau giây lát.")

        redacted = self._redact(TextUtils.normalize_chat_text(message))
        history_limit = Config.Chat.MAX_HISTORY_TURNS() * 2
        async with self._database.session() as session:
            repository = ConversationRepository(session)
            conversation = await self._resolve_conversation(repository, caller, conversation_id)
            history_rows = await repository.recent_messages(conversation.id, history_limit) if conversation_id else []
            repository.add(
                Message(conversation_id=conversation.id, role="user", content=redacted, request_id=caller.request_id)
            )
            conversation.message_count += 1
            conversation.last_activity_at = utc_now()
            staff_active = conversation.status == CONVERSATION_STATUS_STAFF_ACTIVE

        # The outcome lets ``recent_history`` drop failed turns' apologies.
        history = [{"role": row.role, "content": row.content, "outcome": row.outcome} for row in history_rows]
        answers = [row for row in history_rows if row.role == "assistant"]
        previous_answer = (answers[-1].outcome, answers[-1].confidence) if answers else None
        request = TurnRequest(
            query=redacted,
            history=history,
            policy=self._settings.chat_policy(),
            sources=sources,
            context=ToolContext(user_id=caller.user_id, tier_level=caller.tier_level),
            staff_active=staff_active,
        )
        return PreparedTurn(caller, conversation.id, uuid.uuid4(), request, time.perf_counter(),
                            previous_answer=previous_answer)

    @staticmethod
    async def _resolve_conversation(
        repository: ConversationRepository, caller: ChatCaller, conversation_id: Optional[uuid.UUID]
    ) -> Conversation:
        """
        Load the caller's conversation or start a new one.

        A visitor who logs in mid-conversation keeps it: the first logged-in
        turn attaches it to their user id (ID-08), after which only that user
        can continue or read it.
        """
        if conversation_id is not None:
            conversation = await repository.get_conversation(conversation_id)
            if conversation is None or not caller.owns(conversation.user_id, conversation.end_user_id):
                raise NotFoundError("Conversation not found")
            if conversation.user_id is None and caller.logged_in:
                conversation.user_id = caller.user_id
                logger.info("Conversation %s attached to its logged-in user", conversation.id)
            return conversation
        conversation = Conversation(
            api_key_id=caller.api_key_id, end_user_id=caller.end_user_id, user_id=caller.user_id
        )
        repository.add(conversation)
        await repository.flush()
        return conversation

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    async def stream(self, turn: PreparedTurn) -> AsyncIterator[Dict[str, Any]]:
        """
        Run the pipeline and yield client events.

        Yields:
            ``meta`` (ids) first, then ``delta`` events, then one ``done``
            event with outcome and citations. The assistant message, token
            usage and any handoff are persisted even if the client disconnects.
        """
        async with self._slots:
            yield {
                "type": "meta",
                "conversation_id": str(turn.conversation_id),
                "message_id": str(turn.assistant_message_id),
            }
            streamed: List[str] = []
            result: Optional[TurnResult] = None
            try:
                async for event in self._pipeline.run(turn.request):
                    if isinstance(event, TurnUsage):
                        turn.usages.append(event)
                    elif isinstance(event, TurnDelta):
                        if not streamed:
                            turn.request.trace.steps_ms["first_token"] = int((time.perf_counter() - turn.started_at) * 1000)
                        streamed.append(event.text)
                        yield {"type": "delta", "text": event.text}
                    else:
                        result = event
            except (asyncio.CancelledError, GeneratorExit):
                partial = TurnResult(TurnOutcome.ERROR, "".join(streamed), guard_reason=ABORTED_GUARD_REASON)
                self._persist_in_background(turn, partial)
                raise

            if result is None:
                logger.error("Chat pipeline ended without a result")
                result = TurnResult(TurnOutcome.ERROR, "".join(streamed), guard_reason="no_result")
            self._escalate_repeated_failure(turn, result)
            handoff = await self._persist(turn, result)
            handoff_id = str(handoff.id) if handoff is not None else None
            yield {
                "type": "done",
                "outcome": result.outcome.value,
                # Canned replies (deny/handoff/blocked) arrive only here, never as deltas.
                "text": result.text,
                "citations": result.citations,
                "confidence": result.confidence,
                "cached": result.cached,
                "handoff_id": handoff_id,
                "reply_expected_by": handoff.due_at.isoformat() if handoff is not None and handoff.due_at else None,
            }

    async def answer(self, turn: PreparedTurn) -> Dict[str, Any]:
        """Non-streaming variant: run the turn and return the ``done`` payload with ids."""
        done: Dict[str, Any] = {}
        meta: Dict[str, Any] = {}
        async for event in self.stream(turn):
            if event["type"] == "meta":
                meta = event
            elif event["type"] == "done":
                done = event
        return {**meta, **done}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    @staticmethod
    def _escalate_repeated_failure(turn: PreparedTurn, result: TurnResult) -> None:
        """
        Offer a human after two unhelpful answers in a row (HND-02): out of scope
        twice, or two answers of low confidence. The answer itself is kept.

        # ceiling: "unhelpful" is outcome + confidence heuristics; replace with a
        # router "unclear/declined" signal once ORC-03 clarifications exist.
        """
        if result.handoff_reason is not None or turn.request.policy.fallback_mode != FALLBACK_MODE_HANDOFF:
            return
        if _unhelpful(result.outcome.value, result.confidence) and turn.previous_answer and _unhelpful(*turn.previous_answer):
            result.handoff_reason = HandoffReason.REPEATED_NO_ANSWER

    def _persist_in_background(self, turn: PreparedTurn, result: TurnResult) -> None:
        """Save an interrupted turn without awaiting (the request task is being cancelled)."""
        task = asyncio.create_task(self._persist(turn, result))
        self._pending_writes.add(task)
        task.add_done_callback(self._pending_writes.discard)

    async def _persist(self, turn: PreparedTurn, result: TurnResult) -> Optional[HandoffRequest]:
        """
        Store the assistant message, token usage and handoff in one transaction.

        Returns:
            The new ticket, if one was opened.
        """
        prompt_tokens = sum(item.usage.prompt_tokens for item in turn.usages)
        completion_tokens = sum(item.usage.completion_tokens for item in turn.usages)
        costs = [
            self._pricing.cost_micro_usd(item.usage.model, item.usage.prompt_tokens, item.usage.completion_tokens)
            for item in turn.usages
        ]
        latency_ms = int((time.perf_counter() - turn.started_at) * 1000)
        handoff = None
        try:
            async with self._database.session() as session:
                repository = ConversationRepository(session)
                conversation = await repository.get_conversation(turn.conversation_id)
                repository.add(
                    Message(
                        id=turn.assistant_message_id,
                        conversation_id=turn.conversation_id,
                        role="assistant",
                        content=self._redact(result.text),
                        outcome=result.outcome.value,
                        cached=result.cached,
                        citations=result.citations,
                        confidence=result.confidence,
                        model=result.model,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        latency_ms=latency_ms,
                        request_id=turn.caller.request_id,
                        guard_reason=result.guard_reason,
                    )
                )
                await repository.flush()
                repository.add(self._trace_row(turn, result))
                repository.add_all(
                    [
                        TokenUsage(
                            conversation_id=turn.conversation_id,
                            message_id=turn.assistant_message_id,
                            end_user_id=turn.caller.end_user_id,
                            purpose=item.purpose,
                            provider=item.usage.provider,
                            model=item.usage.model,
                            prompt_tokens=item.usage.prompt_tokens,
                            completion_tokens=item.usage.completion_tokens,
                            cost_micro_usd=cost,
                            tier=turn.caller.tier,
                        )
                        for item, cost in zip(turn.usages, costs)
                    ]
                )
                if conversation is not None:
                    conversation.message_count += 1
                    conversation.last_activity_at = utc_now()
                    # One ticket in progress per conversation: a later handoff reason is already covered by it.
                    waiting = result.handoff_reason is not None and await repository.active_handoff(
                        turn.conversation_id, HANDOFF_ACTIVE_STATUSES
                    )
                    if waiting:
                        logger.info("Conversation %s already has a ticket in progress", turn.conversation_id)
                    elif result.handoff_reason is not None:
                        handoff = self._handoffs.open_request(
                            repository, conversation, turn.assistant_message_id, result.handoff_reason.value,
                            turn.caller.user_id,
                        )
                        await repository.flush()
        except Exception:
            logger.exception("Failed to persist chat turn %s", turn.assistant_message_id)
            return None

        try:
            await self._usage.record_turn(turn.caller, prompt_tokens + completion_tokens, sum(costs))
        except Exception:
            # The turn is stored; only its budget/spend charge is lost.
            logger.exception("Failed to charge usage of turn %s", turn.assistant_message_id)
        await self._live_feed.publish(
            {
                "type": "turn",
                "conversation_id": str(turn.conversation_id),
                "message_id": str(turn.assistant_message_id),
                "outcome": result.outcome.value,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "latency_ms": latency_ms,
                "model": result.model,
                "cost_micro_usd": sum(costs),
            }
        )
        if handoff is not None:
            await self._handoffs.notify(handoff)
        return handoff

    def _trace_row(self, turn: PreparedTurn, result: TurnResult) -> MessageTrace:
        """The answer's trace (ADM-05); the rewritten query is redacted like the messages."""
        trace = turn.request.trace
        return MessageTrace(
            message_id=turn.assistant_message_id,
            conversation_id=turn.conversation_id,
            route=trace.route,
            intent=trace.intent,
            confidence=result.confidence,
            rewritten_query=self._redact(result.rewritten_query) if result.rewritten_query else None,
            filters=trace.filters,
            chunks=trace.chunks,
            tool_calls=trace.tool_calls_json(),
            prompt_version=trace.prompt_version,
            steps_ms={**trace.steps_ms, "total": int((time.perf_counter() - turn.started_at) * 1000)},
        )

    async def wait_for_pending_writes(self) -> None:
        """Await background persistence of interrupted turns (shutdown and tests)."""
        if self._pending_writes:
            await asyncio.gather(*self._pending_writes, return_exceptions=True)
