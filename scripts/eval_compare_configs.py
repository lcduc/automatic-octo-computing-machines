"""
Retrieval config comparison: one golden set through several retrieval configurations in one process.

Runs against the live knowledge base, scored by the same ``RetrievalEvaluator`` and
``build_report`` as ``scripts/eval_rag.py`` (document-level recall@k and MRR over the
answerable questions). The configurations, each against the one before:

- ``dense_only``: embedding search alone (fusion weight 1.0), no re-ranker;
- ``hybrid``: embedding + BM25 fusion at the live weight, no re-ranker;
- ``hybrid_rerank``: that plus the cross-encoder re-ranker (needs ``RERANKING_ENABLED``);
- ``hybrid_rerank_adapter``: that plus the query adapter, when ``QUERY_ADAPTER_PATH`` holds one.

No LLM calls are made. Needs the database and the in-process models: leave ``MODEL_SERVER_URL``
empty, because a model-server applies its own query adapter. Usage (from the repository root,
with the venv active)::

    python -m scripts.eval_compare_configs
    python -m scripts.eval_compare_configs --golden-set scripts/demo_data/golden_colloquial_holdout.json --k 10 --out logs/config_comparison.json
"""

# Standard library imports
import argparse
import asyncio
import json
import logging
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# Third-party imports
from dotenv import load_dotenv

load_dotenv()

# Local imports
from config.settings import Config  # noqa: E402
from core.retrieval.embeddings import EmbeddingService  # noqa: E402
from core.retrieval.knowledge_index import KnowledgeSnapshot  # noqa: E402
from core.retrieval.retriever import ContextRetriever  # noqa: E402
from scripts.eval_rag import (  # noqa: E402
    ANONYMOUS_ACCESS_LEVEL, DEFAULT_GOLDEN_SET_PATH, RetrievalEvaluator, build_report, load_golden_set,
)

logger = logging.getLogger(__name__)

#: Report fields compared between configurations.
COMPARISON_METRICS = ("recall_at_k", "mrr")
#: Fusion weight that leaves BM25 out of the ranking entirely.
DENSE_ONLY_WEIGHT = 1.0


@dataclass(frozen=True)
class RetrievalRunConfig:
    """One named retrieval configuration to evaluate."""

    name: str
    semantic_weight: float
    reranking_enabled: bool
    query_adapter_path: Optional[str] = None  # None runs without the adapter


def comparison_configs(
    semantic_weight: float, reranker_available: bool, adapter_path: Optional[str]
) -> List[RetrievalRunConfig]:
    """
    The configurations to compare, each adding one component to the one before.

    Args:
        semantic_weight: The live embedding-vs-BM25 fusion weight.
        reranker_available: Whether the app loaded a re-ranker; without one the re-ranked configs are skipped.
        adapter_path: A fitted query adapter file, or ``None`` when there is none.
    """
    configs = [
        RetrievalRunConfig("dense_only", DENSE_ONLY_WEIGHT, reranking_enabled=False),
        RetrievalRunConfig("hybrid", semantic_weight, reranking_enabled=False),
    ]
    if reranker_available:
        configs.append(RetrievalRunConfig("hybrid_rerank", semantic_weight, reranking_enabled=True))
        if adapter_path:
            configs.append(RetrievalRunConfig(
                "hybrid_rerank_adapter", semantic_weight, reranking_enabled=True, query_adapter_path=adapter_path,
            ))
    return configs


class ConfigComparisonRunner:
    """Runs the same golden set under several retrieval configs over one loaded snapshot and models."""

    def __init__(self, snapshot: KnowledgeSnapshot, embedding: EmbeddingService, reranker: Any,
                 top_k: int, access_level: int):
        """
        Args:
            snapshot: Corpus to search, shared by every configuration.
            embedding: The in-process embedding service (it holds the process-wide query adapter).
            reranker: The app's re-ranker, or ``None`` when reranking is off.
            top_k: Matches per question, shared so the comparison isolates fusion, re-ranking and adapter.
            access_level: Caller access level; higher-tier documents are skipped.
        """
        self._snapshot = snapshot
        self._embedding = embedding
        self._reranker = reranker
        self._top_k = top_k
        self._access_level = access_level

    async def run(self, config: RetrievalRunConfig, golden_set: List[Dict[str, Optional[str]]]) -> Dict[str, Any]:
        """
        Evaluate one configuration.

        The query adapter is process-wide state the app loads at start-up, so it is
        cleared first and reloaded only for a configuration that asks for it.

        Returns:
            ``build_report``'s report, tagged with the config that produced it.
        """
        EmbeddingService.clear_query_adapter()
        if config.query_adapter_path and not self._embedding.load_query_adapter(config.query_adapter_path):
            raise SystemExit(f"Could not load the query adapter from {config.query_adapter_path}")
        reranked = ContextRetriever(self._embedding, self._reranker) if config.reranking_enabled else None
        evaluator = RetrievalEvaluator(
            self._snapshot, reranked, ContextRetriever(self._embedding, None),
            self._top_k, config.semantic_weight, self._access_level,
        )
        logger.info("Evaluating %d questions with %s", len(golden_set), config.name)
        results = [
            await asyncio.to_thread(evaluator.evaluate, item["query"], item["expected_document"], item.get("kind"))
            for item in golden_set
        ]
        report = build_report(
            results, self._top_k, Config.RAG.SIMILARITY_THRESHOLD(), Config.RAG.SEMANTIC_THRESHOLD(), reranked is not None,
        )
        report["config"] = asdict(config)
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
            for metric in COMPARISON_METRICS
        }


