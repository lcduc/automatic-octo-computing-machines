"""
In-memory search index over the knowledge stored in PostgreSQL.

PostgreSQL is the source of truth; this index is a read-only snapshot of every
searchable chunk (texts, normalized embeddings, a BM25 model and metadata),
rebuilt after each knowledge edit and swapped in atomically so concurrent
searches always see one consistent version.
"""

# Standard library imports
import asyncio
import logging
from dataclasses import dataclass
from datetime import date
from typing import Callable, Dict, List, Optional

# Third-party imports
import numpy as np
from rank_bm25 import BM25Okapi

# Local imports
from core.storage.database import Database
from core.storage.knowledge_repository import IndexRow, KnowledgeRepository
from models.knowledge import IndexedChunk
from utils.text_utils import TextUtils

logger = logging.getLogger(__name__)

#: Access level of documents whose tier is unknown: no caller reaches them (fail closed).
UNREACHABLE_LEVEL = 32_000
#: Day ordinals standing in for open-ended validity.
OPEN_START = date.min.toordinal()
OPEN_END = date.max.toordinal()
TierLevel = Callable[[str], int]


def anonymous_only(tier: str) -> int:
    """Default tier mapping: public documents only; any other tier is unreachable."""
    return 0 if tier == "anonymous" else UNREACHABLE_LEVEL


@dataclass(frozen=True)
class KnowledgeSnapshot:
    """
    One immutable version of the searchable corpus.

    ``chunks[i]`` and ``embeddings[i]`` describe the same chunk; chunks are
    ordered by document then position, so ``i ± 1`` are neighbours whenever
    their ``document_id`` matches.
    """

    version: int
    chunks: List[IndexedChunk]
    #: L2-normalized float32 matrix, shape (len(chunks), dim); empty (0, 0) when no chunks.
    embeddings: np.ndarray
    bm25: Optional[BM25Okapi]
    #: Source name -> indices of its chunks, for fast source filtering.
    source_indices: Dict[str, np.ndarray]
    #: Per chunk: lowest caller access level, and first/last valid day (ordinals, inclusive).
    access_levels: np.ndarray = None
    valid_from: np.ndarray = None
    valid_to: np.ndarray = None

    @property
    def is_empty(self) -> bool:
        """True when nothing is searchable."""
        return not self.chunks

    def visible(self, candidates: np.ndarray, access_level: int, today: date) -> np.ndarray:
        """
        The candidates a caller may be answered from today (checklist Invariant 4):
        their document's tier is at or below ``access_level`` and ``today`` is
        within its effective dates. Applied in code before any ranking, never
        left to the prompt.
        """
        if candidates.size == 0:
            return candidates
        day = today.toordinal()
        mask = (
            (self.access_levels[candidates] <= access_level)
            & (self.valid_from[candidates] <= day)
            & (self.valid_to[candidates] >= day)
        )
        return candidates[mask]

    @classmethod
    def empty(cls, version: int = 0) -> "KnowledgeSnapshot":
        """A snapshot with no chunks."""
        none = np.zeros(0, dtype=np.int32)
        return cls(version, [], np.zeros((0, 0), dtype=np.float32), None, {}, none, none, none)

    @classmethod
    def build(cls, rows: List[IndexRow], version: int, tier_level: TierLevel = anonymous_only) -> "KnowledgeSnapshot":
        """
        Build a snapshot from repository rows (CPU-bound; run off the event loop).

        Args:
            rows: Searchable chunks ordered by document then position.
            version: Monotonic version number of the new snapshot.
            tier_level: Tier name -> access level; unknown tiers must map above every caller.
        """
        if not rows:
            return cls.empty(version)

        chunks = [
            IndexedChunk(
                chunk_id=str(row.chunk_id),
                document_id=str(row.document_id),
                position=row.position,
                content=row.content,
                document_title=row.document_title,
                source=row.source_name,
                source_priority=float(row.source_priority),
                metadata={
                    **({"filename": row.original_filename} if row.original_filename else {}),
                    **(row.document_metadata or {}),
                    **(row.chunk_metadata or {}),
                },
                access_level=_level(tier_level, row.access_tier),
                effective_from=row.effective_from,
                effective_to=row.effective_to,
            )
            for row in rows
        ]
        embeddings = np.vstack([np.asarray(row.embedding, dtype=np.float32) for row in rows])
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        embeddings = embeddings / np.where(norms == 0, 1.0, norms)

        # Titles are included so a keyword match on the document name counts.
        tokenized = [TextUtils.tokenize_for_search(f"{c.document_title} {c.content}") for c in chunks]
        bm25 = BM25Okapi(tokenized)

        by_source: Dict[str, List[int]] = {}
        for index, chunk in enumerate(chunks):
            by_source.setdefault(chunk.source, []).append(index)
        source_indices = {name: np.asarray(indices, dtype=np.int64) for name, indices in by_source.items()}
        access_levels = np.fromiter((chunk.access_level for chunk in chunks), dtype=np.int32, count=len(chunks))
        valid_from = np.fromiter(
            (chunk.effective_from.toordinal() if chunk.effective_from else OPEN_START for chunk in chunks),
            dtype=np.int64, count=len(chunks),
        )
        valid_to = np.fromiter(
            (chunk.effective_to.toordinal() if chunk.effective_to else OPEN_END for chunk in chunks),
            dtype=np.int64, count=len(chunks),
        )
        return cls(version, chunks, embeddings, bm25, source_indices, access_levels, valid_from, valid_to)


