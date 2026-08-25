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


class _StubRetriever:
    """Fake retriever returning fixed, pre-built search results."""

    def __init__(self, results):
        self._results = results

    def hybrid_search(self, query, embeddings, documents, k, semantic_weight):
        return self._results


@pytest.mark.asyncio
async def test_action_intent_uses_tool_calling_agent_and_skips_rag():
    decision_message = types.SimpleNamespace(content="It's 10am.", tool_calls=[])
    provider = _StubProvider(intent_text="action", decision_message=decision_message)
    service = ChatbotService(context_retriever=object(), llm_provider=provider)

    deltas = [delta async for delta in service.stream_response_with_history("what time is it?")]

    assert deltas == [
        {"type": "delta", "answer": {"text": "It's 10am."}},
        {"type": "final", "answer": {"text": ""}, "citations": []},
    ]
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

    events = [event async for event in service.stream_response_with_history("hi")]

    assert events[:2] == [
        {"type": "delta", "answer": {"text": "hello "}},
        {"type": "delta", "answer": {"text": "there"}},
    ]
    assert len(events) == 3
    final_event = events[2]
    assert final_event["type"] == "final"
    assert final_event["answer"]["text"] == ""
    assert final_event["answer"]["cached"] is False
    assert "confidence" in final_event["answer"]
    assert final_event["citations"] == []  # no documents were provided, so no RAG results
    assert len(provider.complete_async_calls) == 1  # IntentRouter.classify only
    assert provider.complete_with_tools_calls == []  # tool-calling never invoked
    assert len(provider.stream_calls) == 1


@pytest.mark.asyncio
async def test_rag_intent_streams_citations_for_retrieved_sources(tmp_path):
    results = [
        {
            "document": "doc a text",
            "combined_score": 0.9,
            "index": 0,
            "source_id": "doc_a",
            "source_name": "doc_a.pdf",
            "source_type": "file",
        },
        {
            "document": "doc b text",
            "combined_score": 0.7,
            "index": 1,
            "source_id": "doc_b",
            "source_name": "doc_b.pdf",
            "source_type": "file",
        },
    ]
    provider = _StubProvider(intent_text="rag", stream_chunks=["answer"])
    audit_trail = AuditTrailService(log_path=str(tmp_path / "audit_trail.jsonl"))
    service = ChatbotService(
        context_retriever=_StubRetriever(results), llm_provider=provider, audit_trail=audit_trail
    )

    events = [
        event
        async for event in service.stream_response_with_history(
            "hi", embeddings=object(), documents=["doc a text", "doc b text"]
        )
    ]

    final_event = events[-1]
    assert final_event["type"] == "final"
    assert final_event["citations"] == [
        {"source": "doc_a.pdf", "type": "file", "score": 0.9},
        {"source": "doc_b.pdf", "type": "file", "score": 0.7},
    ]


@pytest.mark.asyncio
async def test_tool_calling_disabled_skips_intent_classification(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_ENABLED", "false")
    provider = _StubProvider(intent_text="action", stream_chunks=["ok"])
    service = ChatbotService(context_retriever=object(), llm_provider=provider)

    generator = service.stream_response_with_history("hi")
    try:
        first_event = await generator.__anext__()
    finally:
        await generator.aclose()

    assert first_event == {"type": "delta", "answer": {"text": "ok"}}
    assert provider.complete_async_calls == []  # classify() never called
    assert provider.complete_with_tools_calls == []
