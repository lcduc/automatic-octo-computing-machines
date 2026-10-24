"""
Retrieval metrics of one embedding variant on the human golden sets: dense only and the full stack.

Reports document-level Recall@1, Recall@5 and MRR@10 (``top_k`` 10 chunks) over the answerable
questions, per golden set and for the dev / holdout groups, twice:

- ``dense``: cosine ranking only (no BM25, no reranker), the stage a query adapter or a
  fine-tuned embedding model changes directly;
- ``full``: the live semantic weight, BM25 fusion and the cross-encoder reranker.

The variant under test is whatever the environment configures: ``EMBEDDING_MODEL``,
``QUERY_ADAPTER_PATH`` and ``DATABASE_URL``. Starting the app re-embeds every chunk whose stored
model differs from ``EMBEDDING_MODEL``, so the run refuses a database embedded with another model
unless ``--allow-reembed`` is given (point ``DATABASE_URL`` at a copy, never at the live database).

No LLM calls are made. Usage (from the repository root, with the venv active)::

    python -m scripts.eval_retrieval_variants --label baseline --out logs/variants/baseline.json
"""

# Standard library imports
import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# Third-party imports
from dotenv import load_dotenv
from sqlalchemy import text

load_dotenv()

# Local imports
from core.retrieval.retriever import ContextRetriever  # noqa: E402
from scripts.eval_rag import ANONYMOUS_ACCESS_LEVEL, QueryResult, RetrievalEvaluator, load_golden_set  # noqa: E402

logger = logging.getLogger(__name__)

DEMO_DATA_DIR = Path(__file__).parent / "demo_data"
#: Golden sets per group; the holdout group is never looked at while tuning.
GROUPS = {
    "dev": ("golden_queries", "golden_colloquial_dev"),
    "holdout": ("golden_colloquial_holdout",),
}
#: Chunks retrieved per question; documents are ranked by their first chunk among them.
EVAL_TOP_K = 10
#: Fusion weight that turns the hybrid search into a pure cosine ranking.
DENSE_ONLY_WEIGHT = 1.0
RECALL_CUTOFFS = (1, 5)


def metrics(results: Sequence[QueryResult]) -> Dict[str, float]:
    """Recall@1/@5 and MRR (over the top-k documents) of the answerable questions; rank is ``None`` when missed."""
    answerable = [result for result in results if result.expected_document is not None]
    total = len(answerable)
    report: Dict[str, float] = {"answerable": total}
    for cutoff in RECALL_CUTOFFS:
        hits = sum(1 for result in answerable if result.rank is not None and result.rank <= cutoff)
        report[f"recall_at_{cutoff}"] = hits / total if total else 0.0
    report["mrr"] = (
        sum(1 / result.rank for result in answerable if result.rank is not None) / total if total else 0.0
    )
    return report