def _level(tier_level: TierLevel, tier: str) -> int:
    """Access level of a document tier; a tier the mapping does not know is unreachable."""
    level = tier_level(tier)
    return UNREACHABLE_LEVEL if tier != "anonymous" and level == 0 else level


class KnowledgeIndex:
    """
    Holds the current :class:`KnowledgeSnapshot` and rebuilds it on demand.

    # ceiling: whole corpus held in RAM and scanned brute-force (~1.5 KB/chunk
    # at 384 dims, a few ms per query for 100k chunks); move semantic search to
    # a pgvector HNSW index when the corpus passes ~500k chunks.
    """

    def __init__(self, database: Database, tier_level: TierLevel = anonymous_only):
        """
        Args:
            database: Connected database the snapshot is loaded from.
            tier_level: Document tier name -> access level.
        """
        self._database = database
        self._tier_level = tier_level
        self._snapshot = KnowledgeSnapshot.empty()
        self._refresh_lock = asyncio.Lock()
        self._refresh_requested = False
        self._background_refresh: Optional[asyncio.Task] = None

    @property
    def snapshot(self) -> KnowledgeSnapshot:
        """The current snapshot (never ``None``)."""
        return self._snapshot

    async def refresh(self) -> KnowledgeSnapshot:
        """
        Reload every searchable chunk from the database and swap the snapshot in.

        Concurrent calls are serialized; each produces a fresh snapshot.
        """
        async with self._refresh_lock:
            logger.debug("Refreshing knowledge index")
            async with self._database.session() as session:
                rows = await KnowledgeRepository(session).load_index_rows()
            snapshot = await asyncio.to_thread(KnowledgeSnapshot.build, rows, self._snapshot.version + 1, self._tier_level)
            self._snapshot = snapshot
            logger.info(
                "Knowledge index v%d ready: %d chunks from %d sources",
                snapshot.version,
                len(snapshot.chunks),
                len(snapshot.source_indices),
            )
            return snapshot

    def request_refresh(self) -> None:
        """
        Schedule a refresh without waiting for it; bursts coalesce into one rebuild.

        Used by background ingestion so a batch of uploads triggers one or two
        rebuilds instead of one per file.
        """
        self._refresh_requested = True
        if self._background_refresh is None or self._background_refresh.done():
            self._background_refresh = asyncio.create_task(self._drain_refresh_requests())

    async def _drain_refresh_requests(self) -> None:
        """Keep refreshing while new requests arrived during the previous rebuild."""
        while self._refresh_requested:
            self._refresh_requested = False
            try:
                await self.refresh()
            except Exception:
                logger.exception("Background knowledge index refresh failed")
