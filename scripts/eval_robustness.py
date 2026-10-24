"""
Robustness eval: how the router and retrieval hold up on messy Vietnamese input.

Every case of the router eval (``router_eval.json`` plus the three golden sets, labelled as in
``eval_router``) and every answerable golden question is run clean and under each perturbation of
``scripts/vietnamese_perturber.py`` (seeded, so every run sees the same variants). Messages reach the
router and the retriever as in the chat pipeline: chat shorthands written out first
(``TextUtils.expand_chat_abbreviations``). Reports:

- router: accuracy, macro-F1 over the six routes, real questions stolen by a shortcut, off-topic caught;
- retrieval, document level over the top 10 chunks: Recall@1, Recall@5 and MRR@10 for

  - ``dense``  (SEMANTIC_WEIGHT=1.0, no reranker), ``bm25`` (0.0) and ``hybrid`` (0.7): the order of the
    fused score itself, i.e. the ranking the reranker's pool is cut from. The live no-reranker path
    re-sorts that pool by cosine, which would make all three nearly the same ranking;
  - ``full`` (0.7 + reranker): the live ``ContextRetriever.search`` with the relevance gates off;
- how many questions would trigger the LLM accent-restoring rewrite (``looks_like_unaccented_vietnamese``),
  which this eval does not run (no LLM calls are made).

Usage (from the repository root, with the venv active and the demo knowledge base seeded)::

    python -m scripts.eval_robustness
    python -m scripts.eval_robustness --only router --out logs/robustness_router.json
"""

# Standard library imports
import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# Third-party imports
import numpy as np
from dotenv import load_dotenv
from sklearn.metrics import f1_score

load_dotenv()

# Local imports
from core.routing.embedding_router import EmbeddingRouter, RouteIntent  # noqa: E402
from scripts import vietnamese_perturber  # noqa: E402
from scripts.eval_rag import ANONYMOUS_ACCESS_LEVEL, RetrievalEvaluator  # noqa: E402
from scripts.eval_router import DEFAULT_EVAL_SET_PATH, golden_to_router_cases  # noqa: E402
from scripts.vietnamese_perturber import VietnamesePerturber  # noqa: E402
from utils.text_utils import TextUtils  # noqa: E402

logger = logging.getLogger(__name__)

DEMO_DATA = Path(__file__).parent / "demo_data"
GOLDEN_SET_PATHS = tuple(
    DEMO_DATA / name for name in ("golden_queries.json", "golden_colloquial_dev.json", "golden_colloquial_holdout.json")
)
CLEAN = "clean"
#: Chunks retrieved per question; documents are ranked by their first chunk among them.
TOP_K = 10
RECALL_CUTOFFS = (1, 5)
ROUTE_LABELS = [route.value for route in RouteIntent]


@dataclass(frozen=True)
class RetrievalConfig:
    """One retrieval setup under test."""

    name: str
    semantic_weight: float
    reranked: bool


RETRIEVAL_CONFIGS = (
    RetrievalConfig("dense", 1.0, False),
    RetrievalConfig("bm25", 0.0, False),
    RetrievalConfig("hybrid", 0.7, False),
    RetrievalConfig("full", 0.7, True),
)


def load_router_cases() -> List[Dict[str, str]]:
    """The 189 labelled router messages: the router eval set plus the three golden sets."""
    cases = json.loads(DEFAULT_EVAL_SET_PATH.read_text(encoding="utf-8"))
    for path in GOLDEN_SET_PATHS:
        cases += golden_to_router_cases(json.loads(path.read_text(encoding="utf-8")))
    return cases


def load_answerable() -> List[Dict[str, str]]:
    """The answerable golden questions (those with an expected document)."""
    items = []
    for path in GOLDEN_SET_PATHS:
        items += [item for item in json.loads(path.read_text(encoding="utf-8")) if item["expected_document"]]
    return items


