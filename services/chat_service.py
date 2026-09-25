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
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence, Set

# Local imports
from config.settings import Config
from core.agent.chatbot import ChatbotService
from core.agent.prompts import AutoReplies
from core.guardrails.pii_redactor import PiiRedactor
from core.storage.conversation_repository import ConversationRepository
from core.storage.database import Database
from core.storage.tables.base import utc_now
from core.storage.tables.conversation_tables import Conversation, Message, TokenUsage
from models.caller import ChatCaller
from models.chat_turn import TurnDelta, TurnOutcome, TurnRequest, TurnResult, TurnUsage
from .errors import NotFoundError, RateLimitedError, ServiceUnavailableError
from .handoff_service import HandoffService
from .rate_limit_service import RateLimitService
from .settings_service import SettingsService
from .usage_service import UsageService

logger = logging.getLogger(__name__)

#: Shown when a visitor exhausted today's token budget.
#: ``Retry-After`` for an exhausted daily budget (the client just needs to stop retrying).
BUDGET_RETRY_AFTER_SECONDS = 3600
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


class ChatService:
    """Runs chat turns for authenticated callers and records their results."""

    def __init__(
        self,
        database: Database,
        pipeline: ChatbotService,
        settings: SettingsService,
        usage: UsageService,
        handoffs: HandoffService,
        rate_limiter: RateLimitService,
        redactor: Optional[PiiRedactor],
    ):
        """
        Args:
            database: Connected database.
            pipeline: The RAG chat pipeline.
            settings: Runtime chat policy.
            usage: Token budgets and the live feed.
            handoffs: Creates handoff requests.
            rate_limiter: Per-user / per-IP request limiter.
            redactor: PII redactor, or ``None`` when redaction is disabled.
        """
        self._database = database
        self._pipeline = pipeline
        self._settings = settings
        self._usage = usage
        self._handoffs = handoffs
        self._rate_limiter = rate_limiter
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
            RateLimitedError: Too many requests or today's token budget used up.
            ServiceUnavailableError: Every generation slot is busy.
            NotFoundError: ``conversation_id`` does not belong to this visitor.
        """
        retry_after = self._rate_limiter.hit(f"user:{caller.end_user_id}", Config.Security.RATE_LIMIT_USER_PER_MINUTE())
        if retry_after is not None:
            raise RateLimitedError(AutoReplies.RATE_LIMITED, retry_after)
        if not await self._usage.within_budget(caller.end_user_id):
            raise RateLimitedError(AutoReplies.BUDGET_EXCEEDED, BUDGET_RETRY_AFTER_SECONDS)
        if self._slots.locked():
            raise ServiceUnavailableError("Hệ thống đang bận, vui lòng thử lại sau giây lát.")

        redacted = self._redact(message.strip())
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

        history = [{"role": row.role, "content": row.content} for row in history_rows]
        request = TurnRequest(query=redacted, history=history, policy=self._settings.chat_policy(), sources=sources)
        return PreparedTurn(caller, conversation.id, uuid.uuid4(), request, time.perf_counter())

    @staticmethod
    async def _resolve_conversation(
        repository: ConversationRepository, caller: ChatCaller, conversation_id: Optional[uuid.UUID]
    ) -> Conversation:
        """Load the visitor's conversation or start a new one."""
        if conversation_id is not None:
            conversation = await repository.get_conversation(conversation_id)
            if conversation is None or conversation.end_user_id != caller.end_user_id:
                raise NotFoundError("Conversation not found")
            return conversation
        conversation = Conversation(api_key_id=caller.api_key_id, end_user_id=caller.end_user_id)
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
            handoff_id = await self._persist(turn, result)
            yield {
                "type": "done",
                "outcome": result.outcome.value,
                # Canned replies (deny/handoff/blocked) arrive only here, never as deltas.
                "text": result.text,
                "citations": result.citations,
                "confidence": result.confidence,
                "cached": result.cached,
                "handoff_id": handoff_id,
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

    def _persist_in_background(self, turn: PreparedTurn, result: TurnResult) -> None:
        """Save an interrupted turn without awaiting (the request task is being cancelled)."""
        task = asyncio.create_task(self._persist(turn, result))
        self._pending_writes.add(task)
        task.add_done_callback(self._pending_writes.discard)

    async def _persist(self, turn: PreparedTurn, result: TurnResult) -> Optional[str]:
        """
        Store the assistant message, token usage and handoff in one transaction.

        Returns:
            The new handoff request id, if one was opened.
        """
        prompt_tokens = sum(item.usage.prompt_tokens for item in turn.usages)
        completion_tokens = sum(item.usage.completion_tokens for item in turn.usages)
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
                        )
                        for item in turn.usages
                    ]
                )
                if conversation is not None:
                    conversation.message_count += 1
                    conversation.last_activity_at = utc_now()
                    if result.handoff_reason is not None:
                        handoff = self._handoffs.open_request(
                            repository, conversation, turn.assistant_message_id, result.handoff_reason.value
                        )
                        await repository.flush()
        except Exception:
            logger.exception("Failed to persist chat turn %s", turn.assistant_message_id)
            return None

        self._usage.add(turn.caller.end_user_id, prompt_tokens + completion_tokens)
        self._usage.publish(
            {
                "type": "turn",
                "conversation_id": str(turn.conversation_id),
                "message_id": str(turn.assistant_message_id),
                "outcome": result.outcome.value,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "latency_ms": latency_ms,
                "model": result.model,
            }
        )
        if handoff is not None:
            self._handoffs.notify(handoff)
            return str(handoff.id)
        return None

    async def wait_for_pending_writes(self) -> None:
        """Await background persistence of interrupted turns (shutdown and tests)."""
        if self._pending_writes:
            await asyncio.gather(*self._pending_writes, return_exceptions=True)
