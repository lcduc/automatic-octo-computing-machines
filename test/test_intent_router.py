"""Unit tests for IntentRouter - classifying a turn as RAG lookup vs action/tool call."""

import pytest

from core.agent.intent_router import IntentRouter
from core.agent.tools.base import BaseTool
from core.agent.tools.registry import ToolRegistry
from models.intent import IntentType
from models.llm import LLMResult


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

    async def execute(self, arguments, context) -> str:
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
        return LLMResult(self.response)


def _router_with_tool(client: _StubClientProvider) -> IntentRouter:
    return IntentRouter(client, ToolRegistry(tools=[_DummyTool()]))


@pytest.mark.asyncio
async def test_classifies_question_as_rag():
    client = _StubClientProvider(response="rag")
    router = _router_with_tool(client)

    result, _usage = await router.classify("Chính sách nghỉ phép của công ty là gì?")

    assert result == IntentType.RAG
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_classifies_command_as_action():
    client = _StubClientProvider(response="action")
    router = _router_with_tool(client)

    result, _usage = await router.classify("Bây giờ là mấy giờ?")

    assert result == IntentType.ACTION


@pytest.mark.asyncio
async def test_output_is_case_and_whitespace_insensitive():
    client = _StubClientProvider(response="  Action \n")
    router = _router_with_tool(client)

    result, _usage = await router.classify("Bây giờ là mấy giờ?")

    assert result == IntentType.ACTION


@pytest.mark.asyncio
async def test_unrecognized_output_defaults_to_rag():
    client = _StubClientProvider(response="tôi không chắc")
    router = _router_with_tool(client)

    result, _usage = await router.classify("một câu hỏi bất kỳ")

    assert result == IntentType.RAG


@pytest.mark.asyncio
async def test_client_error_defaults_to_rag():
    client = _StubClientProvider(raise_error=True)
    router = _router_with_tool(client)

    result, _usage = await router.classify("một câu hỏi bất kỳ")

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

    result, _usage = await router.classify("Bây giờ là mấy giờ?")

    assert result == IntentType.RAG
    assert client.calls == []


class _PrivateTool(_DummyTool):
    """A tool only signed-in users may use."""

    @property
    def name(self) -> str:
        return "list_my_orders"

    @property
    def description(self) -> str:
        return "List the signed-in user's own orders."

    @property
    def required_tier_level(self) -> int:
        return 1


@pytest.mark.asyncio
async def test_anonymous_request_for_private_data_asks_for_login_without_offering_the_tool():
    from models.tool_context import ToolContext

    client = _StubClientProvider(response="login")
    router = IntentRouter(client, ToolRegistry(tools=[_DummyTool(), _PrivateTool()]), login_available=True)
    intent, _ = await router.classify("đơn hàng của tôi", context=ToolContext())
    assert intent == IntentType.LOGIN_REQUIRED
    prompt = client.calls[0][0]["content"]
    assert "List the signed-in user's own orders." in prompt and "list_my_orders" not in prompt

    signed_in, _ = await IntentRouter(client, ToolRegistry(tools=[_PrivateTool()]), login_available=True).classify(
        "đơn hàng của tôi", context=ToolContext(user_id="user-42", tier_level=1))
    assert signed_in == IntentType.RAG  # the stub still says "login"; a signed-in user is never asked to log in
    assert "list_my_orders" in client.calls[-1][0]["content"]


@pytest.mark.asyncio
async def test_login_is_never_offered_when_the_host_has_no_sign_in():
    from models.tool_context import ToolContext

    client = _StubClientProvider(response="login")
    router = IntentRouter(client, ToolRegistry(tools=[_PrivateTool()]), login_available=False)
    assert await router.classify("đơn hàng của tôi", context=ToolContext()) == (IntentType.RAG, None)
    assert client.calls == []
