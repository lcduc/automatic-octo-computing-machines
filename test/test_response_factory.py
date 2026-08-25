"""Unit tests for ChatResponseFactory's answer/citations envelope builders."""

import types

from core.agent.response_factory import ChatResponseFactory


class _StubConfidenceScorer:
    """Minimal stand-in exposing only what ChatResponseFactory calls."""

    def get_confidence_level(self, score: float) -> str:
        return "High" if score >= 0.8 else "Low"


def _confidence(score: float = 0.9):
    return types.SimpleNamespace(
        overall_score=score,
        context_alignment=0.9,
        response_length_appropriateness=0.9,
        semantic_coherence=0.9,
        source_citation=0.9,
        uncertainty_indicators=0.9,
        reasoning="Looks good.",
    )


def _factory() -> ChatResponseFactory:
    return ChatResponseFactory(_StubConfidenceScorer())


def _result(source_id: str, score: float, source_name: str = None) -> dict:
    return {
        "index": 0,
        "combined_score": score,
        "source_id": source_id,
        "source_name": source_name or source_id,
        "source_type": "file",
    }


# --- citations() ---------------------------------------------------------


def test_citations_empty_for_no_results():
    assert ChatResponseFactory.citations(None) == []
    assert ChatResponseFactory.citations([]) == []


def test_citations_dedupes_by_source_keeping_best_score():
    results = [
        _result("doc_a", 0.6),
        _result("doc_a", 0.9),  # better chunk from the same source
        _result("doc_b", 0.75),
    ]

    citations = ChatResponseFactory.citations(results)

    assert citations == [
        {"source": "doc_a", "type": "file", "score": 0.9},
        {"source": "doc_b", "type": "file", "score": 0.75},
    ]


def test_citations_sorted_highest_score_first():
    results = [_result("low", 0.3), _result("high", 0.95), _result("mid", 0.6)]

    citations = ChatResponseFactory.citations(results)

    assert [c["source"] for c in citations] == ["high", "mid", "low"]


# --- answer_payload() / history_payload() / history_error_payload() ------


def test_answer_payload_shape():
    factory = _factory()

    payload = factory.answer_payload("hello", _confidence(0.9), cached=True)

    assert payload["text"] == "hello"
    assert payload["cached"] is True
    assert payload["confidence"]["score"] == 0.9
    assert payload["confidence"]["level"] == "High"


def test_history_payload_carries_answer_and_citations():
    factory = _factory()
    results = [_result("doc_a", 0.9)]

    payload = factory.history_payload("hello", _confidence(0.9), results, cached=False)

    assert payload["success"] is True
    assert payload["answer"]["text"] == "hello"
    assert payload["citations"] == [{"source": "doc_a", "type": "file", "score": 0.9}]


def test_history_error_payload_shape():
    payload = ChatResponseFactory.history_error_payload("boom")

    assert payload == {"answer": None, "citations": [], "success": False, "error": "boom"}


# --- streaming events ------------------------------------------------------


def test_stream_delta_event_shape():
    assert ChatResponseFactory.stream_delta_event("hi") == {
        "type": "delta",
        "answer": {"text": "hi"},
    }


def test_stream_final_event_blanks_text_but_keeps_citations_and_confidence():
    factory = _factory()
    results = [_result("doc_a", 0.9)]

    event = factory.stream_final_event("full answer", _confidence(0.9), results, cached=False)

    assert event["type"] == "final"
    assert event["answer"]["text"] == ""
    assert event["answer"]["confidence"]["score"] == 0.9
    assert event["citations"] == [{"source": "doc_a", "type": "file", "score": 0.9}]


def test_stream_error_event_shape():
    assert ChatResponseFactory.stream_error_event("boom") == {
        "type": "error",
        "message": "boom",
    }