class VariantEvaluator:
    """Runs every golden set through the dense-only and the full retrieval of the running app."""

    def __init__(self, dense: RetrievalEvaluator, full: Optional[RetrievalEvaluator]):
        """
        Args:
            dense: Evaluator over the cosine-only retriever with the dense-only weight.
            full: Evaluator over the live hybrid + reranker retrieval; ``None`` when reranking is off.
        """
        self._modes = {"dense": dense, **({"full": full} if full else {})}

    def evaluate(self, golden_sets: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """
        Score each mode on each golden set, then on the groups and on everything.

        Returns:
            ``{mode: {set or group name: metrics}}`` plus the per-question ranks under ``per_query``.
        """
        report: Dict[str, Any] = {"per_query": {}}
        for mode, evaluator in self._modes.items():
            by_set = {
                name: [evaluator.evaluate(item["query"], item["expected_document"], item.get("kind")) for item in items]
                for name, items in golden_sets.items()
            }
            scores = {name: metrics(results) for name, results in by_set.items()}
            for group, members in GROUPS.items():
                scores[group] = metrics([r for name in members if name in by_set for r in by_set[name]])
            scores["all"] = metrics([r for results in by_set.values() for r in results])
            report[mode] = scores
            report["per_query"][mode] = {
                name: [{"query": r.query, "expected": r.expected_document, "rank": r.rank} for r in results]
                for name, results in by_set.items()
            }
        return report


async def stored_embedding_models(container) -> List[str]:
    """Distinct embedding models of the chunks in the configured database."""
    container.database.connect()
    async with container.database.session() as session:
        rows = await session.execute(text("SELECT DISTINCT embedding_model FROM knowledge_chunks"))
        return sorted(str(row[0]) for row in rows)


async def run(golden_sets: Dict[str, List[Dict[str, Any]]], top_k: int, allow_reembed: bool) -> Dict[str, Any]:
    """Start the app services against the configured database and evaluate the variant."""
    from api.container import AppContainer
    from config.settings import Config

    container = AppContainer()
    model = Config.LLM.EMBEDDING_MODEL()
    stored = await stored_embedding_models(container)
    if stored != [model] and not allow_reembed:
        raise SystemExit(
            f"The database holds embeddings of {stored}, not {model!r}; starting the app would re-embed it. "
            "Point DATABASE_URL at a copy and pass --allow-reembed."
        )
    await container.start()
    try:
        snapshot = container.index.snapshot
        if snapshot.is_empty:
            raise SystemExit("The knowledge base is empty; seed it first (python -m scripts.seed_demo documents).")
        policy = container.settings.chat_policy()
        cosine_only = ContextRetriever(container.embedding, None)
        dense = RetrievalEvaluator(snapshot, None, cosine_only, top_k, DENSE_ONLY_WEIGHT, ANONYMOUS_ACCESS_LEVEL)
        full = (
            RetrievalEvaluator(
                snapshot, ContextRetriever(container.embedding, container.reranker), cosine_only,
                top_k, policy.semantic_weight, ANONYMOUS_ACCESS_LEVEL,
            )
            if container.reranker
            else None
        )
        logger.info("Evaluating %s over %d chunks (reranker %s)", model, len(snapshot.chunks), "on" if full else "off")
        report = await asyncio.to_thread(VariantEvaluator(dense, full).evaluate, golden_sets)
        report["config"] = {
            "embedding_model": model,
            "query_adapter": Config.RAG.QUERY_ADAPTER_PATH() if Path(Config.RAG.QUERY_ADAPTER_PATH()).exists() else None,
            "top_k": top_k,
            "semantic_weight": policy.semantic_weight,
            "reranker": Config.RAG.RERANKER_MODEL() if full else None,
            "chunks": len(snapshot.chunks),
        }
        return report
    finally:
        await container.stop()


def print_report(label: str, report: Dict[str, Any]) -> None:
    """One table per mode (intentional CLI output)."""
    print(f"\n{label}: {report['config']['embedding_model']}, adapter {report['config']['query_adapter']}")
    for mode in ("dense", "full"):
        if mode not in report:
            continue
        mrr_label = f"MRR@{report['config']['top_k']}"
        print(f"\n  {mode:<28}{'n':>4}{'R@1':>8}{'R@5':>8}{mrr_label:>9}")
        for name, scores in report[mode].items():
            print(
                f"  {name:<28}{scores['answerable']:>4}{scores['recall_at_1']:>8.1%}"
                f"{scores['recall_at_5']:>8.1%}{scores['mrr']:>9.3f}"
            )
    print()


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point; returns the exit code."""
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", default="variant", help="Name printed with the results")
    parser.add_argument("--top-k", type=int, default=EVAL_TOP_K)
    parser.add_argument("--out", type=Path, default=None, help="Also save the full JSON report here")
    parser.add_argument("--allow-reembed", action="store_true",
                        help="Let the app re-embed a database embedded with another model")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    names = [name for members in GROUPS.values() for name in members]
    golden_sets = {name: load_golden_set(DEMO_DATA_DIR / f"{name}.json") for name in names}
    report = asyncio.run(run(golden_sets, args.top_k, args.allow_reembed))
    report["label"] = args.label
    print_report(args.label, report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Full report saved to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
