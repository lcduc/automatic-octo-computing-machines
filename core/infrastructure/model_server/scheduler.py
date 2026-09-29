"""
Two-lane scheduling of GPU work: chat requests before ingestion.

Chat-path work (query embedding, reranking) always starts as soon as a slot is
free. Ingestion work (bulk embedding, OCR) waits while any chat request is
waiting, and at most ``ingestion_limit`` of it runs at once (1: one OCR page at
a time), so a big upload never occupies every slot.
"""

# Standard library imports
import asyncio
import logging
from enum import Enum
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class Lane(str, Enum):
    """Which kind of work a job is."""

    CHAT = "chat"
    INGESTION = "ingestion"


class PriorityScheduler:
    """Runs blocking model calls in threads, chat lane first."""

    def __init__(self, slots: int, ingestion_limit: int):
        """
        Args:
            slots: Jobs that may run at once (bounds GPU memory use).
            ingestion_limit: Ingestion jobs that may run at once (below ``slots``,
                so a chat request always finds room).
        """
        if slots < 1 or not 0 < ingestion_limit < slots:
            raise ValueError("need slots >= 2 and 0 < ingestion_limit < slots")
        self._slots = slots
        self._ingestion_limit = ingestion_limit
        self._condition = asyncio.Condition()
        self._running = 0
        self._ingestion_running = 0
        self._chat_waiting = 0

    def _can_start(self, lane: Lane) -> bool:
        """Whether a job of ``lane`` may start now (caller holds the condition)."""
        if self._running >= self._slots:
            return False
        if lane == Lane.CHAT:
            return True
        return self._chat_waiting == 0 and self._ingestion_running < self._ingestion_limit

    async def run(self, lane: Lane, function: Callable[..., T], *args: Any) -> T:
        """Wait for a slot in ``lane``, then run ``function(*args)`` in a worker thread."""
        async with self._condition:
            if lane == Lane.CHAT:
                self._chat_waiting += 1
            try:
                await self._condition.wait_for(lambda: self._can_start(lane))
            finally:
                if lane == Lane.CHAT:
                    self._chat_waiting -= 1
            self._running += 1
            if lane == Lane.INGESTION:
                self._ingestion_running += 1
        try:
            return await asyncio.to_thread(function, *args)
        finally:
            async with self._condition:
                self._running -= 1
                if lane == Lane.INGESTION:
                    self._ingestion_running -= 1
                self._condition.notify_all()

    def stats(self) -> dict:
        """Current load, for ``/ready``."""
        return {"running": self._running, "ingestion_running": self._ingestion_running, "chat_waiting": self._chat_waiting}
