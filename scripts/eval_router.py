"""
Router eval: how well the embedding router sorts a labelled set of messages.

Runs ``scripts/demo_data/router_eval.json`` (``[{"text": ..., "intent": <route name>}]``) through
the router with the real embedding model, and reports:

- accuracy and a confusion matrix of expected vs decided route;
- the safety figure that matters most: real questions (``rag_question``) that a shortcut stole;
- the second off-topic signal: off-topic messages the router left for retrieval, split by whether
  their on-topic score is below ``ROUTE_OFF_TOPIC_LEAD`` (refused after an empty retrieval) or above (handed to staff);
- the score ranges per route, to tune the thresholds.

No LLM calls are made. Usage (from the repository root, with the venv active)::

    python -m scripts.eval_router
    python -m scripts.eval_router --eval-set my_set.json --out logs/router_report.json
    python -m scripts.eval_router --golden-set scripts/demo_data/golden_colloquial_dev.json

``--golden-set`` adds a retrieval golden set (``[{"query", "expected_document", "kind"?}]``): answerable and
``unanswerable`` questions must stay ``rag_question``, the rest must be ``off_topic``.
"""

# Standard library imports
import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

# Third-party imports
from dotenv import load_dotenv

load_dotenv()

# Local imports
from config.settings import Config  # noqa: E402
from core.retrieval.embeddings import get_embedding_service  # noqa: E402
from core.routing.embedding_router import EmbeddingRouter, RouteIntent  # noqa: E402
from scripts.eval_baseline import ROUTER_SECTION, EvalBaseline  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_EVAL_SET_PATH = Path(__file__).parent / "demo_data" / "router_eval.json"


