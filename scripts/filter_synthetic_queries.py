"""
Filter the generated synthetic questions and split them into train / validation pairs.

Steps, in order (each drop is counted in ``filter_report.json``):

1. exact duplicates: same text once lower-cased, unaccented and stripped of punctuation;
2. near duplicates: cosine >= ``NEAR_DUPLICATE_COSINE`` to an earlier kept question of the same chunk;
3. decontamination: a question that matches, or nearly matches, any human golden question is dropped,
   so no evaluation question leaks into training even by accident;
4. round trip: the reranker scores the question against every chunk; it is kept only when its
   source chunk ranks in the top ``ROUND_TRIP_TOP_N``;
5. at most ``MAX_KEPT_PER_CHUNK`` per chunk, taken style by style in reranker order;
6. split: one question of every chunk with at least ``MIN_KEPT_FOR_VALIDATION`` goes to validation.

Usage (from the repository root, with the venv active; needs the embedding model and the reranker)::

    python -m scripts.filter_synthetic_queries
"""

# Standard library imports
import argparse
import json
import logging
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

# Third-party imports
import numpy as np
from dotenv import load_dotenv

load_dotenv()

# Local imports
from config.settings import Config  # noqa: E402
from scripts.synthetic_dataset import (  # noqa: E402
    CORPUS_FILE, FILTER_REPORT_FILE, RAW_QUESTIONS_FILE, TRAIN_FILE, VAL_FILE, read_jsonl, write_jsonl,
)
from utils.text_utils import TextUtils  # noqa: E402

logger = logging.getLogger(__name__)

GOLDEN_SET_FILES = sorted((Path(__file__).parent / "demo_data").glob("golden_*.json"))
#: e5 cosine of two questions asking the same thing in nearly the same words.
NEAR_DUPLICATE_COSINE = 0.95
#: Stricter than within-chunk duplicates: any golden question this close is treated as leaked.
GOLDEN_OVERLAP_COSINE = 0.93
ROUND_TRIP_TOP_N = 3
MAX_KEPT_PER_CHUNK = 5
MIN_KEPT_FOR_VALIDATION = 3
SPLIT_SEED = 13
PUNCTUATION = re.compile(r"[^\w\s]")


def normalized(text: str) -> str:
    """Lower-cased, unaccented, punctuation-free, single-spaced form used for exact matching."""
    plain = TextUtils.strip_vietnamese_accents(text.lower())
    return " ".join(PUNCTUATION.sub(" ", plain).split())


def rerank_text(chunk: Dict[str, Any]) -> str:
    """What the live reranker scores for a chunk: its title, then its text (``ContextRetriever._rerank_text``)."""
    return f"{chunk['document_title']}\n{chunk['content']}"


