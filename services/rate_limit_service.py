"""
Per-key sliding-window request limiting (per end user, per client IP).

# ceiling: counters live in this process only — correct for the single-worker
# VPS deployment; move them to Redis if the API ever runs as several processes.
"""

# Standard library imports
import logging
import math
import threading
import time
from collections import deque
from typing import Deque, Dict, Optional

logger = logging.getLogger(__name__)

#: Length of every rate-limit window, in seconds.
WINDOW_SECONDS = 60
#: Idle keys are dropped once the table grows past this many entries.
PRUNE_THRESHOLD = 20_000


class RateLimitService:
    """Sliding-window limiter keyed by an arbitrary string (``user:…``, ``ip:…``)."""

    def __init__(self, clock=time.monotonic):
        """
        Args:
            clock: Monotonic time source in seconds (injectable for tests).
        """
        self._clock = clock
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int) -> Optional[int]:
        """
        Record one request for ``key`` if it is within ``limit`` per window.

        Args:
            key: Bucket identity.
            limit: Requests allowed per window; ``<= 0`` disables the check.

        Returns:
            ``None`` when allowed, otherwise seconds until a slot frees up.
        """
        if limit <= 0:
            return None
        now = self._clock()
        with self._lock:
            if len(self._hits) > PRUNE_THRESHOLD:
                self._prune(now)
            window = self._hits.setdefault(key, deque())
            while window and now - window[0] >= WINDOW_SECONDS:
                window.popleft()
            if len(window) >= limit:
                retry_after = max(1, math.ceil(WINDOW_SECONDS - (now - window[0])))
                logger.warning("Rate limit hit for %s", key.split(":", 1)[0])
                return retry_after
            window.append(now)
            return None

    def _prune(self, now: float) -> None:
        """Forget keys with no request in the current window. Caller holds the lock."""
        idle = [key for key, window in self._hits.items() if not window or now - window[-1] >= WINDOW_SECONDS]
        for key in idle:
            del self._hits[key]
