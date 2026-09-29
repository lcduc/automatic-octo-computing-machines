"""
Internal data classes describing indexed knowledge and retrieval results.
"""

# Standard library imports
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

#: Chunking strategy that keeps each file type's built-in splitting.
AUTO_STRATEGY = "auto"

#: How a document's text was extracted; decides what ``auto`` chunking means for it.
EXTRACTION_DOCLING = "docling"
EXTRACTION_OCR = "ocr"
EXTRACTION_LOCAL = "local"
#: Typed in the admin web rather than uploaded.
EXTRACTION_TEXT = "text"


@dataclass(frozen=True)
class ChunkingSpec:
    """How a document's text is split into chunks: a strategy name and its parameters."""

    strategy: str = AUTO_STRATEGY
    params: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, value: Optional[Dict[str, Any]]) -> "ChunkingSpec":
        """Build from the stored JSON form ``{"strategy": ..., **params}``; empty means ``auto``."""
        params = dict(value or {})
        return cls(strategy=params.pop("strategy", AUTO_STRATEGY), params=params)

    def to_json(self) -> Dict[str, Any]:
        """The stored JSON form."""
        return {"strategy": self.strategy, **self.params}


@dataclass(frozen=True)
class ChunkDraft:
    """A chunk produced by a chunking strategy, before it is embedded and stored."""

    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChunkingResult:
    """Chunks produced for a text plus warnings worth showing to an admin."""

    drafts: List[ChunkDraft]
    warnings: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExtractedDocument:
    """A parsed upload: its full text, how it was extracted, and its chunks."""

    text: str
    extraction_method: str
    chunking: ChunkingResult


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
    #: Lowest caller access level answered from this chunk's document (0 = everyone).
    access_level: int = 0
    #: Validity of the chunk's document (inclusive; ``None`` = open-ended).
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None


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
