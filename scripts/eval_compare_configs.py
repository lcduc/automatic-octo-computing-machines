#!/usr/bin/env python3
"""
eval_compare_configs.py

Compares retrieval quality between a vector-only baseline and the full
hybrid + cross-encoder rerank + query-adapter configuration, on the same
golden query set, using the same ``RetrievalEvaluator`` as eval_rag.py.

No LLM calls are made — this only exercises embeddings + BM25 + reranking,
so it costs nothing and runs in seconds against an already-built vector store
and an already-fitted query adapter (see scripts/build_query_adapter.py).

Usage:
  python scripts/eval_compare_configs.py
  python scripts/eval_compare_configs.py --golden-set data/eval/golden_queries.json --out data/logs/config_comparison.json
"""
import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import Config
from core.retrieval.embeddings import EmbeddingService
from core.retrieval.retriever import ContextRetriever
from core.storage import get_vector_store_provider
from scripts.eval_rag import DEFAULT_GOLDEN_SET_PATH, RetrievalEvaluator, load_golden_set

logger = logging.getLogger(__name__)

#: Path guaranteed not to exist, used to force a no-op adapter load.
_ADAPTER_DISABLED_SENTINEL_PATH = "data/vectors/__disabled_for_eval__.npy"

_COMPARISON_METRICS = ("recall_at_k", "precision_at_k", "mrr")


@dataclass(frozen=True)
class RetrievalRunConfig:
    """One named retrieval configuration to evaluate."""

    name: str
    semantic_weight: float
    reranking_enabled: bool
    query_adapter_path: Optional[str]  # None disables the adapter for this run


class ConfigComparisonRunner:
    """Runs the same golden query set under several retrieval configs and diffs the results."""

    def __init__(self, k: int):
        """
        Args:
            k: Chunks requested per query, shared across every config so the
                comparison isolates fusion/rerank/adapter behaviour only.
        """
        self._k = k

    def run(self, config: RetrievalRunConfig, golden_set, embeddings, documents) -> Dict[str, Any]:
        """
        Evaluate one configuration end to end.

        The reranker toggle and the query adapter are process-wide state
        (``Config.RAG.RERANKING_ENABLED`` is read fresh per ``ContextRetriever``
        construction; the adapter matrix lives on the ``EmbeddingService``
        class). Both are reset here before building a fresh retriever so each
        run reflects exactly the config it was given, regardless of which
        config ran before it in this process.

        Returns:
            The evaluator's report dict, tagged with the config that produced it.
        """
        os.environ["RERANKING_ENABLED"] = "true" if config.reranking_enabled else "false"

        EmbeddingService.clear_query_adapter()
        os.environ["QUERY_ADAPTER_PATH"] = (
            config.query_adapter_path if config.query_adapter_path else _ADAPTER_DISABLED_SENTINEL_PATH
        )

        retriever = ContextRetriever()
        evaluator = RetrievalEvaluator(retriever, k=self._k, semantic_weight=config.semantic_weight)
        report = evaluator.evaluate_all(golden_set, embeddings, documents)
        report["config"] = {
            "name": config.name,
            "semantic_weight": config.semantic_weight,
            "reranking_enabled": config.reranking_enabled,
            "query_adapter_enabled": config.query_adapter_path is not None,
        }
        return report

    @staticmethod
    def summarize(baseline: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compare ``candidate`` against ``baseline`` for every comparison metric.

        Returns:
            Dict keyed by metric name, each with the raw baseline/candidate
            values plus the absolute and relative (percentage) improvement.
        """
        def relative_improvement(base: float, new: float) -> Optional[float]:
            if base <= 0:
                return None
            return (new - base) / base * 100.0

        return {
            metric: {
                "baseline": baseline[metric],
                "candidate": candidate[metric],
                "absolute_delta": candidate[metric] - baseline[metric],
                "relative_improvement_pct": relative_improvement(baseline[metric], candidate[metric]),
            }
            for metric in _COMPARISON_METRICS
        }


def print_comparison(vector_only: Dict[str, Any], summary: Dict[str, Any]) -> None:
    """Print a human-readable side-by-side comparison table."""
    print(f"\nConfig comparison -- {vector_only['total_queries']} queries, k={vector_only['k']}\n")
    header = f"  {'metric':<14}{'vector-only':>14}{'hybrid+rerank+adapter':>24}{'relative gain':>16}"
    print(header)
    print("  " + "-" * (len(header) - 2))

    labels = {"recall_at_k": "Recall@k", "precision_at_k": "Precision@k", "mrr": "MRR"}
    for metric, label in labels.items():
        stats = summary[metric]
        gain = stats["relative_improvement_pct"]
        gain_str = f"{gain:+.1f}%" if gain is not None else "n/a"
        is_ratio = metric != "mrr"
        base_str = f"{stats['baseline']:.1%}" if is_ratio else f"{stats['baseline']:.3f}"
        cand_str = f"{stats['candidate']:.1%}" if is_ratio else f"{stats['candidate']:.3f}"
        print(f"  {label:<14}{base_str:>14}{cand_str:>24}{gain_str:>16}")
    print()


def main() -> None:
    """Load the vector store and golden set, run both configs, print and optionally save the comparison."""
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
    parser.add_argument("--out", default=None, help="Optional path to save the full JSON comparison report")
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

    vector_only_config = RetrievalRunConfig(
        name="vector_only", semantic_weight=1.0, reranking_enabled=False, query_adapter_path=None
    )
    full_config = RetrievalRunConfig(
        name="hybrid_rerank_adapter",
        semantic_weight=Config.RAG.SEMANTIC_WEIGHT(),
        reranking_enabled=True,
        query_adapter_path=Config.RAG.QUERY_ADAPTER_PATH(),
    )

    runner = ConfigComparisonRunner(k=k)
    vector_only_report = runner.run(vector_only_config, golden_set, embeddings, documents)
    full_report = runner.run(full_config, golden_set, embeddings, documents)
    summary = ConfigComparisonRunner.summarize(vector_only_report, full_report)

    print_comparison(vector_only_report, summary)

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        combined = {"vector_only": vector_only_report, "full": full_report, "summary": summary}
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(combined, f, ensure_ascii=False, indent=2)
        print(f"Full comparison report saved to {args.out}")


if __name__ == "__main__":
    main()
