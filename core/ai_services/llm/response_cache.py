"""
In-process TTL + LRU cache for generated LLM answers.

Extracted from ``ChatbotService`` so the caching policy lives in one testable
place instead of being interleaved with prompt building and API calls.
"""

# Standard library imports
import hashlib
import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ResponseCache:
    """
    Bounded cache of query/context keyed LLM answers.

    Entries expire after ``ttl_seconds``; when the cache is full the
    least-recently-used entry is evicted.
    """

    def __init__(self, max_entries: int, ttl_seconds: int):
        """
        Args:
            max_entries: Hard cap on stored answers before LRU eviction kicks in.
            ttl_seconds: Age after which an entry is treated as a miss.
        """
        self._max_entries = max(1, max_entries)
        self._ttl_seconds = ttl_seconds
        self._entries: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    @staticmethod
    def build_key(
        query: str,
        context: str = "",
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """
        Build a deterministic cache key.

        The context and history are part of the key: the same question against a
        different corpus or conversation must not reuse a previous answer.
        """
        history_digest = ""
        if history:
            joined = "".join(str(message.get("content", "")) for message in history)
            history_digest = hashlib.md5(joined.encode("utf-8")).hexdigest()[:8]
        raw = f"{query.strip().lower()}|{context}|{history_digest}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def get(self, key: str) -> Optional[str]:
        """Return the cached answer for ``key``, or ``None`` when absent/expired."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return None

            if time.time() - entry["created_at"] > self._ttl_seconds:
                del self._entries[key]
                self._misses += 1
                return None

            entry["last_accessed"] = time.time()
            self._hits += 1
            return entry["response"]

    def set(self, key: str, response: str) -> None:
        """Store ``response`` under ``key``, evicting the LRU entry if needed."""
        with self._lock:
            if key not in self._entries and len(self._entries) >= self._max_entries:
                self._evict_lru()
            now = time.time()
            self._entries[key] = {
                "response": response,
                "created_at": now,
                "last_accessed": now,
            }

    def _evict_lru(self) -> None:
        """Drop the least recently accessed entry. Caller must hold the lock."""
        oldest_key = min(
            self._entries, key=lambda k: self._entries[k]["last_accessed"]
        )
        del self._entries[oldest_key]

    def clear(self) -> int:
        """Empty the cache and return how many entries were removed."""
        with self._lock:
            removed = len(self._entries)
            self._entries.clear()
            return removed

    @property
    def size(self) -> int:
        """Number of entries currently held."""
        return len(self._entries)

    def get_stats(self) -> Dict[str, Any]:
        """Hit/miss counters and hit rate for monitoring endpoints."""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total * 100) if total else 0.0
            return {
                "size": len(self._entries),
                "max_entries": self._max_entries,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": f"{hit_rate:.1f}%",
            }
