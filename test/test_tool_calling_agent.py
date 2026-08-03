"""Unit tests for ToolCallingAgent and ToolRegistry - the bare tool-calling frame."""

import types

import pytest

from core.ai_services.llm.tool_calling_agent import ToolCallingAgent
from core.ai_services.llm.tools.base import BaseTool
from core.ai_services.llm.tools.registry import ToolRegistry


class _StubQueryRewriter:
    """No-op rewriter so agent tests aren't coupled to QueryRewriter's own behavior."""

    def rewrite(self, query, history):
        return query


class _EchoTool(BaseTool):
    """Trivial test-only tool: not a shipped product tool, just exercises the registry."""

    @property
    def name(self) -> str:
        return "echo_tool"

    @property
    def description(self) -> str:
        return "Echoes back the given text."

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }

    def execute(self, **kwargs) -> str:
        return f"echoed: {kwargs['text']}"


class _FailingTool(BaseTool):
    """Test-only tool that always raises, to exercise the registry's error handling."""

    @property
    def name(self) -> str:
        return "failing_tool"

    @property
    def description(self) -> str:
        return "Always raises."

    @property
    def parameters(self):
        return {"type": "object", "properties": {}}

    def execute(self, **kwargs) -> str:
        raise RuntimeError("boom")


def _fake_tool_call(call_id: str, name: str, arguments: str):
    return types.SimpleNamespace(
        id=call_id, function=types.SimpleNamespace(name=name, arguments=arguments)
    )


def _fake_message(content=None, tool_calls=None):
    return types.SimpleNamespace(content=content, tool_calls=tool_calls or [])


class _StubClientProvider:
    """Fake OpenAIClientProvider driving the agent without any real API calls."""

    def __init__(self, decision_message, stream_chunks=None):
        self.decision_message = decision_message
        self.stream_chunks = stream_chunks or []
        self.decision_calls = []
        self.stream_calls = []

    async def complete_with_tools_async(self, messages, tools=None):
        self.decision_calls.append({"messages": messages, "tools": tools})
        return self.decision_message

    async def stream(self, messages):
        self.stream_calls.append(messages)
        for chunk in self.stream_chunks:
            yield chunk


async def _collect(agen):
    return [item async for item in agen]


# --- ToolRegistry ------------------------------------------------------------


def test_registry_schemas_empty_when_no_tools():
    registry = ToolRegistry(tools=[])
    assert registry.schemas() == []


def test_registry_executes_registered_tool():
    registry = ToolRegistry(tools=[_EchoTool()])
    result = registry.execute("echo_tool", {"text": "hi"})
    assert result == "echoed: hi"


def test_registry_unknown_tool_returns_error_string_not_raise():
    registry = ToolRegistry(tools=[_EchoTool()])
    result = registry.execute("does_not_exist", {})
    assert "does_not_exist" in result
    assert "Error" in result


def test_registry_tool_exception_returns_error_string_not_raise():
    registry = ToolRegistry(tools=[_FailingTool()])
    result = registry.execute("failing_tool", {})
    assert "failing_tool" in result
    assert "Error" in result


# --- ToolCallingAgent ---------------------------------------------------------


@pytest.mark.asyncio
async def test_no_tool_call_yields_direct_answer():
    client = _StubClientProvider(decision_message=_fake_message(content="Xin chào!"))
    registry = ToolRegistry(tools=[_EchoTool()])
    agent = ToolCallingAgent(client, registry, _StubQueryRewriter())

    deltas = await _collect(agent.stream("hi"))

    assert deltas == ["Xin chào!"]
    assert client.stream_calls == []  # no follow-up call needed


@pytest.mark.asyncio
async def test_tool_call_executes_and_streams_followup():
    tool_call = _fake_tool_call("call_1", "echo_tool", '{"text": "hi"}')
    decision_message = _fake_message(content=None, tool_calls=[tool_call])
    client = _StubClientProvider(
        decision_message=decision_message, stream_chunks=["Final ", "answer"]
    )
    registry = ToolRegistry(tools=[_EchoTool()])
    agent = ToolCallingAgent(client, registry, _StubQueryRewriter())

    deltas = await _collect(agent.stream("please echo hi"))

    assert deltas == ["Final ", "answer"]
    assert len(client.stream_calls) == 1

    followup_messages = client.stream_calls[0]
    tool_messages = [m for m in followup_messages if m.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["content"] == "echoed: hi"
    assert tool_messages[0]["tool_call_id"] == "call_1"


@pytest.mark.asyncio
async def test_malformed_tool_arguments_reported_as_error_not_raised():
    tool_call = _fake_tool_call("call_1", "echo_tool", "not valid json")
    decision_message = _fake_message(content=None, tool_calls=[tool_call])
    client = _StubClientProvider(decision_message=decision_message, stream_chunks=["ok"])
    registry = ToolRegistry(tools=[_EchoTool()])
    agent = ToolCallingAgent(client, registry, _StubQueryRewriter())

    deltas = await _collect(agent.stream("please echo hi"))

    assert deltas == ["ok"]
    followup_messages = client.stream_calls[0]
    tool_messages = [m for m in followup_messages if m.get("role") == "tool"]
    assert "Error" in tool_messages[0]["content"]


@pytest.mark.asyncio
async def test_agent_error_yields_single_error_chunk():
    class _RaisingClientProvider:
        async def complete_with_tools_async(self, messages, tools=None):
            raise RuntimeError("simulated failure")

    agent = ToolCallingAgent(_RaisingClientProvider(), ToolRegistry(tools=[]), _StubQueryRewriter())

    deltas = await _collect(agent.stream("hi"))

    assert len(deltas) == 1
    assert deltas[0].startswith("[ERROR]")
