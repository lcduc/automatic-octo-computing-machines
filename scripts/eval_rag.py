"""
Retrieval eval and threshold calibration against the live knowledge base.

Runs a labelled golden set through the same retriever, models and admin
settings the chat path uses, with the relevance gates switched off, and reports:

- recall@k / MRR: does the expected document come back for answerable questions;
- for ``SIMILARITY_THRESHOLD`` (reranker score, the normal gate) and
  ``SEMANTIC_THRESHOLD`` (cosine, the gate when no reranker scored): how many
  answerable questions the current value lets through and how many
  unanswerable ones it refuses, and the value that separates the two best.

Golden set: a JSON list of ``{"query": ..., "expected_document": <document title> | null}``;
``null`` marks a question the knowledge base cannot answer, which the bot should refuse.

No LLM calls are made. Usage (from the repository root, with the venv active)::

    python -m scripts.eval_rag
    python -m scripts.eval_rag --golden-set my_set.json --out logs/eval_report.json
"""

# Standard library imports
import argparse
import asyncio
import json
import logging
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# Third-party imports
from dotenv import load_dotenv

load_dotenv()

# Local imports
from core.retrieval.knowledge_index import KnowledgeSnapshot  # noqa: E402
from core.retrieval.retriever import ContextRetriever  # noqa: E402
from models.knowledge import RetrievedChunk  # noqa: E402
from scripts.eval_baseline import EvalBaseline  # noqa: E402
from scripts.threshold_calibrator import ThresholdCalibrator  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_GOLDEN_SET_PATH = Path(__file__).parent / "demo_data" / "golden_queries.json"
#: Score of a question whose expected document (or any chunk) was not retrieved at all.
NO_MATCH = -math.inf
#: Access level of an anonymous widget visitor, which the eval asks as by default.
ANONYMOUS_ACCESS_LEVEL = 0


@dataclass(frozen=True)
class QueryResult:
    """Ungated retrieval outcome of one golden question."""

    query: str
    expected_document: Optional[str]
    #: Distinct document titles in rank order.
    documents: List[str]
    #: 1-based rank of the expected document, ``None`` when missed or unanswerable.
    rank: Optional[int]
    #: Best reranker score over the expected document's chunks (any chunk when unanswerable).
    best_rerank: Optional[float]
    #: The same for cosine similarity, from a search without the reranker.
    best_cosine: float
    #: For an unanswerable question: ``off_topic`` or ``unanswerable`` (on topic, but not in the knowledge base).
    kind: Optional[str] = None


class RetrievalEvaluator:
    """Runs golden questions through the live retriever with the relevance gates off."""

    def __init__(
        self,
        snapshot: KnowledgeSnapshot,
        reranked: Optional[ContextRetriever],
        cosine_only: ContextRetriever,
        top_k: int,
        semantic_weight: float,
        access_level: int,
    ):
        """
        Args:
            snapshot: Corpus to search.
            reranked: Retriever with the live reranker; ``None`` when reranking is off.
            cosine_only: Retriever without a reranker, as the chat path runs when reranking fails.
            top_k: Matches per question, as the live ``retrieval_top_k``.
            semantic_weight: Embedding-vs-BM25 fusion weight, as the live setting.
            access_level: Caller access level; higher-tier documents are skipped.
        """
        self._snapshot = snapshot
        self._reranked = reranked
        self._cosine_only = cosine_only
        self._top_k = top_k
        self._semantic_weight = semantic_weight
        self._access_level = access_level

    def evaluate(self, query: str, expected_document: Optional[str], kind: Optional[str] = None) -> QueryResult:
        """Score one question; the ranking comes from the reranked search when there is one."""
        cosine_matches = self._search(self._cosine_only, query)
        matches = self._search(self._reranked, query) if self._reranked else cosine_matches
        documents = list(dict.fromkeys(match.chunk.document_title for match in matches))
        rank = documents.index(expected_document) + 1 if expected_document in documents else None
        best_rerank = self._best(matches, expected_document, "rerank_score") if self._reranked else None
        return QueryResult(
            query, expected_document, documents, rank, best_rerank,
            self._best(cosine_matches, expected_document, "semantic_score"), kind,
        )

    def _search(self, retriever: ContextRetriever, query: str) -> List[RetrievedChunk]:
        """Top-k matches with every score kept: no threshold, no neighbour expansion."""
        return retriever.search(
            query, self._snapshot, top_k=self._top_k, semantic_weight=self._semantic_weight,
            threshold=NO_MATCH, semantic_threshold=NO_MATCH, max_context_chunks=self._top_k,
            expansion_radius=0, access_level=self._access_level,
        )

    @staticmethod
    def _best(matches: List[RetrievedChunk], expected_document: Optional[str], score: str) -> float:
        """Highest ``score`` among the expected document's chunks, or all chunks when none is expected."""
        scores = [
            getattr(match, score) for match in matches
            if expected_document is None or match.chunk.document_title == expected_document
        ]
        return max(scores, default=NO_MATCH)


