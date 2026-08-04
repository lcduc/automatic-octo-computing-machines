"""Unit tests for IntentRouter - classifying a turn as RAG lookup vs action/tool call."""

import pytest

from core.ai_services.llm.intent_router import IntentRouter
from models.intent import IntentType


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


@pytest.mark.asyncio
async def test_classifies_question_as_rag():
    client = _StubClientProvider(response="rag")
    router = IntentRouter(client)

    result = await router.classify("Chính sách nghỉ phép của công ty là gì?")

    assert result == IntentType.RAG
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_classifies_command_as_action():
    client = _StubClientProvider(response="action")
    router = IntentRouter(client)

    result = await router.classify("Xoá tài liệu báo cáo tháng 3")

    assert result == IntentType.ACTION


@pytest.mark.asyncio
async def test_output_is_case_and_whitespace_insensitive():
    client = _StubClientProvider(response="  Action \n")
    router = IntentRouter(client)

    result = await router.classify("gửi email cho anh Nam")

    assert result == IntentType.ACTION


@pytest.mark.asyncio
async def test_unrecognized_output_defaults_to_rag():
    client = _StubClientProvider(response="tôi không chắc")
    router = IntentRouter(client)

    result = await router.classify("một câu hỏi bất kỳ")

    assert result == IntentType.RAG


@pytest.mark.asyncio
async def test_client_error_defaults_to_rag():
    client = _StubClientProvider(raise_error=True)
    router = IntentRouter(client)

    result = await router.classify("một câu hỏi bất kỳ")

    assert result == IntentType.RAG


@pytest.mark.asyncio
async def test_history_is_included_in_the_classification_call():
    history = [
        {"role": "user", "content": "Chính sách nghỉ phép của công ty là gì?"},
        {"role": "assistant", "content": "Nhân viên được nghỉ 12 ngày phép mỗi năm."},
    ]
    client = _StubClientProvider(response="rag")
    router = IntentRouter(client)

    await router.classify("còn nghỉ ốm thì sao?", history)

    sent_messages = client.calls[0]
    assert any(m["content"] == history[0]["content"] for m in sent_messages[1:])
