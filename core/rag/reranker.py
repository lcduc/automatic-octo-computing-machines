"""
Pluggable reranker for hybrid retrieval results.
Uses a cross-encoder if available, otherwise falls back to a lightweight heuristic reranker.
"""

from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)

try:
    from sentence_transformers import CrossEncoder  # type: ignore
except Exception:
    CrossEncoder = None  # type: ignore


class Reranker:
    """
    Rerank retrieval results given the user query and candidate chunks.
    If a CrossEncoder model is available, use it; otherwise, rely on combined scores provided upstream.
    """

    def __init__(self, model_name: str = None):
        self._model = None
        if model_name is None:
            try:
                from config.rag.rag_config import RAGConfig
                model_name = RAGConfig.RERANKER_MODEL()
            except Exception:
                model_name = "cross-encoder/ms-marco-MultiMiniLM-L-6-v2"
        self._model_name = model_name
        if CrossEncoder is not None:
            # Try configured model first, then a known multilingual fallback
            for candidate in [model_name, "cross-encoder/ms-marco-MultiMiniLM-L-6-v2"]:
                try:
                    self._model = CrossEncoder(candidate)
                    logger.info(f"✅ Reranker loaded: {candidate}")
                    self._model_name = candidate
                    break
                except Exception as e:
                    logger.warning(f"⚠️ Failed to load reranker '{candidate}': {e}")

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
                logger.warning(f"⚠️ Cross-encoder reranking failed, falling back: {e}")

        # Heuristic fallback: prefer combined score, then semantic, then keyword
        for r in results:
            r["rerank_score"] = (
                1.0 * float(r.get("combined_score", 0.0))
                + 0.25 * float(r.get("norm_semantic_score", r.get("semantic_score", 0.0)))
                + 0.1 * float(r.get("norm_keyword_score", r.get("keyword_score", 0.0)))
            )
        results.sort(key=lambda x: x.get("rerank_score", 0.0), reverse=True)
        return results[:top_k]


