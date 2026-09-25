#!/usr/bin/env python3
"""
eval_hardware_divergence.py

Verifies that the embedding model's GPU path and CPU path produce the same
output for the same input -- i.e. that hardware-adaptive device selection
(see ``EmbeddingService.get_embedder`` in core/retrieval/embeddings.py) is
transparent to retrieval quality, not just "doesn't crash."

Loads the configured embedding model twice, once forced onto each device,
encodes the same query set with both, and reports the per-query cosine
divergence between the two outputs. Requires a CUDA GPU to be available;
otherwise there is no GPU path to compare against.

Usage:
  python scripts/eval_hardware_divergence.py
  python scripts/eval_hardware_divergence.py --golden-set data/eval/golden_queries.json --out data/logs/hardware_divergence_report.json
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_GOLDEN_SET_PATH = "data/eval/golden_queries.json"


class HardwareDivergenceEvaluator:
    """Compares GPU-path vs CPU-path embedding output for the same model and inputs."""

    def __init__(self, model_name: str, cache_folder: str):
        """
        Args:
            model_name: Sentence-transformers model to load on both devices.
            cache_folder: Local model cache directory (avoids re-downloading).
        """
        self._model_name = model_name
        self._cache_folder = cache_folder

    def _encode_on_device(self, texts: List[str], device: str) -> np.ndarray:
        """Load a fresh model instance pinned to ``device`` and encode ``texts``."""
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(self._model_name, device=device, cache_folder=self._cache_folder)
        try:
            return model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        finally:
            del model

    def evaluate(self, queries: List[str]) -> Dict[str, Any]:
        """
        Encode ``queries`` on both cuda and cpu and report per-query divergence.

        Returns:
            Report dict with mean/max/min cosine divergence (``1 - cosine_similarity``)
            across the query set, plus the largest single per-element difference.

        Raises:
            RuntimeError: No CUDA GPU is available to compare against.
        """
        import torch

        if not torch.cuda.is_available():
            raise RuntimeError("No CUDA GPU available -- there is no GPU path to compare against CPU.")

        logger.info("Encoding %d queries on cuda", len(queries))
        emb_gpu = self._encode_on_device(queries, "cuda")
        logger.info("Encoding %d queries on cpu", len(queries))
        emb_cpu = self._encode_on_device(queries, "cpu")

        norm_gpu = emb_gpu / np.linalg.norm(emb_gpu, axis=1, keepdims=True)
        norm_cpu = emb_cpu / np.linalg.norm(emb_cpu, axis=1, keepdims=True)
        cosine_similarity = np.sum(norm_gpu * norm_cpu, axis=1)
        divergence = 1.0 - cosine_similarity

        return {
            "model": self._model_name,
            "query_count": len(queries),
            "mean_divergence": float(divergence.mean()),
            "max_divergence": float(divergence.max()),
            "min_divergence": float(divergence.min()),
            "max_abs_element_diff": float(np.max(np.abs(emb_gpu - emb_cpu))),
        }


def print_report(report: Dict[str, Any]) -> None:
    """Print a human-readable summary of the divergence report."""
    print(f"\nHardware divergence eval -- {report['query_count']} queries, model={report['model']}")
    print(f"  Mean cosine divergence (1 - cos_sim): {report['mean_divergence']:.10f}")
    print(f"  Max cosine divergence:                {report['max_divergence']:.10f}")
    print(f"  Max absolute per-element difference:  {report['max_abs_element_diff']:.10f}")
    print()


def main() -> None:
    """Load the golden query set, run the GPU-vs-CPU comparison, print and optionally save the report."""
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--golden-set", default=DEFAULT_GOLDEN_SET_PATH, help="Path to a JSON file with a 'query' field per item"
    )
    parser.add_argument("--out", default=None, help="Optional path to save the full JSON report")
    args = parser.parse_args()

    from config.settings import Config

    with open(args.golden_set, "r", encoding="utf-8") as f:
        queries = [item["query"] for item in json.load(f)]

    evaluator = HardwareDivergenceEvaluator(
        model_name=Config.LLM.EMBEDDING_MODEL(), cache_folder=Config.Paths.MODELS_DIR()
    )
    report = evaluator.evaluate(queries)
    print_report(report)

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"Full report saved to {args.out}")


if __name__ == "__main__":
    main()