class RouterEvaluator:
    """Scores the router on a labelled set."""

    def __init__(self, router: EmbeddingRouter):
        """
        Args:
            router: The router under test.
        """
        self._router = router

    def evaluate(self, cases: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Route every case.

        Returns:
            The report: counts, confusion matrix, stolen questions, off-topic coverage and score ranges.
        """
        decided = [(case, self._router.classify(case["text"])) for case in cases]
        confusion: Dict[str, Counter] = defaultdict(Counter)
        for case, decision in decided:
            confusion[case["intent"]][decision.intent.value] += 1
        correct = sum(1 for case, decision in decided if decision.intent.value == case["intent"])

        stolen = [
            {"text": case["text"], "became": decision.intent.value, "score": round(decision.score, 3)}
            for case, decision in decided
            if case["intent"] == RouteIntent.RAG_QUESTION.value and decision.intent != RouteIntent.RAG_QUESTION
        ]
        off_topic = [(case, d) for case, d in decided if case["intent"] == RouteIntent.OFF_TOPIC.value]
        left = [(case, d) for case, d in off_topic if d.intent != RouteIntent.OFF_TOPIC]
        return {
            "cases": len(cases),
            "accuracy": correct / len(cases),
            "confusion": {expected: dict(row) for expected, row in confusion.items()},
            "questions_stolen_by_a_shortcut": stolen,
            "off_topic": {
                "caught_by_router": len(off_topic) - len(left),
                "left_for_retrieval_but_refused_when_it_finds_nothing": sum(1 for _, d in left if d.looks_off_topic),
                "left_for_retrieval_and_would_be_handed_to_staff": [
                    {"text": case["text"], "lead": round(d.off_topic_lead, 3)} for case, d in left if not d.looks_off_topic
                ],
            },
            "questions_refused_when_retrieval_finds_nothing": [
                {"text": case["text"], "lead": round(decision.off_topic_lead, 3)}
                for case, decision in decided
                if case["intent"] == RouteIntent.RAG_QUESTION.value and decision.looks_off_topic
            ],
            "score_ranges": self._score_ranges(decided),
            "thresholds": EmbeddingRouter.thresholds(),
            "off_topic_lead": Config.Routing.OFF_TOPIC_LEAD(),
        }

    @staticmethod
    def _score_ranges(decided) -> Dict[str, Dict[str, float]]:
        """Per expected route: the lowest and highest best-match score, to compare with its threshold."""
        ranges: Dict[str, List[float]] = defaultdict(list)
        for case, decision in decided:
            if decision.best_route == case["intent"]:
                ranges[case["intent"]].append(decision.score)
        return {route: {"min": round(min(v), 3), "max": round(max(v), 3)} for route, v in ranges.items()}


def golden_to_router_cases(golden: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Router cases from a retrieval golden set: anything on topic is a real question, the rest is off topic."""
    return [
        {
            "text": item["query"],
            "intent": (
                RouteIntent.RAG_QUESTION.value
                if item["expected_document"] or item.get("kind") == "unanswerable"
                else RouteIntent.OFF_TOPIC.value
            ),
        }
        for item in golden
    ]


def print_report(report: Dict[str, Any]) -> None:
    """Human-readable summary of :meth:`RouterEvaluator.evaluate` (intentional CLI output)."""
    print(f"\nRouter: {report['cases']} labelled messages, accuracy {report['accuracy']:.1%}")
    routes = [route.value for route in RouteIntent]
    print("\n  expected \\ decided  " + "  ".join(f"{route[:9]:>9}" for route in routes))
    for expected in routes:
        row = report["confusion"].get(expected, {})
        print(f"  {expected:<18} " + "  ".join(f"{row.get(route, 0):>9}" for route in routes))
    print(f"\n  Real questions stolen by a shortcut: {len(report['questions_stolen_by_a_shortcut'])}")
    for item in report["questions_stolen_by_a_shortcut"]:
        print(f"    - {item['text']!r} -> {item['became']} ({item['score']})")
    off = report["off_topic"]
    print(
        f"\n  Off topic: {off['caught_by_router']} caught by the router, "
        f"{off['left_for_retrieval_but_refused_when_it_finds_nothing']} left for retrieval and refused when it finds nothing, "
        f"{len(off['left_for_retrieval_and_would_be_handed_to_staff'])} would still be handed to staff"
    )
    for item in off["left_for_retrieval_and_would_be_handed_to_staff"]:
        print(f"    - {item['text']!r} (lead {item['lead']:+})")
    refused = report["questions_refused_when_retrieval_finds_nothing"]
    print(f"  Real questions that would be refused if retrieval found nothing: {len(refused)} "
          f"(ROUTE_OFF_TOPIC_LEAD={report['off_topic_lead']})")
    for item in refused:
        print(f"    - {item['text']!r} (lead {item['lead']:+})")
    print("\n  Best-match score range of correctly routed messages vs the threshold in force:")
    for route, spread in report["score_ranges"].items():
        threshold = report["thresholds"].get(route)
        print(f"    {route:<16} min {spread['min']:.3f}  max {spread['max']:.3f}  threshold {threshold[0] if threshold else '-'}")


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point; returns the exit code."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--eval-set", type=Path, default=DEFAULT_EVAL_SET_PATH)
    parser.add_argument("--golden-set", type=Path, action="append", default=[], help="Also use a retrieval golden set (repeatable)")
    parser.add_argument("--out", type=Path, default=None, help="Write the full report here as JSON")
    parser.add_argument("--check", action="store_true", help="Fail (exit 1) when the report regresses against the committed baseline")
    parser.add_argument("--write-baseline", action="store_true", help="Record this report as the baseline (then commit the file)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    cases = json.loads(args.eval_set.read_text(encoding="utf-8"))
    for path in args.golden_set:
        cases += golden_to_router_cases(json.loads(path.read_text(encoding="utf-8")))
    report = RouterEvaluator(EmbeddingRouter(get_embedding_service())).evaluate(cases)
    print_report(report)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nFull report saved to {args.out}")
    baseline = EvalBaseline()
    if args.write_baseline:
        baseline.write(ROUTER_SECTION, baseline.router_values(report))
        print("Baseline written; commit scripts/demo_data/eval_baseline.json")
    if args.check:
        problems = baseline.check_router(report)
        for problem in problems:
            print(f"REGRESSION: {problem}")
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
