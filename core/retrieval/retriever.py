"""
Hybrid retrieval over the in-memory knowledge snapshot.

Semantic similarity (embeddings) and keyword relevance (BM25) are fused by
weighted reciprocal rank fusion (RET-04), scaled by each source's priority,
reranked by a cross-encoder, gated by an absolute
relevance threshold and finally expanded with neighbouring chunks of the same
document so the LLM reads contiguous passages.
"""

# Standard library imports
import logging
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

# Third-party imports
import numpy as np

# Local imports
from models.knowledge import IndexedChunk, RetrievedChunk
from utils.text_utils import TextUtils
from .knowledge_index import KnowledgeSnapshot

logger = logging.getLogger(__name__)

#: Candidates handed to the reranker per requested result.
RERANK_POOL_MULTIPLIER = 4
#: Smallest candidate pool reranked (RET-04: 20-50); 30 beat 16 on the golden set.
MIN_RERANK_POOL = 30
#: RRF damping constant: the usual 60, so the top few ranks do not dominate.
RRF_K = 60


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
    def _candidate_indices(
        snapshot: KnowledgeSnapshot, sources: Optional[Sequence[str]], access_level: int, today: date
    ) -> np.ndarray:
        """Indices of the chunks a search may return: source filter, then tier and effective dates."""
        if not sources:
            candidates = np.arange(len(snapshot.chunks))
        else:
            selected = [snapshot.source_indices[name] for name in sources if name in snapshot.source_indices]
            candidates = np.concatenate(selected) if selected else np.zeros(0, dtype=np.int64)
        return snapshot.visible(candidates, access_level, today)

    @staticmethod
    def _reciprocal_ranks(values: np.ndarray, matched: np.ndarray) -> np.ndarray:
        """
        ``1 / (RRF_K + rank)`` of each value, best first; unmatched entries score 0.

        Args:
            values: Scores of one ranking (higher is better).
            matched: Which entries the ranking actually found (e.g. BM25 > 0).
        """
        scores = np.zeros(len(values), dtype=np.float64)
        found = np.flatnonzero(matched)
        if found.size:
            order = found[np.argsort(-values[found], kind="stable")]
            scores[order] = 1.0 / (RRF_K + np.arange(1, order.size + 1))
        return scores

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

        semantic_ranks = self._reciprocal_ranks(semantic, np.ones(len(semantic), dtype=bool))
        keyword_ranks = self._reciprocal_ranks(keyword, keyword > 0)
        fused = semantic_weight * semantic_ranks + (1 - semantic_weight) * keyword_ranks
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
        access_level: int = 0,
        today: Optional[date] = None,
    ) -> List[RetrievedChunk]:
        """
        Return matched chunks (plus neighbours for context), best first.

        Args:
            query: Standalone search text.
            snapshot: Corpus to search.
            top_k: Maximum matched chunks.
            semantic_weight: Weight of the embedding ranking vs the BM25 ranking in the fusion (0-1).
            threshold: Minimum relevance (reranker score, or cosine similarity
                when no reranker ran) for a chunk to count as a match.
            max_context_chunks: Cap on returned chunks including neighbours.
            expansion_radius: Neighbours added on each side of a match (same document).
            sources: Restrict to these source names; ``None`` searches all.
            access_level: The caller's tier level; higher-tier documents are skipped.
            today: The local date for effective-date filtering (default: today).

        Returns:
            Matched chunks first-ranked-first, each followed by its neighbours in
            document order. Empty when nothing clears ``threshold``.
        """
        if snapshot.is_empty or not query.strip():
            return []
        candidates = self._candidate_indices(snapshot, sources, access_level, today or date.today())
        if candidates.size == 0:
            return []

        semantic, keyword, fused = self._hybrid_scores(query, snapshot, candidates, semantic_weight)
        pool_size = min(len(candidates), max(top_k * RERANK_POOL_MULTIPLIER, MIN_RERANK_POOL))
        pool = np.argsort(-fused)[:pool_size]

        rerank_scores = None
        if self._reranker is not None:
            texts = [self._rerank_text(snapshot.chunks[candidates[p]]) for p in pool]
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
    def _rerank_text(chunk: IndexedChunk) -> str:
        """
        What the reranker scores: the document title, then the chunk.

        A chunk rarely says which document it is from ("## EDUCATION" in a CV
        never names the person), so without the title the cross-encoder scores
        "which university did X attend" low on the one chunk that answers it.
        """
        return f"{chunk.document_title}\n{chunk.content}" if chunk.document_title else chunk.content

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
