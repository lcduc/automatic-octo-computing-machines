"""Unit tests for the intent-routing eval harness (a fake router, no LLM calls)."""

import asyncio
import json

from models.intent import IntentType
from scripts.eval_intent_router import DEFAULT_GOLDEN_SET_PATH, IntentRoutingEvaluator

#: Stands in for the ``LLMUsage`` of a call that got an answer; only its presence matters here.
ANSWERED = object()


class FakeRouter:
    """Answers like ``IntentRouter.classify``: ``(intent, usage)``, usage ``None`` when no LLM answered."""

    def __init__(self, answers):
        self._answers = answers

    async def classify(self, query):
        return self._answers[query]


def test_scores_the_intent_out_of_the_routers_intent_usage_pair():
    router = FakeRouter({
        "Bây giờ là mấy giờ?": (IntentType.ACTION, ANSWERED),
        "Visa Đức mất bao lâu?": (IntentType.ACTION, ANSWERED),
    })
    golden = [
        {"query": "Bây giờ là mấy giờ?", "expected_intent": "action"},
        {"query": "Visa Đức mất bao lâu?", "expected_intent": "rag"},
    ]

    report = asyncio.run(IntentRoutingEvaluator(router).evaluate_all(golden))

    assert report["accuracy"] == 0.5
    assert report["confusion_matrix"]["rag"]["action"] == 1
    assert report["unanswered_by_llm"] == 0


def test_counts_turns_the_router_defaulted_to_rag_without_an_llm_answer():
    # classify() falls back to RAG with no usage when the provider call fails,
    # which would otherwise score as a correct "rag" answer.
    router = FakeRouter({"Mức lương tối thiểu?": (IntentType.RAG, None)})

    report = asyncio.run(IntentRoutingEvaluator(router).evaluate_all(
        [{"query": "Mức lương tối thiểu?", "expected_intent": "rag"}]
    ))

    assert report["unanswered_by_llm"] == 1


def test_the_default_golden_set_exists_and_uses_known_intents():
    golden = json.loads(DEFAULT_GOLDEN_SET_PATH.read_text(encoding="utf-8"))

    assert golden
    assert {item["expected_intent"] for item in golden} <= {intent.value for intent in IntentType}
