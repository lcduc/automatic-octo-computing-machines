#!/usr/bin/env python3
"""
eval_intent_router.py

Measures real routing accuracy for IntentRouter against a labeled golden set,
using the exact same tool registry the live chatbot registers (see
``ChatbotService.__init__`` in core/agent/chatbot.py) and a real LLM provider
call per query (``Config.LLM.ACTIVE_LIGHT_MODEL()``).

Usage:
  python scripts/eval_intent_router.py
  python scripts/eval_intent_router.py --golden-set data/eval/golden_intents.json --out data/logs/intent_eval_report.json
"""
import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.agent.intent_router import IntentRouter
from core.agent.provider_factory import LLMProviderFactory
from core.agent.tools.current_time_tool import CurrentTimeTool
from core.agent.tools.registry import ToolRegistry
from models.intent import IntentType

logger = logging.getLogger(__name__)

DEFAULT_GOLDEN_SET_PATH = "data/eval/golden_intents.json"


class IntentRoutingEvaluator:
    """Runs a labeled (query, expected_intent) golden set through a real IntentRouter."""

    def __init__(self, router: IntentRouter):
        """
        Args:
            router: Router to evaluate; wraps a real LLM provider, so each
                query in :meth:`evaluate_all` performs one real API call.
        """
        self._router = router

    async def evaluate_one(self, query: str, expected_intent: str) -> Dict[str, Any]:
        """Classify one query and score it against its expected intent."""
        predicted = await self._router.classify(query)
        return {
            "query": query,
            "expected_intent": expected_intent,
            "predicted_intent": predicted.value,
            "correct": predicted.value == expected_intent,
        }

    async def evaluate_all(self, golden_set: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Run the full golden set sequentially and aggregate accuracy overall,
        per expected class, and as a confusion matrix.

        Sequential (not gathered concurrently) so classification calls don't
        burst the LLM provider's rate limit for what is a small, infrequent
        eval run.
        """
        per_query = [
            await self.evaluate_one(item["query"], item["expected_intent"])
            for item in golden_set
        ]

        total = len(per_query)
        correct = sum(1 for r in per_query if r["correct"])

        by_class: Dict[str, Dict[str, int]] = {}
        confusion: Dict[str, Dict[str, int]] = {
            intent.value: {other.value: 0 for other in IntentType} for intent in IntentType
        }
        for r in per_query:
            bucket = by_class.setdefault(r["expected_intent"], {"total": 0, "correct": 0})
            bucket["total"] += 1
            bucket["correct"] += 1 if r["correct"] else 0
            confusion[r["expected_intent"]][r["predicted_intent"]] += 1

        return {
            "total_queries": total,
            "accuracy": correct / total if total else 0.0,
            "by_class": {
                intent: {**stats, "accuracy": stats["correct"] / stats["total"]}
                for intent, stats in sorted(by_class.items())
            },
            "confusion_matrix": confusion,
            "misses": [r for r in per_query if not r["correct"]],
            "per_query": per_query,
        }


def load_golden_set(path: str) -> List[Dict[str, str]]:
    """Load the (query, expected_intent) golden set from a JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def print_report(report: Dict[str, Any]) -> None:
    """Print a human-readable summary of the intent-routing evaluation."""
    print(f"\nIntent routing eval -- {report['total_queries']} queries")
    print(f"  Overall accuracy: {report['accuracy']:.1%}")

    print("\n  By expected class:")
    for intent, stats in report["by_class"].items():
        print(f"    {intent:8s} {stats['correct']}/{stats['total']}  ({stats['accuracy']:.0%})")

    print("\n  Confusion matrix (rows = expected, cols = predicted):")
    intents = sorted(report["confusion_matrix"].keys())
    print("    " + " ".join(f"{i:>8s}" for i in [""] + intents))
    for expected in intents:
        row = report["confusion_matrix"][expected]
        print(f"    {expected:>8s} " + " ".join(f"{row.get(p, 0):>8d}" for p in intents))

    if report["misses"]:
        print("\n  Misses:")
        for miss in report["misses"]:
            print(
                f"    expected={miss['expected_intent']:8s} got={miss['predicted_intent']:8s} '{miss['query']}'"
            )
    print()


async def _run(args: argparse.Namespace) -> Dict[str, Any]:
    golden_set = load_golden_set(args.golden_set)

    # Same registry the live ChatbotService registers (see chatbot.py __init__)
    # so this measures the exact routing behaviour a real chat turn gets.
    tool_registry = ToolRegistry(tools=[CurrentTimeTool()])
    router = IntentRouter(LLMProviderFactory.create(), tool_registry)
    evaluator = IntentRoutingEvaluator(router)
    return await evaluator.evaluate_all(golden_set)


def main() -> None:
    """Load the golden set, run real classification calls, print and optionally save the report."""
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--golden-set", default=DEFAULT_GOLDEN_SET_PATH, help="Path to the golden intent JSON file"
    )
    parser.add_argument("--out", default=None, help="Optional path to save the full JSON report")
    args = parser.parse_args()

    report = asyncio.run(_run(args))
    print_report(report)

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"Full report saved to {args.out}")


if __name__ == "__main__":
    main()
