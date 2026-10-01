"""Unit tests for the embedding router and for how the chat pipeline acts on its decisions (no model weights)."""

import json

import numpy as np
import pytest

from core.agent.chatbot import ChatbotService
from core.agent.prompts import AutoReplies
from core.agent.response_cache import ResponseCache
from core.guardrails.input_guard import InputGuard
from core.retrieval.knowledge_index import KnowledgeSnapshot
from core.retrieval.retriever import ContextRetriever
from core.routing.embedding_router import EmbeddingRouter, RouteDecision, RouteIntent
from models.chat_turn import ChatPolicy, TurnOutcome, TurnRequest, TurnResult
from test.unit.test_chat_pipeline import FakeEmbeddings, FakeIndex, FakeLLM, _snapshot

ROUTES = {
    "greeting": ["xin chao"],
    "thanks": ["cam on"],
    "handoff_request": ["cho toi gap nhan vien"],
    "ambiguous": ["cho em hoi"],
    "off_topic": ["gia vang hom nay"],
    "rag_question": ["di duc lam viec can gi"],
}
#: One axis per route, so a text's route is the axis it points along.
AXES = {name: index for index, name in enumerate(ROUTES)}


class AxisEmbeddings:
    """Embeds a text as the axis of the route one of whose examples it contains, mixed by an optional blend."""

    def __init__(self, blends=None):
        self._blends = blends or {}

    def embed_query(self, text):
        vector = np.zeros(len(AXES), dtype=np.float32)
        for name, examples in ROUTES.items():
            if any(example in text for example in examples):
                vector[AXES[name]] = 1.0
        for name, weight in self._blends.get(text, {}).items():
            vector[AXES[name]] = weight
        norm = np.linalg.norm(vector)
        return vector / norm if norm else vector


@pytest.fixture
def routes_file(tmp_path):
    path = tmp_path / "routes.json"
    path.write_text(json.dumps({"routes": ROUTES}), encoding="utf-8")
    return path


def _router(routes_file, blends=None):
    return EmbeddingRouter(AxisEmbeddings(blends), routes_file)


def test_each_route_is_recognised_by_its_examples(routes_file):
    router = _router(routes_file)
    for name, examples in ROUTES.items():
        assert router.classify(examples[0]).intent.value == name


def test_a_vague_match_is_a_question_not_a_shortcut(routes_file):
    # Equally close to "greeting" and "thanks": no clear winner, so retrieval decides.
    router = _router(routes_file, blends={"alo": {"greeting": 1.0, "thanks": 1.0}})
    assert router.classify("alo").intent == RouteIntent.RAG_QUESTION


def test_small_talk_shortcuts_only_apply_to_short_messages(routes_file):
    router = _router(routes_file)
    long_greeting = "xin chao, " + "toi muon biet them ve viec " * 3
    assert router.classify(long_greeting).intent == RouteIntent.RAG_QUESTION
    assert router.classify("gia vang hom nay " + "x" * 80).intent == RouteIntent.OFF_TOPIC


def test_off_topic_lead_compares_the_two_example_sets(routes_file):
    router = _router(routes_file, blends={"khong ro": {"off_topic": 1.0, "rag_question": 0.5}})
    assert router.classify("khong ro").looks_off_topic
    assert not router.classify("di duc lam viec can gi").looks_off_topic


def _decision(lead):
    return RouteDecision(
        intent=RouteIntent.RAG_QUESTION, score=1.0, best_route="rag_question", runner_up="x", runner_up_score=0.0,
        scores={RouteIntent.OFF_TOPIC.value: max(lead, 0.0), RouteIntent.RAG_QUESTION.value: max(-lead, 0.0)},
    )


def test_a_message_nothing_relates_to_is_off_topic_unless_it_is_clearly_on_topic():
    assert _decision(0.0).is_off_topic(0.0003)  # nothing in the knowledge base relates, not clearly on topic
    assert not _decision(0.0).is_off_topic(0.004)  # related a little: on topic, just unanswered
    assert not _decision(0.0).is_off_topic(None)  # no reranker scored: no verdict from relatedness
    assert not _decision(-0.05).is_off_topic(0.0003)  # clearly on topic however low the score
    assert _decision(0.05).is_off_topic(0.9)  # nearer the off-topic examples


