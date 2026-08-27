#!/usr/bin/env python3
"""
eval_rag.py

Cheap, fast retrieval-accuracy check for the RAG pipeline.

Runs a small golden set of (query, expected_source) pairs through the same
``ContextRetriever.hybrid_search()`` the live chat path uses (see
``ChatbotService._retrieve_context`` in core/agent/chatbot.py), and reports
recall@k and MRR against the expected source folder under data/chunks/.

No LLM calls are made — this only exercises embeddings + BM25 retrieval, so
it costs nothing and runs in seconds against an already-built vector store.

Usage:
  python scripts/eval_rag.py
  python scripts/eval_rag.py --golden-set data/eval/golden_queries.json --out data/logs/eval_report.json
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import Config
from core.retrieval.retriever import ContextRetriever
from core.storage import get_vector_store_provider

logger = logging.getLogger(__name__)

DEFAULT_GOLDEN_SET_PATH = "data/eval/golden_queries.json"


class RetrievalEvaluator:
    """Runs a golden query set through hybrid search and scores recall@k / MRR."""

    def __init__(self, retriever: ContextRetriever, k: int, semantic_weight: float):
        """
        Args:
            retriever: Retriever to evaluate; shares the live vector store.
            k: Number of results requested per query, matching the live
                ``RETRIEVAL_TOP_K`` the chat path uses.
            semantic_weight: Semantic-vs-keyword fusion weight, matching the
                live ``SEMANTIC_WEIGHT``.
        """
        self._retriever = retriever
        self._k = k
        self._semantic_weight = semantic_weight

    def evaluate_one(
        self, query: str, expected_source: str, embeddings, documents: List[str]
    ) -> Dict[str, Any]:
        """
        Run one query and score it against its expected source.

        Returns:
            Dict with the query, expected source, retrieved source order,
            whether the expected source was found, and its rank if found.
        """
        results = self._retriever.hybrid_search(
            query, embeddings, documents, k=self._k, semantic_weight=self._semantic_weight
        )
        retrieved_sources = [r.get("source_id", "unknown") for r in results]
        hit = expected_source in retrieved_sources
        rank = retrieved_sources.index(expected_source) + 1 if hit else None
        return {
            "query": query,
            "expected_source": expected_source,
            "retrieved_sources": retrieved_sources,
            "hit": hit,
            "rank": rank,
        }

    def evaluate_all(
        self, golden_set: List[Dict[str, str]], embeddings, documents: List[str]
    ) -> Dict[str, Any]:
        """
        Run the full golden set and aggregate recall@k / MRR, overall and per source.

        Returns:
            Report dict with overall metrics, a per-source breakdown, the
            list of missed queries, and every individual query result.
        """
        per_query = [
            self.evaluate_one(item["query"], item["expected_source"], embeddings, documents)
            for item in golden_set
        ]

        total = len(per_query)
        hits = sum(1 for r in per_query if r["hit"])
        mrr = sum(1.0 / r["rank"] for r in per_query if r["hit"]) / total if total else 0.0

        by_source: Dict[str, Dict[str, int]] = {}
        for r in per_query:
            bucket = by_source.setdefault(r["expected_source"], {"total": 0, "hits": 0})
            bucket["total"] += 1
            bucket["hits"] += 1 if r["hit"] else 0

        return {
            "k": self._k,
            "total_queries": total,
            "recall_at_k": hits / total if total else 0.0,
            "mrr": mrr,
            "by_source": {
                source: {**stats, "recall": stats["hits"] / stats["total"]}
                for source, stats in sorted(by_source.items())
            },
            "misses": [r for r in per_query if not r["hit"]],
            "per_query": per_query,
        }


def load_golden_set(path: str) -> List[Dict[str, str]]:
    """Load the (query, expected_source) golden set from a JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def print_report(report: Dict[str, Any]) -> None:
    """Print a human-readable summary of the evaluation report."""
    print(f"\nRetrieval eval -- {report['total_queries']} queries, k={report['k']}")
    print(f"  Recall@{report['k']}: {report['recall_at_k']:.1%}")
    print(f"  MRR:        {report['mrr']:.3f}")

    print("\n  By source:")
    for source, stats in report["by_source"].items():
        print(f"    {source:6s} {stats['hits']}/{stats['total']}  ({stats['recall']:.0%})")

    if report["misses"]:
        print("\n  Misses:")
        for miss in report["misses"]:
            print(f"    [{miss['expected_source']}] '{miss['query']}' -> got {miss['retrieved_sources']}")
    print()


def main() -> None:
    """Load the vector store and golden set, run the eval, print and optionally save the report."""
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        # Diacritic-heavy Vietnamese queries/sources otherwise crash a
        # cp1252 Windows console with UnicodeEncodeError.
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--golden-set", default=DEFAULT_GOLDEN_SET_PATH, help="Path to the golden query JSON file"
    )
    parser.add_argument(
        "--k", type=int, default=None, help="Override Config.RAG.RETRIEVAL_TOP_K for this run"
    )
    parser.add_argument("--out", default=None, help="Optional path to save the full JSON report")
    args = parser.parse_args()

    golden_set = load_golden_set(args.golden_set)

    provider = get_vector_store_provider()
    data = provider.get_data()
    if data is None:
        raise SystemExit("Vector store could not be loaded -- is data/vectors populated?")
    _, embeddings, documents = data
    if not documents:
        raise SystemExit("Vector store is empty -- rebuild it first (POST /cleanup/vectors/rebuild).")

    k = args.k or Config.RAG.RETRIEVAL_TOP_K()
    evaluator = RetrievalEvaluator(
        ContextRetriever(), k=k, semantic_weight=Config.RAG.SEMANTIC_WEIGHT()
    )
    report = evaluator.evaluate_all(golden_set, embeddings, documents)

    print_report(report)

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"Full report saved to {args.out}")


if __name__ == "__main__":
    main()