class SyntheticQueryFilter:
    """Applies the filter steps and keeps a count of every drop."""

    def __init__(self, embedder, reranker, corpus: List[Dict[str, Any]], golden_queries: List[str]):
        """
        Args:
            embedder: ``SentenceTransformer`` with the live query prompt (``encode_query``).
            reranker: Live ``Reranker`` (``score(query, texts)``).
            corpus: Dataset chunks (``chunk_id``, ``document_title``, ``content``).
            golden_queries: Every human golden question, used only to drop overlapping synthetic ones.
        """
        self._embedder = embedder
        self._reranker = reranker
        self._corpus = corpus
        self._golden_queries = golden_queries
        self.report: Dict[str, Any] = {"dropped": Counter(), "golden_overlaps": []}

    def run(self, raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Every filter step; returns the kept records, each with ``rerank_rank`` and ``rerank_score``."""
        self.report["raw"] = len(raw)
        records = self._drop_exact_duplicates(raw)
        vectors = self._encode([r["question"] for r in records])
        records, vectors = self._drop_near_duplicates(records, vectors)
        records = self._drop_golden_overlaps(records, vectors)
        records = self._round_trip(records)
        kept = self._cap_per_chunk(records)
        self.report["kept"] = len(kept)
        self.report["kept_by_style"] = Counter(r["style"] for r in kept)
        return kept

    def _encode(self, texts: List[str]) -> np.ndarray:
        """Normalized query embeddings."""
        return np.asarray(self._embedder.encode_query(texts, normalize_embeddings=True, convert_to_numpy=True))

    def _drop_exact_duplicates(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Keep the first record of each normalized text."""
        seen, kept = set(), []
        for record in records:
            key = normalized(record["question"])
            if key in seen:
                self.report["dropped"]["exact_duplicate"] += 1
                continue
            seen.add(key)
            kept.append(record)
        return kept

    def _drop_near_duplicates(self, records, vectors):
        """Drop a record too close to an earlier kept one of the same chunk."""
        kept_indices: Dict[str, List[int]] = defaultdict(list)
        keep = []
        for index, record in enumerate(records):
            earlier = kept_indices[record["chunk_id"]]
            if earlier and float(np.max(vectors[earlier] @ vectors[index])) >= NEAR_DUPLICATE_COSINE:
                self.report["dropped"]["near_duplicate"] += 1
                continue
            earlier.append(index)
            keep.append(index)
        return [records[i] for i in keep], vectors[keep]

    def _drop_golden_overlaps(self, records, vectors) -> List[Dict[str, Any]]:
        """Drop a record that equals, or nearly equals, any golden question."""
        golden_keys = {normalized(query) for query in self._golden_queries}
        similarity = vectors @ self._encode(self._golden_queries).T
        nearest = similarity.argmax(axis=1)
        self.report["max_cosine_to_golden"] = {
            "mean": round(float(similarity.max(axis=1).mean()), 3),
            "p95": round(float(np.percentile(similarity.max(axis=1), 95)), 3),
            "max": round(float(similarity.max()), 3),
        }
        kept = []
        for index, record in enumerate(records):
            score = float(similarity[index, nearest[index]])
            if normalized(record["question"]) in golden_keys or score >= GOLDEN_OVERLAP_COSINE:
                self.report["dropped"]["golden_overlap"] += 1
                self.report["golden_overlaps"].append(
                    {"synthetic": record["question"], "golden": self._golden_queries[nearest[index]], "cosine": round(score, 3)}
                )
                continue
            kept.append(record)
        return kept

    def _round_trip(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Keep a record whose source chunk the reranker ranks in the top ``ROUND_TRIP_TOP_N`` of the whole corpus."""
        texts = [rerank_text(chunk) for chunk in self._corpus]
        position = {chunk["chunk_id"]: index for index, chunk in enumerate(self._corpus)}
        failures = Counter()
        kept = []
        logger.info("Reranking %d questions against %d chunks", len(records), len(texts))
        for record in records:
            scored = self._reranker.score(record["question"], texts)
            if scored is None:
                # Dropping the question would silently bias the dataset; a failed reranker must stop the run.
                raise RuntimeError(f"Reranker failed on {record['question']!r}; rerun the filter")
            scores = np.asarray(scored)
            source = scores[position[record["chunk_id"]]]
            rank = int((scores > source).sum()) + 1
            if rank > ROUND_TRIP_TOP_N:
                failures[record["style"]] += 1
                continue
            kept.append({**record, "rerank_rank": rank, "rerank_score": round(float(source), 4)})
        self.report["dropped"]["round_trip"] = sum(failures.values())
        self.report["round_trip_failures_by_style"] = failures
        return kept

    def _cap_per_chunk(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """At most ``MAX_KEPT_PER_CHUNK`` per chunk: styles take turns, each in reranker-score order."""
        by_chunk: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
        for record in sorted(records, key=lambda r: -r["rerank_score"]):
            by_chunk[record["chunk_id"]][record["style"]].append(record)
        kept = []
        for styles in by_chunk.values():
            queues = [list(queue) for queue in styles.values()]
            chosen = []
            while len(chosen) < MAX_KEPT_PER_CHUNK and any(queues):
                for queue in queues:
                    if queue and len(chosen) < MAX_KEPT_PER_CHUNK:
                        chosen.append(queue.pop(0))
            self.report["dropped"]["over_cap"] += sum(len(queue) for queue in queues)
            kept.extend(chosen)
        return kept


def split(records: List[Dict[str, Any]], corpus: List[Dict[str, Any]], seed: int = SPLIT_SEED):
    """
    ``(train, val)`` pairs: one random question per chunk with enough questions goes to validation.

    Each pair carries ``query`` and ``positive`` (the chunk text, as stored and embedded).
    """
    content = {chunk["chunk_id"]: chunk for chunk in corpus}
    by_chunk: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_chunk[record["chunk_id"]].append(record)
    rng = random.Random(seed)
    train, val = [], []
    for chunk_id in sorted(by_chunk):
        items = sorted(by_chunk[chunk_id], key=lambda r: r["question"])
        held_out = rng.randrange(len(items)) if len(items) >= MIN_KEPT_FOR_VALIDATION else None
        for index, record in enumerate(items):
            chunk = content[chunk_id]
            pair = {
                "query": record["question"], "positive": chunk["content"], "chunk_id": chunk_id,
                "document_title": chunk["document_title"], "style": record["style"],
                "rerank_rank": record["rerank_rank"], "rerank_score": record["rerank_score"],
            }
            (val if index == held_out else train).append(pair)
    return train, val


def load_golden_queries() -> List[str]:
    """Every question of every golden set (answerable or not)."""
    queries = []
    for path in GOLDEN_SET_FILES:
        queries += [item["query"] for item in json.loads(path.read_text(encoding="utf-8"))]
    return queries


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point; returns the exit code."""
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    from core.retrieval.embeddings import get_embedding_service
    from core.retrieval.reranker import get_reranker

    reranker = get_reranker()
    if not reranker.available() or reranker._model_name != Config.RAG.RERANKER_MODEL():
        raise SystemExit(f"The round trip needs {Config.RAG.RERANKER_MODEL()}; it did not load.")
    corpus = read_jsonl(CORPUS_FILE)
    query_filter = SyntheticQueryFilter(
        get_embedding_service().get_embedder(), reranker, corpus, load_golden_queries()
    )
    kept = query_filter.run(read_jsonl(RAW_QUESTIONS_FILE))
    train, val = split(kept, corpus)
    write_jsonl(TRAIN_FILE, train)
    write_jsonl(VAL_FILE, val)

    per_chunk = Counter(r["chunk_id"] for r in kept)
    report = {
        **query_filter.report,
        "train": len(train),
        "val": len(val),
        "chunks_with_questions": len(per_chunk),
        "chunks_without_questions": sorted({c["chunk_id"] for c in corpus} - set(per_chunk)),
        "kept_per_chunk": dict(sorted(Counter(per_chunk.values()).items())),
        "settings": {
            "near_duplicate_cosine": NEAR_DUPLICATE_COSINE, "golden_overlap_cosine": GOLDEN_OVERLAP_COSINE,
            "round_trip_top_n": ROUND_TRIP_TOP_N, "max_kept_per_chunk": MAX_KEPT_PER_CHUNK,
            "reranker": Config.RAG.RERANKER_MODEL(), "embedding_model": Config.LLM.EMBEDDING_MODEL(),
        },
    }
    FILTER_REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "golden_overlaps"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