KIND_UNANSWERABLE = "unanswerable"


def calibration(results: List[QueryResult], score: str, current: float) -> Dict[str, Any]:
    """
    Rates of the ``current`` threshold and the best one for ``score`` ("best_rerank" / "best_cosine").

    The threshold is only a floor: questions marked ``unanswerable`` (on topic, not in the knowledge
    base) overlap with answerable ones in score, so they are left out of the calibration and reported
    as ``on_topic_unanswerable_reaching_the_model``, the share that clears the threshold in force.
    """
    negatives = [r for r in results if r.expected_document is None and r.kind != KIND_UNANSWERABLE]
    on_topic = [getattr(r, score) for r in results if r.kind == KIND_UNANSWERABLE]
    calibrator = ThresholdCalibrator(
        [getattr(r, score) for r in results if r.expected_document is not None],
        [getattr(r, score) for r in negatives],
    )
    report = {"current": asdict(calibrator.rates(current)), "best": asdict(calibrator.best())}
    if on_topic:
        report["on_topic_unanswerable_reaching_the_model"] = sum(value >= current for value in on_topic) / len(on_topic)
    return report


def build_report(
    results: List[QueryResult], top_k: int, similarity_threshold: float, semantic_threshold: float, reranked: bool
) -> Dict[str, Any]:
    """Recall/MRR over the answerable questions and the calibration of both gates."""
    answerable = [r for r in results if r.expected_document is not None]
    hits = [r for r in answerable if r.rank is not None]
    total = len(answerable)
    return {
        "top_k": top_k,
        "answerable": total,
        "unanswerable": len(results) - total,
        "recall_at_k": len(hits) / total if total else 0.0,
        "mrr": sum(1 / r.rank for r in hits) / total if total else 0.0,
        "similarity_threshold": (
            calibration(results, "best_rerank", similarity_threshold) if reranked else None
        ),
        "semantic_threshold": calibration(results, "best_cosine", semantic_threshold),
        "misses": [asdict(r) for r in answerable if r.rank is None],
        "per_query": [asdict(r) for r in results],
    }


def _format_rates(label: str, rates: Dict[str, float]) -> str:
    """One line: threshold, answered share, refused share."""
    return (
        f"    {label:8s} {rates['threshold']:.3f}  answers {rates['answered']:.0%} of answerable, "
        f"refuses {rates['refused']:.0%} of unanswerable"
    )


