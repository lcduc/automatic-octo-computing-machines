"""
Files of the synthetic-query dataset used to train retrieval variants, and the chunk-level metric
the training scripts select on.

Layout under ``scripts/demo_data/synthetic/`` (JSON lines, UTF-8):

- ``corpus.jsonl``: the knowledge chunks the questions were generated from
  (``chunk_id``, ``document_title``, ``position``, ``content``);
- ``raw_questions.jsonl``: every LLM-generated question (``chunk_id``, ``style``, ``question``, ``model``);
- ``train.jsonl`` / ``val.jsonl``: the questions kept by the filter, as ``query`` / ``positive``
  pairs (the format ``scripts.build_query_adapter`` reads) plus ``chunk_id``, ``style`` and ``rerank_rank``.

The human golden sets in ``scripts/demo_data/golden_*.json`` are evaluation-only and never written here.
"""

# Standard library imports
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

# Third-party imports
import numpy as np

DATASET_DIR = Path(__file__).parent / "demo_data" / "synthetic"
CORPUS_FILE = DATASET_DIR / "corpus.jsonl"
RAW_QUESTIONS_FILE = DATASET_DIR / "raw_questions.jsonl"
TRAIN_FILE = DATASET_DIR / "train.jsonl"
VAL_FILE = DATASET_DIR / "val.jsonl"
FILTER_REPORT_FILE = DATASET_DIR / "filter_report.json"
#: Ranking depth of the validation metric, matching the golden-set MRR@10.
VALIDATION_MRR_AT = 10


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Every record of a JSON-lines file."""
    with open(path, "r", encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def write_jsonl(path: Path, records: Iterable[Dict[str, Any]]) -> int:
    """Write records as JSON lines (creating the directory); returns how many were written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(path, "w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count


def chunk_mrr(query_vectors: np.ndarray, corpus_vectors: np.ndarray, targets: Sequence[int], k: int = VALIDATION_MRR_AT) -> float:
    """
    MRR@k of each query's target chunk under cosine ranking.

    Args:
        query_vectors: ``(n_queries, dim)``, any norm.
        corpus_vectors: ``(n_chunks, dim)``, any norm.
        targets: Index into ``corpus_vectors`` of each query's source chunk.
        k: Ranks beyond ``k`` score 0.
    """
    queries = query_vectors / np.linalg.norm(query_vectors, axis=1, keepdims=True)
    corpus = corpus_vectors / np.linalg.norm(corpus_vectors, axis=1, keepdims=True)
    scores = queries @ corpus.T
    target_scores = scores[np.arange(len(targets)), np.asarray(targets)]
    ranks = (scores > target_scores[:, None]).sum(axis=1) + 1
    return float(np.where(ranks <= k, 1.0 / ranks, 0.0).mean())
