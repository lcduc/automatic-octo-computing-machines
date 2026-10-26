"""
Offline builder for the retrieval query adapter.

Fits the closed-form linear adapter from a labelled ``(query, positive)`` file
and writes it to the configured adapter path. With a validation file, the ridge
strength is chosen first: each candidate is fitted on the training pairs and
scored by the chunk-level MRR@10 of the validation questions over the corpus.

Usage (from the repository root, with the venv active)::

    python -m scripts.build_query_adapter                       # synthetic train/val, lambda grid
    python -m scripts.build_query_adapter --lambdas 0.1 --output data/query_adapter.npy
"""

# Standard library imports
import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# Local imports
from config.settings import Config
from core.retrieval.embeddings import get_embedding_service
from core.retrieval.query_adapter import build_from_evals, compute_query_adapter, save_query_adapter
from scripts.synthetic_dataset import CORPUS_FILE, TRAIN_FILE, VAL_FILE, chunk_mrr, read_jsonl

logger = logging.getLogger(__name__)

#: Columns the eval file must provide.
REQUIRED_COLUMNS = {"query", "positive"}
#: Ridge strengths tried by default; QᵀQ of unit-norm queries has trace n, so these span "barely" to "mostly" regularized.
LAMBDA_GRID = (1e-3, 1e-2, 1e-1, 1.0, 10.0, 100.0)


class QueryAdapterBuilder:
    """Reads an eval file, fits the query adapter and persists it."""

    def __init__(self, output_path: Optional[str] = None):
        """
        Args:
            output_path: Where to write the adapter; defaults to the configured
                ``QUERY_ADAPTER_PATH``.
        """
        self._output_path = output_path or Config.RAG.QUERY_ADAPTER_PATH()

    def build(self, evals_file: str, lambda_reg: float = 1e-3) -> str:
        """
        Fit and save the adapter.

        Args:
            evals_file: Path to a ``.jsonl`` or ``.csv`` with ``query`` and
                ``positive`` columns.
            lambda_reg: Ridge regularization strength.

        Returns:
            The path the adapter was written to.

        Raises:
            ValueError: When the eval file is missing required columns.
        """
        queries, positives = self._load_pairs(evals_file)
        embedder = get_embedding_service().get_embedder()
        adapter = build_from_evals(queries, positives, embedder, lambda_reg)
        save_query_adapter(adapter, self._output_path)
        logger.info(
            "Query adapter saved to %s (dim=%d)", self._output_path, adapter.shape[0]
        )
        return self._output_path

    def select_lambda(
        self, evals_file: str, val_file: str, corpus_file: str, lambdas: Sequence[float]
    ) -> Tuple[float, Dict[str, float]]:
        """
        Pick the ridge strength whose adapter ranks the validation questions' chunks best.

        Args:
            evals_file: Training pairs (``query``, ``positive``).
            val_file: Validation questions (``query``, ``chunk_id``).
            corpus_file: Every chunk (``chunk_id``, ``content``), the candidates ranked.
            lambdas: Candidate strengths.

        Returns:
            ``(best_lambda, {"none" | str(lambda): validation MRR@10})``; ``"none"`` is the unadapted model.
        """
        queries, positives = self._load_pairs(evals_file)
        val, corpus = read_jsonl(Path(val_file)), read_jsonl(Path(corpus_file))
        index = {chunk["chunk_id"]: position for position, chunk in enumerate(corpus)}
        targets = [index[item["chunk_id"]] for item in val]

        embedder = get_embedding_service().get_embedder()
        train_queries = embedder.encode_query(queries, convert_to_numpy=True)
        train_positives = embedder.encode_document(positives, convert_to_numpy=True)
        val_queries = embedder.encode_query([item["query"] for item in val], convert_to_numpy=True)
        corpus_vectors = embedder.encode_document([chunk["content"] for chunk in corpus], convert_to_numpy=True)

        scores = {"none": chunk_mrr(val_queries, corpus_vectors, targets)}
        for lambda_reg in lambdas:
            adapter = compute_query_adapter(train_queries, train_positives, regularization_lambda=lambda_reg)
            scores[str(lambda_reg)] = chunk_mrr(val_queries @ adapter, corpus_vectors, targets)
            logger.info("lambda=%g: validation MRR@10 %.4f", lambda_reg, scores[str(lambda_reg)])
        best = max(lambdas, key=lambda value: scores[str(value)])
        return best, scores

    @staticmethod
    def _load_pairs(evals_file: str) -> Tuple[List[str], List[str]]:
        """Load query/positive pairs from a JSONL or CSV eval file."""
        import pandas as pd

        suffix = Path(evals_file).suffix.lower()
        frame = (
            pd.read_json(evals_file, lines=True)
            if suffix == ".jsonl"
            else pd.read_csv(evals_file)
        )
        if not REQUIRED_COLUMNS.issubset(frame.columns):
            raise ValueError(
                f"Eval file must contain columns {sorted(REQUIRED_COLUMNS)}; "
                f"found {sorted(frame.columns)}"
            )
        return (
            frame["query"].astype(str).tolist(),
            frame["positive"].astype(str).tolist(),
        )


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point; returns the exit code."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--train", default=str(TRAIN_FILE), help="Training pairs (query, positive)")
    parser.add_argument("--val", default=str(VAL_FILE), help="Validation questions for choosing lambda")
    parser.add_argument("--corpus", default=str(CORPUS_FILE), help="Chunks ranked by the validation metric")
    parser.add_argument("--lambdas", type=float, nargs="+", default=list(LAMBDA_GRID))
    parser.add_argument("--output", default=None, help="Adapter path (default: QUERY_ADAPTER_PATH)")
    parser.add_argument("--force", action="store_true",
                        help="Write the adapter even when it scores below the unadapted model on validation")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    builder = QueryAdapterBuilder(args.output)
    best, scores = builder.select_lambda(args.train, args.val, args.corpus, args.lambdas)
    beats_unadapted = scores[str(best)] > scores["none"]
    report = {"validation_mrr_at_10": scores, "chosen_lambda": best, "beats_unadapted": beats_unadapted, "adapter": None}
    if not beats_unadapted and not args.force:
        # The app and the router load QUERY_ADAPTER_PATH at start-up, so a worse adapter would degrade both.
        logger.error("No lambda beats the unadapted model on validation; not writing an adapter (--force writes it anyway)")
        print(json.dumps(report, indent=2))
        return 1
    if not beats_unadapted:
        logger.warning("Writing an adapter that scores below the unadapted model on validation (--force)")
    report["adapter"] = builder.build(args.train, best)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
