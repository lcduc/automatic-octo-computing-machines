"""
Internal data classes describing indexed knowledge and retrieval results.
"""

# Standard library imports
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class IndexedChunk:
    """One searchable chunk as held by the in-memory knowledge index."""

    chunk_id: str
    document_id: str
    position: int
    content: str
    document_title: str
    source: str
    #: Retrieval score multiplier of the chunk's source (1.0 = neutral).
    source_priority: float
    #: Document metadata overlaid with chunk metadata (chunk keys win).
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievedChunk:
    """A chunk selected for the prompt context, with its scores."""

    chunk: IndexedChunk
    #: Relevance used for gating: reranker score when reranking ran, else fused score.
    relevance: float
    semantic_score: float = 0.0
    keyword_score: float = 0.0
    #: False for neighbours pulled in only to give a matched chunk its surrounding text.
    matched: bool = True
    rerank_score: Optional[float] = None