async def compare(golden_set: List[Dict[str, Optional[str]]], k: Optional[int], access_level: int) -> Dict[str, Any]:
    """Start the app services once, run every configuration, and diff each against ``dense_only``."""
    from api.container import AppContainer

    container = AppContainer()
    await container.start()
    try:
        if not isinstance(container.embedding, EmbeddingService):
            raise SystemExit("Comparing configs needs the in-process models: unset MODEL_SERVER_URL.")
        snapshot = container.index.snapshot
        if snapshot.is_empty:
            raise SystemExit("The knowledge base is empty; add documents first (e.g. python -m scripts.seed_demo documents).")
        policy = container.settings.chat_policy()
        top_k = k or policy.retrieval_top_k
        adapter_path = Config.RAG.QUERY_ADAPTER_PATH()
        if not Path(adapter_path).is_file():
            logger.info("No query adapter at %s; skipping the adapter configuration", adapter_path)
            adapter_path = None
        if container.reranker is None:
            logger.warning("No re-ranker loaded (RERANKING_ENABLED off or load failed); skipping re-ranked configurations")

        runner = ConfigComparisonRunner(snapshot, container.embedding, container.reranker, top_k, access_level)
        configs = comparison_configs(policy.semantic_weight, container.reranker is not None, adapter_path)
        reports = {config.name: await runner.run(config, golden_set) for config in configs}
    finally:
        await container.stop()

    baseline = reports["dense_only"]
    return {
        "top_k": top_k,
        "answerable": baseline["answerable"],
        "reports": reports,
        "vs_dense_only": {
            name: ConfigComparisonRunner.summarize(baseline, report) for name, report in reports.items() if name != "dense_only"
        },
    }


def print_comparison(comparison: Dict[str, Any]) -> None:
    """Print one row per configuration with its recall, MRR and gain over ``dense_only``."""
    print(f"\nConfig comparison: {comparison['answerable']} answerable questions, k={comparison['top_k']}\n")
    header = f"  {'config':<24}{'weight':>8}{'Recall@k':>11}{'MRR':>8}{'MRR vs dense':>15}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for name, report in comparison["reports"].items():
        gain = comparison["vs_dense_only"].get(name, {}).get("mrr", {}).get("relative_improvement_pct")
        gain_text = "" if name == "dense_only" else (f"{gain:+.1f}%" if gain is not None else "n/a")
        print(f"  {name:<24}{report['config']['semantic_weight']:>8.2f}{report['recall_at_k']:>11.1%}"
              f"{report['mrr']:>8.3f}{gain_text:>15}")
    print()


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point; returns the exit code."""
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        # Vietnamese titles otherwise crash a cp1252 Windows console with UnicodeEncodeError.
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--golden-set", type=Path, default=DEFAULT_GOLDEN_SET_PATH, help="Golden set JSON file")
    parser.add_argument("--k", type=int, default=None, help="Matches per question (default: the live retrieval_top_k)")
    parser.add_argument("--access-level", type=int, default=ANONYMOUS_ACCESS_LEVEL,
                        help="Ask as this access level (default: anonymous visitor)")
    parser.add_argument("--out", type=Path, default=None, help="Also save the full JSON comparison here")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    comparison = asyncio.run(compare(load_golden_set(args.golden_set), args.k, args.access_level))
    print_comparison(comparison)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as file:
            json.dump(comparison, file, ensure_ascii=False, indent=2)
        print(f"Full comparison saved to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