def router_metrics(expected: Sequence[str], decided: Sequence[str]) -> Dict[str, Any]:
    """Accuracy, macro-F1 over the six routes, stolen questions and off-topic catches of route decisions."""
    expected, decided = [str(route) for route in expected], [str(route) for route in decided]
    pairs = list(zip(expected, decided))
    correct = sum(want == got for want, got in pairs)
    rag, off = RouteIntent.RAG_QUESTION.value, RouteIntent.OFF_TOPIC.value
    return {
        "cases": len(pairs),
        "correct": correct,
        "accuracy": correct / len(pairs),
        "macro_f1": float(f1_score(expected, decided, labels=ROUTE_LABELS, average="macro", zero_division=0)),
        "questions": expected.count(rag),
        "questions_stolen": sum(want == rag and got != rag for want, got in pairs),
        "off_topic": expected.count(off),
        "off_topic_caught": sum(want == off and got == off for want, got in pairs),
    }


class RetrievalRobustness:
    """Ranks the expected document of each answerable question under every retrieval config."""

    def __init__(self, snapshot, embedding, reranker, access_level: int = ANONYMOUS_ACCESS_LEVEL):
        """
        Args:
            snapshot: The knowledge snapshot to search.
            embedding: The retriever's embedding service.
            reranker: The live reranker, or ``None`` when it is not available (``full`` is then skipped).
            access_level: Caller access level, as in ``eval_rag``.
        """
        from core.retrieval.retriever import ContextRetriever

        self._snapshot = snapshot
        self._fusion = ContextRetriever(embedding, None)
        self._reranked = ContextRetriever(embedding, reranker) if reranker is not None else None
        self._candidates = snapshot.visible(np.arange(len(snapshot.chunks)), access_level, date.today())
        self._access_level = access_level

    def configs(self) -> List[RetrievalConfig]:
        """The configs this run can score."""
        return [config for config in RETRIEVAL_CONFIGS if not config.reranked or self._reranked is not None]

    def documents(self, query: str, config: RetrievalConfig) -> List[str]:
        """Distinct document titles of the top :data:`TOP_K` chunks, best first."""
        if config.reranked:
            evaluator = RetrievalEvaluator(
                self._snapshot, self._reranked, self._fusion, TOP_K, config.semantic_weight, self._access_level
            )
            return evaluator.evaluate(query, None).documents
        # The fused score before the no-reranker path re-sorts the pool by cosine.
        _, _, fused = self._fusion._hybrid_scores(query, self._snapshot, self._candidates, config.semantic_weight)
        ranked = [position for position in np.argsort(-fused, kind="stable") if fused[position] > 0][:TOP_K]
        return list(dict.fromkeys(self._snapshot.chunks[self._candidates[p]].document_title for p in ranked))

    def score(self, items: List[Dict[str, str]], config: RetrievalConfig) -> Dict[str, Any]:
        """Recall@1/5 and MRR@10 of the expected documents, with the hit counts behind them."""
        ranks = []
        for item in items:
            documents = self.documents(item["query"], config)
            ranks.append(documents.index(item["expected_document"]) + 1 if item["expected_document"] in documents else None)
        report: Dict[str, Any] = {"questions": len(items)}
        for cutoff in RECALL_CUTOFFS:
            hits = sum(rank is not None and rank <= cutoff for rank in ranks)
            report[f"hits_at_{cutoff}"] = hits
            report[f"recall_at_{cutoff}"] = hits / len(items)
        report["mrr_at_10"] = sum(1 / rank for rank in ranks if rank is not None) / len(items)
        return report


def as_searched(text: str) -> str:
    """The text the chat pipeline routes and searches with (see ``ChatbotService``)."""
    return TextUtils.expand_chat_abbreviations(text)


def variants(perturber: VietnamesePerturber, names: Sequence[str], texts: List[str]) -> Dict[str, List[str]]:
    """``texts`` clean and under each named perturbation."""
    return {CLEAN: list(texts), **{name: [perturber.perturb(text, name) for text in texts] for name in names}}


