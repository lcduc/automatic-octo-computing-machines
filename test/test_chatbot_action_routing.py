"""Unit tests for the chat pipeline's intent-based routing to the tool-calling agent."""

import types
import uuid

import numpy as np
import pytest

from core.agent.chatbot import ChatbotService
from core.agent.intent_router import IntentRouter
from core.agent.response_cache import ResponseCache
from core.agent.tool_calling_agent import ToolCallingAgent
from core.agent.query_rewriter import QueryRewriter
from core.agent.tools.current_time_tool import CurrentTimeTool
from core.agent.tools.registry import ToolRegistry
from core.guardrails.input_guard import InputGuard
from core.retrieval.knowledge_index import KnowledgeSnapshot
from core.retrieval.retriever import ContextRetriever
from core.storage.knowledge_repository import IndexRow
from models.chat_turn import ChatPolicy, TurnOutcome, TurnRequest, TurnResult, TurnUsage
from models.llm import LLMResult, LLMUsage, StreamDelta

POLICY = ChatPolicy("deny", "DENY", "HANDOFF", "BLOCKED", "HELLO", "WELCOME")


class _StubProvider:
    """Fake provider covering intent classification, tool-calling and streaming."""

    name = "stub"

    def __init__(self, intent_text: str):
        self.intent_text = intent_text
        self.tool_decisions = 0
        self.stream_calls = 0

    async def complete_async(self, messages, model=None):
        return LLMResult(self.intent_text, LLMUsage("stub", "light", 3, 1))

    async def complete_with_tools_async(self, messages, tools=None, model=None):
        self.tool_decisions += 1
        return types.SimpleNamespace(content="Bây giờ là 10:00.", tool_calls=[]), LLMUsage("stub", "main", 20, 5)

    async def stream(self, messages, model=None):
        self.stream_calls += 1
        yield StreamDelta(text="Câu trả lời từ tài liệu.")
        yield StreamDelta(usage=LLMUsage("stub", "main", 50, 10))


class _Embeddings:
    def embed_query(self, query):
        return np.array([1.0, 0.0], dtype=np.float32)


class _Index:
    snapshot = KnowledgeSnapshot.build(
        [IndexRow(uuid.uuid4(), uuid.uuid4(), 0, "Chính sách nghỉ phép 12 ngày", [1.0, 0.0], {}, "Nội quy", {}, None,
                  "general", 1.0)],
        version=1,
    )


def _pipeline(provider):
    registry = ToolRegistry(tools=[CurrentTimeTool()])
    return ChatbotService(
        llm_provider=provider,
        retriever=ContextRetriever(_Embeddings(), reranker=None),
        index=_Index(),
        guard=InputGuard(),
        cache=ResponseCache(10, 60),
        intent_router=IntentRouter(provider, registry),
        tool_agent=ToolCallingAgent(provider, registry, QueryRewriter(provider)),
    )


async def _run(pipeline, query):
    events = [e async for e in pipeline.run(TurnRequest(query=query, history=[], policy=POLICY))]
    assert isinstance(events[-1], TurnResult)
    return events


@pytest.mark.asyncio
async def test_action_intent_is_answered_by_the_tool_agent():
    provider = _StubProvider("action")
    events = await _run(_pipeline(provider), "Bây giờ là mấy giờ?")
    assert events[-1].outcome == TurnOutcome.ANSWERED and events[-1].text == "Bây giờ là 10:00."
    assert provider.tool_decisions == 1 and provider.stream_calls == 0
    assert [e.purpose for e in events if isinstance(e, TurnUsage)] == ["intent", "tool"]


@pytest.mark.asyncio
async def test_rag_intent_uses_retrieval_and_streaming():
    provider = _StubProvider("rag")
    events = await _run(_pipeline(provider), "chính sách nghỉ phép")
    assert events[-1].citations[0]["title"] == "Nội quy"
    assert provider.tool_decisions == 0 and provider.stream_calls == 1