class StubRouter:
    """Returns a fixed decision, so the pipeline tests do not depend on embeddings."""

    def __init__(self, intent, lead=0.0):
        self._decision = RouteDecision(
            intent=intent, score=1.0, best_route=intent.value, runner_up="x", runner_up_score=0.0,
            scores={RouteIntent.OFF_TOPIC.value: max(lead, 0.0), RouteIntent.RAG_QUESTION.value: max(-lead, 0.0)},
        )

    def classify(self, text):
        return self._decision


POLICY = ChatPolicy(
    fallback_mode="handoff", deny_message="DENY", handoff_message="HANDOFF", guard_block_message="BLOCKED",
    greeting_message="HELLO", thanks_message="WELCOME",
)


def _pipeline(llm, router, snapshot=None):
    return ChatbotService(
        llm_provider=llm, retriever=ContextRetriever(FakeEmbeddings(), reranker=None),
        index=FakeIndex(snapshot or _snapshot()), guard=InputGuard(),
        cache=ResponseCache(max_entries=10, ttl_seconds=60), router=router,
    )


async def _ask(pipeline, query, history=None, policy=POLICY):
    events = [e async for e in pipeline.run(TurnRequest(query=query, history=history or [], policy=policy))]
    assert isinstance(events[-1], TurnResult)
    return events[-1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "intent, outcome, text, reason",
    [
        (RouteIntent.GREETING, TurnOutcome.SMALLTALK, "HELLO", None),
        (RouteIntent.THANKS, TurnOutcome.SMALLTALK, "WELCOME", None),
        (RouteIntent.OFF_TOPIC, TurnOutcome.DENIED, AutoReplies.OFF_TOPIC, None),
        (RouteIntent.HANDOFF_REQUEST, TurnOutcome.HANDOFF, "HANDOFF", "user_request"),
    ],
)
async def test_confident_routes_answer_without_any_llm_call(intent, outcome, text, reason):
    llm = FakeLLM()
    result = await _ask(_pipeline(llm, StubRouter(intent)), "bat ky")
    assert (result.outcome, result.text) == (outcome, text)
    assert (result.handoff_reason.value if result.handoff_reason else None) == reason
    assert llm.stream_calls == [] and llm.complete_calls == []


@pytest.mark.asyncio
async def test_a_vague_opener_is_asked_once_and_then_handed_to_staff():
    llm = FakeLLM()
    pipeline = _pipeline(llm, StubRouter(RouteIntent.AMBIGUOUS))
    first = await _ask(pipeline, "cho em hỏi")
    assert (first.outcome, first.text) == (TurnOutcome.SMALLTALK, AutoReplies.CLARIFY)

    history = [{"role": "user", "content": "cho em hỏi"}, {"role": "assistant", "content": AutoReplies.CLARIFY}]
    second = await _ask(pipeline, "mình cần hỏi", history=history)
    assert second.outcome == TurnOutcome.HANDOFF and second.handoff_reason.value == "ambiguous_repeated"
    assert llm.stream_calls == [] and llm.complete_calls == []


@pytest.mark.asyncio
async def test_a_short_follow_up_mid_conversation_is_not_called_vague():
    llm = FakeLLM()
    history = [{"role": "user", "content": "lương tối thiểu"}, {"role": "assistant", "content": "Vùng nào?"}]
    result = await _ask(_pipeline(llm, StubRouter(RouteIntent.AMBIGUOUS)), "vùng I thì sao", history=history)
    assert result.outcome == TurnOutcome.ANSWERED


@pytest.mark.asyncio
async def test_nothing_found_is_refused_when_off_topic_but_handed_to_staff_when_on_topic():
    llm = FakeLLM()
    empty = KnowledgeSnapshot.empty()
    off = await _ask(_pipeline(llm, StubRouter(RouteIntent.RAG_QUESTION, lead=0.1), empty), "xyz")
    assert (off.outcome, off.text) == (TurnOutcome.DENIED, AutoReplies.OFF_TOPIC)
    on = await _ask(_pipeline(llm, StubRouter(RouteIntent.RAG_QUESTION, lead=-0.1), empty), "xyz")
    assert on.outcome == TurnOutcome.HANDOFF and on.handoff_reason.value == "no_knowledge"
    assert llm.stream_calls == []