async def score_retrieval(items: List[Dict[str, str]], texts: Dict[str, List[str]]) -> Dict[str, Any]:
    """Start the app services (as ``eval_rag``) and score every variant under every config."""
    from api.container import AppContainer

    container = AppContainer()
    await container.start()
    try:
        if container.index.snapshot.is_empty:
            raise SystemExit("The knowledge base is empty; seed it first (python -m scripts.seed_demo documents).")
        scorer = RetrievalRobustness(container.index.snapshot, container.embedding, container.reranker)
        report: Dict[str, Any] = {}
        for name, queries in texts.items():
            variant_items = [{**item, "query": query} for item, query in zip(items, queries)]
            report[name] = {
                config.name: await asyncio.to_thread(scorer.score, variant_items, config) for config in scorer.configs()
            }
            report[name]["rewrite_triggered"] = sum(TextUtils.looks_like_unaccented_vietnamese(q) for q in queries)
            logger.info("Retrieval scored for %s", name)
        return report
    finally:
        await container.stop()


def print_tables(report: Dict[str, Any]) -> None:
    """Markdown tables of the report (intentional CLI output)."""
    if "router" in report:
        print("\n| input | router accuracy | macro-F1 | questions stolen | off-topic caught |")
        print("|---|---|---|---|---|")
        for name, row in report["router"].items():
            print(f"| {name} | {row['accuracy']:.1%} ({row['correct']}/{row['cases']}) | {row['macro_f1']:.3f} "
                  f"| {row['questions_stolen']}/{row['questions']} | {row['off_topic_caught']}/{row['off_topic']} |")
    if "retrieval" in report:
        configs = [config.name for config in RETRIEVAL_CONFIGS if config.name in next(iter(report["retrieval"].values()))]
        print("\n| input | " + " | ".join(f"{name} R@1 / R@5 / MRR@10" for name in configs) + " | rewrite triggered |")
        print("|---|" + "---|" * (len(configs) + 1))
        for name, row in report["retrieval"].items():
            cells = [
                f"{row[c]['recall_at_1']:.1%} / {row[c]['recall_at_5']:.1%} / {row[c]['mrr_at_10']:.3f}" for c in configs
            ]
            questions = row[configs[0]]["questions"]
            print(f"| {name} | " + " | ".join(cells) + f" | {row['rewrite_triggered']}/{questions} |")


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point; returns the exit code."""
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=vietnamese_perturber.DEFAULT_SEED)
    parser.add_argument("--perturbation", action="append", default=None, help="Only this perturbation (repeatable)")
    parser.add_argument("--only", choices=("router", "retrieval"), default=None)
    parser.add_argument("--out", type=Path, default=None, help="Write the full report here as JSON")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    logger.setLevel(logging.INFO)

    perturber = VietnamesePerturber(args.seed)
    names = args.perturbation or perturber.names
    report: Dict[str, Any] = {
        "seed": args.seed,
        "rates": {
            "telex_word": vietnamese_perturber.TELEX_WORD_RATE,
            "typo_char": vietnamese_perturber.TYPO_CHAR_RATE,
            "space_drop": vietnamese_perturber.SPACE_DROP_RATE,
        },
    }
    if args.only in (None, "router"):
        from core.retrieval.embeddings import get_embedding_service

        cases = load_router_cases()
        router = EmbeddingRouter(get_embedding_service())
        expected = [case["intent"] for case in cases]
        report["router"] = {
            name: router_metrics(expected, [router.classify(as_searched(text)).intent.value for text in texts])
            for name, texts in variants(perturber, names, [case["text"] for case in cases]).items()
        }
    if args.only in (None, "retrieval"):
        items = load_answerable()
        texts = variants(perturber, names, [item["query"] for item in items])
        report["retrieval"] = asyncio.run(score_retrieval(items, {name: [as_searched(q) for q in qs] for name, qs in texts.items()}))
    print_tables(report)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nFull report saved to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
