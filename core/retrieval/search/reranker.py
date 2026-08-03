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
    from sentence_transformers import CrossEncoder  # type: ignore
    from transformers import AutoModelForSequenceClassification, AutoTokenizer  # type: ignore
    TRANSFORMERS_AVAILABLE = True
except Exception:
    CrossEncoder = None  # type: ignore
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

        if CrossEncoder is not None or TRANSFORMERS_AVAILABLE:
            candidates = list(dict.fromkeys([model_name, self._EMERGENCY_FALLBACK_MODEL]))
            for candidate in candidates:
                try:
                    # Special handling for jinaai models that require trust_remote_code
                    if candidate.startswith("jinaai/") and TRANSFORMERS_AVAILABLE:
                        tokenizer = AutoTokenizer.from_pretrained(
                            candidate, trust_remote_code=True, cache_dir=cache_dir
                        )
                        model = AutoModelForSequenceClassification.from_pretrained(
                            candidate, trust_remote_code=True, cache_dir=cache_dir
                        )
                        self._model = self._create_cross_encoder_wrapper(model, tokenizer)
                        logger.info("Reranker loaded (transformers): %s", candidate)
                    else:
                        # CrossEncoder has no `cache_folder` param (unlike
                        # SentenceTransformer) — the cache dir is passed through
                        # to the underlying transformers `from_pretrained` calls
                        # instead. Verified against sentence-transformers 2.5.1.
                        self._model = CrossEncoder(
                            candidate,
                            automodel_args={"cache_dir": cache_dir},
                            tokenizer_args={"cache_dir": cache_dir},
                        )
                        logger.info("Reranker loaded (sentence_transformers): %s", candidate)

                    self._model_name = candidate
                    break
                except Exception:
                    logger.exception("Failed to load reranker '%s'", candidate)

    def _create_cross_encoder_wrapper(self, model, tokenizer):
        """Create a CrossEncoder-like wrapper for transformers models."""
        class CrossEncoderWrapper:
            def __init__(self, model, tokenizer):
                self.model = model
                self.tokenizer = tokenizer
                self.model.eval()
            
            def predict(self, pairs):
                """Predict scores for query-document pairs."""
                import torch
                import numpy as np
                
                scores = []
                for query, document in pairs:
                    # Tokenize the pair
                    inputs = self.tokenizer(
                        query, 
                        document, 
                        return_tensors="pt", 
                        truncation=True, 
                        max_length=512,
                        padding=True
                    )
                    
                    # Get prediction
                    with torch.no_grad():
                        outputs = self.model(**inputs)
                        # Get the score (logits) for the positive class
                        score = torch.sigmoid(outputs.logits).item()
                        scores.append(score)
                
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
