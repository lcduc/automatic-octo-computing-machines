"""
End-to-end outcome eval: what the chat pipeline actually does with a labelled question set.

Runs golden sets (``[{"query", "expected_document", "kind"?}]``, the same files as ``eval_rag``)
through the real pipeline with the real models and the configured LLM, one fresh conversation per
question, and reports where each kind of question ends up:

- answerable questions should be answered (the ``[NO_ANSWER]`` marker wrongly firing is a miss);
- ``unanswerable`` questions (on topic, not in the knowledge base) should not be answered, and should reach staff;
- ``off_topic`` questions should be refused.

This calls the LLM (a few cents for ~60 questions). Usage (from the repository root, venv active)::

    python -m scripts.eval_chat_outcomes
    python -m scripts.eval_chat_outcomes --golden-set scripts/demo_data/golden_colloquial_holdout.json --out logs/outcomes.json
"""

# Standard library imports
import argparse
import asyncio
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

# Third-party imports
from dotenv import load_dotenv

load_dotenv()

# Local imports
from models.chat_turn import ChatPolicy, TurnOutcome, TurnRequest, TurnResult  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_GOLDEN_SETS = [
    Path(__file__).parent / "demo_data" / "golden_colloquial_dev.json",
    Path(__file__).parent / "demo_data" / "golden_colloquial_holdout.json",
]
KIND_ANSWERABLE = "answerable"
KIND_UNANSWERABLE = "unanswerable"
KIND_OFF_TOPIC = "off_topic"
#: Pipeline routes that mean "refused as off topic" and "nothing found, on topic".
ROUTE_OFF_TOPIC = "off_topic"


class OutcomeEvaluator:
    """Runs questions through a pipeline and tallies the outcomes per kind of question."""

    def __init__(self, pipeline, policy: ChatPolicy):
        """
        Args:
            pipeline: The assembled ``ChatbotService``.
            policy: Chat behaviour to ask under (the admin-saved one).
        """
        self._pipeline = pipeline
        self._policy = policy

    async def ask(self, query: str) -> Dict[str, Any]:
        """One question in a fresh conversation: its outcome, route and (if any) rewritten query."""
        request = TurnRequest(query=query, history=[], policy=self._policy)
        result: Optional[TurnResult] = None
        async for event in self._pipeline.run(request):
            if isinstance(event, TurnResult):
                result = event
        assert result is not None
        return {
            "query": query,
            "outcome": result.outcome.value,
            "route": request.trace.route,
            "rewritten": result.rewritten_query,
            "handoff_reason": result.handoff_reason.value if result.handoff_reason else None,
        }

    async def evaluate(self, golden: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Ask every question; returns the per-kind tallies and the questions that went wrong."""
        rows = []
        for item in golden:
            kind = item.get("kind") or (KIND_ANSWERABLE if item["expected_document"] else KIND_OFF_TOPIC)
            rows.append({**await self.ask(item["query"]), "kind": kind})
        return {
            "questions": len(rows),
            "by_kind": {
                kind: dict(Counter(self._verdict(row) for row in rows if row["kind"] == kind))
                for kind in (KIND_ANSWERABLE, KIND_UNANSWERABLE, KIND_OFF_TOPIC)
            },
            "wrong": [row for row in rows if self._verdict(row) == "wrong"],
            "rows": rows,
        }

    @staticmethod
    def _verdict(row: Dict[str, Any]) -> str:
        """``right`` or ``wrong`` for the row's kind, with the way it was right or wrong."""
        answered = row["outcome"] == TurnOutcome.ANSWERED.value
        if row["kind"] == KIND_ANSWERABLE:
            return "right" if answered else "wrong"
        if row["kind"] == KIND_UNANSWERABLE:
            return "wrong" if answered else "right"
        return "right" if row["route"] == ROUTE_OFF_TOPIC else ("wrong" if answered else "refused_other_way")


def print_report(report: Dict[str, Any]) -> None:
    """Human-readable summary (intentional CLI output)."""
    print(f"\nOutcomes for {report['questions']} questions")
    for kind, tally in report["by_kind"].items():
        total = sum(tally.values())
        print(f"  {kind:<13} {total:>3}  " + "  ".join(f"{name} {count}" for name, count in sorted(tally.items())))
    for row in report["wrong"]:
        print(f"    wrong [{row['kind']}] {row['query'][:70]!r} -> {row['outcome']} via {row['route']}")


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point; returns the exit code."""
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--golden-set", type=Path, action="append", help="Golden set JSON (repeatable); default: dev + holdout")
    parser.add_argument("--out", type=Path, default=None, help="Save the full JSON report here")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    golden: List[Dict[str, Any]] = []
    for path in args.golden_set or DEFAULT_GOLDEN_SETS:
        golden.extend(json.loads(path.read_text(encoding="utf-8")))
    report = asyncio.run(_run(golden))
    print_report(report)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nFull report saved to {args.out}")
    return 0


async def _run(golden: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Start the real container, evaluate, stop it."""
    from api.container import AppContainer

    container = AppContainer()
    await container.start()
    try:
        return await OutcomeEvaluator(container.pipeline, container.settings.chat_policy()).evaluate(golden)
    finally:
        await container.stop()


if __name__ == "__main__":
    sys.exit(main())
