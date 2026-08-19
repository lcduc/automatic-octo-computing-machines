"""Unit tests for ChatbotService's intent-based routing to ToolCallingAgent."""

import types

import pytest

from core.agent.chatbot import ChatbotService
from core.infrastructure.audit_trail_service import AuditTrailService


class _StubProvider:
    """Fake LLM provider covering intent classification, tool-calling and streaming."""

    def __init__(self, intent_text: str = "rag", decision_message=None, stream_chunks=None):
        self.intent_text = intent_text
        self.decision_message = decision_message or types.SimpleNamespace(
            content="", tool_calls=[]
        )
        self.stream_chunks = stream_chunks or ["ok"]
        self.complete_async_calls = []
        self.complete_with_tools_calls = []
        self.stream_calls = []

    def check_availability(self) -> bool:
        return True

    async def complete_async(self, messages, model=None):
        self.complete_async_calls.append(messages)
        return self.intent_text

    async def complete_with_tools_async(self, messages, tools=None, model=None):
        self.complete_with_tools_calls.append({"messages": messages, "tools": tools})
        return self.decision_message

    async def stream(self, messages, model=None):
        self.stream_calls.append(messages)
        for chunk in self.stream_chunks:
            yield chunk


@pytest.mark.asyncio
async def test_action_intent_uses_tool_calling_agent_and_skips_rag():
    decision_message = types.SimpleNamespace(content="It's 10am.", tool_calls=[])
    provider = _StubProvider(intent_text="action", decision_message=decision_message)
    service = ChatbotService(context_retriever=object(), llm_provider=provider)

    deltas = [delta async for delta in service.stream_response_with_history("what time is it?")]

    assert deltas == ["It's 10am."]
    assert len(provider.complete_async_calls) == 1  # IntentRouter.classify
    assert len(provider.complete_with_tools_calls) == 1  # ToolCallingAgent decision call
    assert provider.stream_calls == []  # RAG generation never reached


@pytest.mark.asyncio
async def test_rag_intent_leaves_existing_rag_flow_untouched(tmp_path):
    provider = _StubProvider(intent_text="rag", stream_chunks=["hello ", "there"])
    # Dedicated audit log so this test's turn never lands in the real
    # data/logs/audit_trail.jsonl - this path runs the turn to completion,
    # which triggers ChatbotService._record_audit.
    audit_trail = AuditTrailService(log_path=str(tmp_path / "audit_trail.jsonl"))
    service = ChatbotService(
        context_retriever=object(), llm_provider=provider, audit_trail=audit_trail
    )

    deltas = [delta async for delta in service.stream_response_with_history("hi")]

    assert deltas == ["hello ", "there"]
    assert len(provider.complete_async_calls) == 1  # IntentRouter.classify only
    assert provider.complete_with_tools_calls == []  # tool-calling never invoked
    assert len(provider.stream_calls) == 1


@pytest.mark.asyncio
async def test_tool_calling_disabled_skips_intent_classification(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_ENABLED", "false")
    provider = _StubProvider(intent_text="action", stream_chunks=["ok"])
    service = ChatbotService(context_retriever=object(), llm_provider=provider)

    generator = service.stream_response_with_history("hi")
    try:
        first_delta = await generator.__anext__()
    finally:
        await generator.aclose()

    assert first_delta == "ok"
    assert provider.complete_async_calls == []  # classify() never called
    assert provider.complete_with_tools_calls == []
