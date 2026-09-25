"""
Hybrid retrieval over the in-memory knowledge snapshot.

Semantic similarity (embeddings) and keyword relevance (BM25) are fused, scaled
by each source's priority, reranked by a cross-encoder, gated by an absolute
relevance threshold and finally expanded with neighbouring chunks of the same
document so the LLM reads contiguous passages.
"""

# Standard library imports
import logging
from typing import Dict, List, Optional, Sequence, Tuple

# Third-party imports
import numpy as np

# Local imports
from models.knowledge import RetrievedChunk
from utils.text_utils import TextUtils
from .knowledge_index import KnowledgeSnapshot

logger = logging.getLogger(__name__)

#: Candidates handed to the reranker per requested result.
RERANK_POOL_MULTIPLIER = 4
#: Smallest candidate pool worth reranking.
MIN_RERANK_POOL = 12


class ContextRetriever:
    """Finds the chunks most relevant to a query in a :class:`KnowledgeSnapshot`."""

    def __init__(self, embedding_service, reranker=None):
        """
        Args:
            embedding_service: Exposes ``embed_query(text) -> np.ndarray`` (normalized).
            reranker: Optional cross-encoder exposing ``score(query, texts)``;
                ``None`` disables reranking.
        """
        self._embedding_service = embedding_service
        self._reranker = reranker

    @staticmethod
    def _candidate_indices(snapshot: KnowledgeSnapshot, sources: Optional[Sequence[str]]) -> np.ndarray:
        """Indices of the chunks a search may return, honouring a source filter."""
        if not sources:
            return np.arange(len(snapshot.chunks))
        selected = [snapshot.source_indices[name] for name in sources if name in snapshot.source_indices]
        if not selected:
            return np.zeros(0, dtype=np.int64)
        return np.concatenate(selected)

    @staticmethod
    def _min_max(values: np.ndarray) -> np.ndarray:
        """Scale to [0, 1]; a constant vector maps to zeros."""
        span = float(values.max() - values.min()) if values.size else 0.0
        if span <= 0:
            return np.zeros_like(values, dtype=np.float64)
        return (values - values.min()) / span

    def _hybrid_scores(
        self, query: str, snapshot: KnowledgeSnapshot, candidates: np.ndarray, semantic_weight: float
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Score every candidate.

        Returns:
            ``(semantic, keyword, fused)`` arrays aligned with ``candidates``;
            ``fused`` already includes the source priority multiplier.
        """
        query_vector = self._embedding_service.embed_query(query)
        semantic = snapshot.embeddings[candidates] @ query_vector

        tokens = TextUtils.tokenize_for_search(query)
        # ceiling: rank_bm25 scores the whole corpus in Python (~100ms at 100k
        # chunks); switch to PostgreSQL full-text search past that size.
        keyword_all = snapshot.bm25.get_scores(tokens) if tokens and snapshot.bm25 is not None else None
        keyword = keyword_all[candidates] if keyword_all is not None else np.zeros(len(candidates))

        fused = semantic_weight * self._min_max(semantic) + (1 - semantic_weight) * self._min_max(keyword)
        priorities = np.fromiter((snapshot.chunks[i].source_priority for i in candidates), dtype=np.float64)
        return semantic, keyword, fused * priorities

    def search(
        self,
        query: str,
        snapshot: KnowledgeSnapshot,
        top_k: int,
        semantic_weight: float,
        threshold: float,
        max_context_chunks: int,
        expansion_radius: int,
        sources: Optional[Sequence[str]] = None,
    ) -> List[RetrievedChunk]:
        """
        Return matched chunks (plus neighbours for context), best first.

        Args:
            query: Standalone search text.
            snapshot: Corpus to search.
            top_k: Maximum matched chunks.
            semantic_weight: Weight of embeddings vs BM25 in the fused score (0-1).
            threshold: Minimum relevance (reranker score, or cosine similarity
                when no reranker ran) for a chunk to count as a match.
            max_context_chunks: Cap on returned chunks including neighbours.
            expansion_radius: Neighbours added on each side of a match (same document).
            sources: Restrict to these source names; ``None`` searches all.

        Returns:
            Matched chunks first-ranked-first, each followed by its neighbours in
            document order. Empty when nothing clears ``threshold``.
        """
        if snapshot.is_empty or not query.strip():
            return []
        candidates = self._candidate_indices(snapshot, sources)
        if candidates.size == 0:
            return []

        semantic, keyword, fused = self._hybrid_scores(query, snapshot, candidates, semantic_weight)
        pool_size = min(len(candidates), max(top_k * RERANK_POOL_MULTIPLIER, MIN_RERANK_POOL))
        pool = np.argsort(-fused)[:pool_size]

        rerank_scores = None
        if self._reranker is not None:
            texts = [snapshot.chunks[candidates[p]].content for p in pool]
            rerank_scores = self._reranker.score(query, texts)

        scored: List[RetrievedChunk] = []
        for rank, position in enumerate(pool):
            chunk = snapshot.chunks[candidates[position]]
            rerank = float(rerank_scores[rank]) if rerank_scores is not None else None
            relevance = rerank if rerank is not None else float(semantic[position])
            if relevance < threshold:
                continue
            scored.append(
                RetrievedChunk(
                    chunk=chunk,
                    relevance=relevance,
                    semantic_score=float(semantic[position]),
                    keyword_score=float(keyword[position]),
                    rerank_score=rerank,
                )
            )

        scored.sort(key=lambda item: item.relevance * item.chunk.source_priority, reverse=True)
        matches = scored[:top_k]
        logger.debug("Search matched %d/%d pooled chunks", len(matches), len(pool))
        return self._expand(snapshot, matches, max_context_chunks, expansion_radius)

    @staticmethod
    def _expand(
        snapshot: KnowledgeSnapshot,
        matches: List[RetrievedChunk],
        max_chunks: int,
        radius: int,
    ) -> List[RetrievedChunk]:
        """Add same-document neighbours around each match, capped at ``max_chunks``."""
        index_of: Dict[str, int] = {}
        if radius > 0:
            index_of = {chunk.chunk_id: i for i, chunk in enumerate(snapshot.chunks)}

        selected: Dict[str, RetrievedChunk] = {}
        ordered: List[RetrievedChunk] = []
        for match in matches:
            if len(ordered) >= max_chunks:
                break
            window = [match]
            if radius > 0:
                centre = index_of[match.chunk.chunk_id]
                for offset in range(-radius, radius + 1):
                    neighbour_index = centre + offset
                    if offset == 0 or not 0 <= neighbour_index < len(snapshot.chunks):
                        continue
                    neighbour = snapshot.chunks[neighbour_index]
                    if neighbour.document_id == match.chunk.document_id:
                        window.append(RetrievedChunk(chunk=neighbour, relevance=0.0, matched=False))
                window.sort(key=lambda item: item.chunk.position)
            for item in window:
                if len(ordered) >= max_chunks:
                    break
                existing = selected.get(item.chunk.chunk_id)
                if existing is not None:
                    # A neighbour that is also a real match keeps its match data.
                    if item.matched and not existing.matched:
                        ordered[ordered.index(existing)] = item
                        selected[item.chunk.chunk_id] = item
                    continue
                selected[item.chunk.chunk_id] = item
                ordered.append(item)
        return ordered