def print_report(report: Dict[str, Any]) -> None:
    """Print a human-readable summary of the report."""
    print(f"\nRetrieval: {report['answerable']} answerable + {report['unanswerable']} unanswerable questions, "
          f"k={report['top_k']}")
    print(f"  Recall@{report['top_k']}: {report['recall_at_k']:.1%}   MRR: {report['mrr']:.3f}")
    for name, label in (("similarity_threshold", "SIMILARITY_THRESHOLD (reranker)"),
                        ("semantic_threshold", "SEMANTIC_THRESHOLD (cosine, no reranker)")):
        print(f"\n  {label}")
        gate = report[name]
        if gate is None:
            print("    reranking is off; not calibrated")
            continue
        print(_format_rates("current", gate["current"]))
        print(_format_rates("best", gate["best"]))
        if "on_topic_unanswerable_reaching_the_model" in gate:
            print(f"    on-topic unanswerable questions that clear the current threshold (the model decides): "
                  f"{gate['on_topic_unanswerable_reaching_the_model']:.0%}")
    if report["misses"]:
        print("\n  Expected document not retrieved:")
        for miss in report["misses"]:
            print(f"    '{miss['query']}' -> {miss['documents']}")
    print()


def load_golden_set(path: Path) -> List[Dict[str, Optional[str]]]:
    """Load the ``[{"query", "expected_document"}]`` golden set."""
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


async def run(golden_set: List[Dict[str, Optional[str]]], access_level: int) -> Dict[str, Any]:
    """Start the app services, evaluate every question, and build the report."""
    from api.container import AppContainer
    from config.settings import Config

    container = AppContainer()
    await container.start()
    try:
        snapshot = container.index.snapshot
        if snapshot.is_empty:
            raise SystemExit("The knowledge base is empty; add documents first (e.g. python -m scripts.seed_demo documents).")
        titles = {chunk.document_title for chunk in snapshot.chunks}
        unknown = {item["expected_document"] for item in golden_set} - titles - {None}
        if unknown:
            logger.warning("Golden set names documents not in the knowledge base: %s", sorted(unknown))

        policy = container.settings.chat_policy()
        reranked = ContextRetriever(container.embedding, container.reranker) if container.reranker else None
        evaluator = RetrievalEvaluator(
            snapshot, reranked, ContextRetriever(container.embedding, None),
            policy.retrieval_top_k, policy.semantic_weight, access_level,
        )
        logger.info("Evaluating %d questions (reranker %s)", len(golden_set), "on" if reranked else "off")
        results = [
            await asyncio.to_thread(evaluator.evaluate, item["query"], item["expected_document"], item.get("kind"))
            for item in golden_set
        ]
        return build_report(
            results, policy.retrieval_top_k, Config.RAG.SIMILARITY_THRESHOLD(),
            Config.RAG.SEMANTIC_THRESHOLD(), reranked is not None,
        )
    finally:
        await container.stop()


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point; returns the exit code."""
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        # Vietnamese titles otherwise crash a cp1252 Windows console with UnicodeEncodeError.
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--golden-set", type=Path, default=DEFAULT_GOLDEN_SET_PATH, help="Golden set JSON file")
    parser.add_argument("--access-level", type=int, default=ANONYMOUS_ACCESS_LEVEL,
                        help="Ask as this access level (default: anonymous visitor)")
    parser.add_argument("--out", type=Path, default=None, help="Also save the full JSON report here")
    parser.add_argument("--check", action="store_true", help="Fail (exit 1) when recall/MRR regress against the committed baseline")
    parser.add_argument("--write-baseline", action="store_true", help="Record this report as the baseline (then commit the file)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    report = asyncio.run(run(load_golden_set(args.golden_set), args.access_level))
    print_report(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as file:
            json.dump(report, file, ensure_ascii=False, indent=2, default=str)
        print(f"Full report saved to {args.out}")
    baseline, name = EvalBaseline(), args.golden_set.stem
    if args.write_baseline:
        baseline.write(name, baseline.retrieval_values(report))
        print("Baseline written; commit scripts/demo_data/eval_baseline.json")
    if args.check:
        problems = baseline.check_retrieval(name, report)
        for problem in problems:
            print(f"REGRESSION: {problem}")
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
