"""Regression tests for turns that went wrong in the widget: a bad query rewrite, a replayed error, a human request."""

import uuid

import numpy as np
import pytest

from core.agent.chatbot import ChatbotService
from core.agent.history import recent_history
from core.agent.prompts import AutoReplies
from core.agent.query_rewriter import QueryRewriter
from core.agent.response_cache import ResponseCache
from core.guardrails.input_guard import InputGuard
from core.retrieval.knowledge_index import KnowledgeSnapshot
from core.retrieval.retriever import ContextRetriever
from core.storage.knowledge_repository import IndexRow
from models.chat_turn import ChatPolicy, TurnOutcome, TurnRequest, TurnResult
from models.llm import LLMResult, StreamDelta

DENY_POLICY = ChatPolicy("deny", "DENY", "HANDOFF", "BLOCKED", "HELLO", "WELCOME")
CV_TEXT = "Lương Chí Đức sinh năm 2004, Kỹ sư AI"
#: What gpt-4.1-nano returned for "answer my question": a reply, not a search query.
BAD_REWRITE = "Bạn có thể vui lòng đặt câu hỏi cụ thể mà bạn muốn tôi trả lời không?"
HISTORY = [
    {"role": "user", "content": "what do you know of luong chi duc", "outcome": None},
    {"role": "assistant", "content": AutoReplies.ERROR, "outcome": "error"},
]


class _Provider:
    """Light model returns ``rewrite``; the answer model streams a fixed answer."""

    name = "stub"

    def __init__(self, rewrite: str = ""):
        self.rewrite = rewrite
        self.rewrite_calls = []
        self.stream_calls = 0

    async def complete_async(self, messages, model=None):
        self.rewrite_calls.append(messages)
        return LLMResult(self.rewrite)

    async def stream(self, messages, model=None):
        self.stream_calls += 1
        yield StreamDelta(text="Lương Chí Đức là Kỹ sư AI.")


class _Embeddings:
    """Only text naming the person lands near the CV chunk."""

    def embed_query(self, query):
        return np.array([1.0, 0.0] if "chi duc" in query.lower() else [0.0, 1.0], dtype=np.float32)


class _Index:
    snapshot = KnowledgeSnapshot.build(
        [IndexRow(uuid.uuid4(), uuid.uuid4(), 0, CV_TEXT, [1.0, 0.0], {}, "CV", {}, None, "general", 1.0)],
        version=1,
    )


def _pipeline(provider):
    return ChatbotService(
        llm_provider=provider,
        retriever=ContextRetriever(_Embeddings(), reranker=None),
        index=_Index(),
        guard=InputGuard(),
        cache=ResponseCache(10, 60),
    )


async def _result(pipeline, query, history):
    events = [e async for e in pipeline.run(TurnRequest(query=query, history=history, policy=DENY_POLICY))]
    assert isinstance(events[-1], TurnResult)
    return events[-1]


def test_failed_turns_are_dropped_from_history():
    assert recent_history(HISTORY, 10) == [{"role": "user", "content": "what do you know of luong chi duc"}]


@pytest.mark.asyncio
async def test_rewriter_sends_history_as_one_quoted_message():
    provider = _Provider(rewrite="what do you know of luong chi duc")
    await QueryRewriter(provider).rewrite("answer my question", HISTORY)

    system, user = provider.rewrite_calls[0]
    assert [system["role"], user["role"]] == ["system", "user"]
    assert "what do you know of luong chi duc" in user["content"]
    assert "answer my question" in user["content"]
    assert AutoReplies.ERROR not in user["content"]


@pytest.mark.asyncio
async def test_bad_rewrite_falls_back_to_the_original_query():
    provider = _Provider(rewrite=BAD_REWRITE)
    result = await _result(_pipeline(provider), "tell me about luong chi duc", HISTORY)

    assert result.outcome == TurnOutcome.ANSWERED
    assert provider.stream_calls == 1


@pytest.mark.asyncio
async def test_human_request_with_handoff_off_says_so_without_searching():
    provider = _Provider()
    result = await _result(_pipeline(provider), "tôi muốn gặp nhân viên tư vấn", [])

    assert result.outcome == TurnOutcome.DENIED
    assert result.text == AutoReplies.HUMAN_UNAVAILABLE
    assert provider.rewrite_calls == [] and provider.stream_calls == 0
