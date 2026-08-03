"""
Offline builder for the retrieval query adapter.

Fits the closed-form linear adapter from a labelled ``(query, positive)`` file
and writes it to the configured adapter path.
"""

# Standard library imports
import logging
from pathlib import Path
from typing import List, Optional, Tuple

# Local imports
from config.settings import Config
from core.ai_services.embeddings.embeddings import get_embedding_service
from core.retrieval.query_expansion.query_adapter import build_from_evals, save_query_adapter

logger = logging.getLogger(__name__)

#: Columns the eval file must provide.
REQUIRED_COLUMNS = {"query", "positive"}


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
