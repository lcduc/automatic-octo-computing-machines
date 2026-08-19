"""Unit tests for IntentRouter - classifying a turn as RAG lookup vs action/tool call."""

import pytest

from core.agent.intent_router import IntentRouter
from core.agent.tools.base import BaseTool
from core.agent.tools.registry import ToolRegistry
from models.intent import IntentType


class _DummyTool(BaseTool):
    """Trivial test-only tool: exercises the registry, not a shipped product tool."""

    @property
    def name(self) -> str:
        return "get_current_time"

    @property
    def description(self) -> str:
        return "Get the current date and time."

    @property
    def parameters(self):
        return {"type": "object", "properties": {}}

    def execute(self, **kwargs) -> str:
        return "2026-01-01 00:00:00"


class _StubClientProvider:
    """Fake OpenAIClientProvider that records calls instead of hitting the API."""

    def __init__(self, response: str = "", raise_error: bool = False):
        self.response = response
        self.raise_error = raise_error
        self.calls = []

    async def complete_async(self, messages, model=None):
        self.calls.append(messages)
        if self.raise_error:
            raise RuntimeError("simulated API failure")
        return self.response


def _router_with_tool(client: _StubClientProvider) -> IntentRouter:
    return IntentRouter(client, ToolRegistry(tools=[_DummyTool()]))


@pytest.mark.asyncio
async def test_classifies_question_as_rag():
    client = _StubClientProvider(response="rag")
    router = _router_with_tool(client)

    result = await router.classify("Chính sách nghỉ phép của công ty là gì?")

    assert result == IntentType.RAG
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_classifies_command_as_action():
    client = _StubClientProvider(response="action")
    router = _router_with_tool(client)

    result = await router.classify("Bây giờ là mấy giờ?")

    assert result == IntentType.ACTION


@pytest.mark.asyncio
async def test_output_is_case_and_whitespace_insensitive():
    client = _StubClientProvider(response="  Action \n")
    router = _router_with_tool(client)

    result = await router.classify("Bây giờ là mấy giờ?")

    assert result == IntentType.ACTION


@pytest.mark.asyncio
async def test_unrecognized_output_defaults_to_rag():
    client = _StubClientProvider(response="tôi không chắc")
    router = _router_with_tool(client)

    result = await router.classify("một câu hỏi bất kỳ")

    assert result == IntentType.RAG


@pytest.mark.asyncio
async def test_client_error_defaults_to_rag():
    client = _StubClientProvider(raise_error=True)
    router = _router_with_tool(client)

    result = await router.classify("một câu hỏi bất kỳ")

    assert result == IntentType.RAG


@pytest.mark.asyncio
async def test_history_is_included_in_the_classification_call():
    history = [
        {"role": "user", "content": "Chính sách nghỉ phép của công ty là gì?"},
        {"role": "assistant", "content": "Nhân viên được nghỉ 12 ngày phép mỗi năm."},
    ]
    client = _StubClientProvider(response="rag")
    router = _router_with_tool(client)

    await router.classify("còn nghỉ ốm thì sao?", history)

    sent_messages = client.calls[0]
    assert any(m["content"] == history[0]["content"] for m in sent_messages[1:])


# --- Registry-driven prompt --------------------------------------------------


@pytest.mark.asyncio
async def test_system_prompt_reflects_registered_tool_description():
    client = _StubClientProvider(response="rag")
    router = _router_with_tool(client)

    await router.classify("Bây giờ là mấy giờ?")

    system_message = client.calls[0][0]
    assert system_message["role"] == "system"
    assert "get_current_time" in system_message["content"]
    assert "Get the current date and time." in system_message["content"]


@pytest.mark.asyncio
async def test_no_tools_registered_defaults_to_rag_without_calling_llm():
    client = _StubClientProvider(response="action")  # would mislead if it were ever read
    router = IntentRouter(client, ToolRegistry(tools=[]))

    result = await router.classify("Bây giờ là mấy giờ?")

    assert result == IntentType.RAG
    assert client.calls == []
