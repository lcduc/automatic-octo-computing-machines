"""
What one chat turn did, step by step (ADM-05, ORC-06): filled in by the
pipeline while it runs, stored once per answer by ``ChatService``.
"""

# Standard library imports
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterator, List, Optional

#: Routes a turn can take through the pipeline.
ROUTE_GUARD = "guard"
ROUTE_SMALLTALK = "smalltalk"
ROUTE_TOPIC = "sensitive_topic"
ROUTE_HUMAN = "human_request"
ROUTE_LOGIN = "login_required"
ROUTE_TOOL = "tool"
ROUTE_RAG = "rag"
ROUTE_CACHE = "cache"
ROUTE_FALLBACK = "fallback"

#: Decimal places kept for retrieval scores.
SCORE_DIGITS = 4


@dataclass(frozen=True)
class ToolCallRecord:
    """One tool the model called. Argument values are not kept: they may carry what the user typed."""

    name: str
    ok: bool
    duration_ms: int
    argument_names: List[str] = field(default_factory=list)


@dataclass
class TurnTrace:
    """Diagnostics of one turn; every field is optional because most routes skip most steps."""

    route: Optional[str] = None
    intent: Optional[str] = None
    #: Retrieval filters in force: tier level, date, sources, threshold, top-k.
    filters: Dict[str, Any] = field(default_factory=dict)
    #: Ranked chunks with their scores (``matched`` is false for context neighbours).
    chunks: List[Dict[str, Any]] = field(default_factory=list)
    tool_calls: List[ToolCallRecord] = field(default_factory=list)
    #: Digest of the system prompt that produced the answer.
    prompt_version: Optional[str] = None
    #: Milliseconds spent per step (``guard``, ``intent``, ``rewrite``, ``retrieval``, ``generation``, ``tools``).
    steps_ms: Dict[str, int] = field(default_factory=dict)

    @contextmanager
    def step(self, name: str) -> Iterator[None]:
        """Time a block and add it to :attr:`steps_ms` (repeated steps accumulate)."""
        started = time.perf_counter()
        try:
            yield
        finally:
            elapsed = int((time.perf_counter() - started) * 1000)
            self.steps_ms[name] = self.steps_ms.get(name, 0) + elapsed

    def record_chunks(self, results: List[Any]) -> None:
        """Keep ids and scores of retrieved chunks (``RetrievedChunk`` items)."""
        self.chunks = [
            {
                "chunk_id": item.chunk.chunk_id,
                "document_id": item.chunk.document_id,
                "relevance": round(item.relevance, SCORE_DIGITS),
                "semantic": round(item.semantic_score, SCORE_DIGITS),
                "keyword": round(item.keyword_score, SCORE_DIGITS),
                "rerank": round(item.rerank_score, SCORE_DIGITS) if item.rerank_score is not None else None,
                "matched": item.matched,
            }
            for item in results
        ]

    def tool_calls_json(self) -> List[Dict[str, Any]]:
        """Tool calls as plain dicts for a JSON column."""
        return [asdict(call) for call in self.tool_calls]
