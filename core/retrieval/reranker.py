"""
Pluggable reranker for hybrid retrieval results.
Uses a cross-encoder if available, otherwise falls back to a lightweight heuristic reranker.
"""

from typing import List, Dict, Any, Optional
import logging
import os
import threading

# Set trust_remote_code environment variable before importing sentence_transformers
os.environ["HF_TRUST_REMOTE_CODE"] = "True"

logger = logging.getLogger(__name__)

try:
    from transformers import AutoModelForSequenceClassification, AutoTokenizer  # type: ignore
    TRANSFORMERS_AVAILABLE = True
except Exception:
    TRANSFORMERS_AVAILABLE = False


class Reranker:
    """
    Rerank retrieval results given the user query and candidate chunks.
    If a CrossEncoder model is available, use it; otherwise, rely on combined scores provided upstream.
    """

    #: Last-resort fallback if the configured reranker can't load at all.
    #: English-only, so it only kicks in as a degraded emergency path — the
    #: configured default must stay a multilingual model for Vietnamese support.
    _EMERGENCY_FALLBACK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    def __init__(self, model_name: str = None):
        self._model = None
        from config.settings import Config

        if model_name is None:
            model_name = Config.RAG.RERANKER_MODEL()
        self._model_name = model_name
        cache_dir = Config.Database.MODELS_DIR()

        if TRANSFORMERS_AVAILABLE:
            candidates = list(dict.fromkeys([model_name, self._EMERGENCY_FALLBACK_MODEL]))
            for candidate in candidates:
                try:
                    # Loaded directly via `transformers` (not
                    # sentence_transformers.CrossEncoder) for every model,
                    # jinaai or not: CrossEncoder's own loading wrapper
                    # segfaults (access violation in torch/transformers
                    # native code, uncatchable from Python) with this
                    # project's torch/transformers/accelerate combo on
                    # Windows, even when passed the same
                    # low_cpu_mem_usage=False that avoids the crash when
                    # calling `from_pretrained` directly. Verified against
                    # transformers 4.53.3 / torch 2.13.0+cu126.
                    trust_remote_code = candidate.startswith("jinaai/")
                    tokenizer = AutoTokenizer.from_pretrained(
                        candidate, trust_remote_code=trust_remote_code, cache_dir=cache_dir
                    )
                    model = AutoModelForSequenceClassification.from_pretrained(
                        candidate,
                        trust_remote_code=trust_remote_code,
                        cache_dir=cache_dir,
                        low_cpu_mem_usage=False,
                    )
                    self._model = self._create_cross_encoder_wrapper(model, tokenizer)
                    logger.info("Reranker loaded (transformers): %s", candidate)

                    self._model_name = candidate
                    break
                except Exception:
                    logger.exception("Failed to load reranker '%s'", candidate)

    def _create_cross_encoder_wrapper(self, model, tokenizer):
        """Create a CrossEncoder-like wrapper around a raw transformers model/tokenizer pair."""
        class CrossEncoderWrapper:
            def __init__(self, model, tokenizer):
                import torch

                self.device = "cuda" if torch.cuda.is_available() else "cpu"
                self.model = model.to(self.device)
                self.tokenizer = tokenizer
                self.model.eval()

            def predict(self, pairs, batch_size: int = 32):
                """Predict scores for query-document pairs, batched for throughput."""
                import torch
                import numpy as np

                if not pairs:
                    return np.array([])

                scores = []
                for i in range(0, len(pairs), batch_size):
                    batch = pairs[i:i + batch_size]
                    queries = [q for q, _ in batch]
                    documents = [d for _, d in batch]

                    # Tokenize the whole batch at once
                    inputs = self.tokenizer(
                        queries,
                        documents,
                        return_tensors="pt",
                        truncation=True,
                        max_length=512,
                        padding=True,
                    ).to(self.device)

                    # Get predictions for the batch in a single forward pass
                    with torch.no_grad():
                        outputs = self.model(**inputs)
                        # Get the score (logits) for the positive class
                        batch_scores = torch.sigmoid(outputs.logits.squeeze(-1))
                        scores.extend(batch_scores.cpu().tolist())

                return np.array(scores)

        return CrossEncoderWrapper(model, tokenizer)

    def available(self) -> bool:
        return self._model is not None

    def rerank(self, query: str, results: List[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
        if not results:
            return []

        # Cross-encoder based reranking
        if self._model is not None:
            try:
                pairs = [(query, r.get("document", "")) for r in results]
                scores = self._model.predict(pairs)
                for i, s in enumerate(scores):
                    results[i]["rerank_score"] = float(s)
                results.sort(key=lambda x: x.get("rerank_score", 0.0), reverse=True)
                return results[:top_k]
            except Exception as e:
                logger.warning(f" Cross-encoder reranking failed, falling back: {e}")

        # Heuristic fallback: prefer combined score, then semantic, then keyword
        for r in results:
            r["rerank_score"] = (
                1.0 * float(r.get("combined_score", 0.0))
                + 0.25 * float(r.get("norm_semantic_score", r.get("semantic_score", 0.0)))
                + 0.1 * float(r.get("norm_keyword_score", r.get("keyword_score", 0.0)))
            )
        results.sort(key=lambda x: x.get("rerank_score", 0.0), reverse=True)
        return results[:top_k]


_reranker: Optional[Reranker] = None
_reranker_lock = threading.Lock()


def get_reranker() -> Reranker:
    """
    Get the process-wide reranker.

    Cross-encoder weights cost hundreds of megabytes and seconds to load, so the
    model must be instantiated once per process rather than per retriever.
    """
    global _reranker
    if _reranker is None:
        with _reranker_lock:
            if _reranker is None:
                _reranker = Reranker()
    return _reranker
