"""Unit tests for QueryRewriter - condensing follow-up questions into standalone queries."""

from core.agent.query_rewriter import QueryRewriter


class _StubClientProvider:
    """Fake OpenAIClientProvider that records calls instead of hitting the API."""

    def __init__(self, response: str = "", raise_error: bool = False):
        self.response = response
        self.raise_error = raise_error
        self.calls = []

    def complete(self, messages, model=None):
        self.calls.append(messages)
        if self.raise_error:
            raise RuntimeError("simulated API failure")
        return self.response


def test_rewrite_without_history_is_a_noop():
    client = _StubClientProvider(response="should never be used")
    rewriter = QueryRewriter(client)

    result = rewriter.rewrite("còn cái kia thì sao?", None)

    assert result == "còn cái kia thì sao?"
    assert client.calls == []


def test_rewrite_without_history_empty_list_is_a_noop():
    client = _StubClientProvider(response="should never be used")
    rewriter = QueryRewriter(client)

    result = rewriter.rewrite("còn cái kia thì sao?", [])

    assert result == "còn cái kia thì sao?"
    assert client.calls == []


def test_rewrite_with_history_calls_client_and_returns_rewritten_query():
    history = [
        {"role": "user", "content": "Chính sách nghỉ phép của công ty là gì?"},
        {"role": "assistant", "content": "Nhân viên được nghỉ 12 ngày phép mỗi năm."},
    ]
    client = _StubClientProvider(response="Chính sách nghỉ ốm của công ty là gì?")
    rewriter = QueryRewriter(client)

    result = rewriter.rewrite("còn nghỉ ốm thì sao?", history)

    assert result == "Chính sách nghỉ ốm của công ty là gì?"
    assert len(client.calls) == 1


def test_rewrite_falls_back_to_original_query_on_client_error():
    history = [{"role": "user", "content": "hello"}]
    client = _StubClientProvider(raise_error=True)
    rewriter = QueryRewriter(client)

    result = rewriter.rewrite("follow up question", history)

    assert result == "follow up question"


def test_rewrite_falls_back_to_original_query_on_empty_response():
    history = [{"role": "user", "content": "hello"}]
    client = _StubClientProvider(response="")
    rewriter = QueryRewriter(client)

    result = rewriter.rewrite("follow up question", history)

    assert result == "follow up question"
