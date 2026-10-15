"""
Two-lane scheduling of GPU work: chat requests before ingestion.

Chat-path work (query embedding, reranking) always starts as soon as a slot is
free. Ingestion work (bulk embedding, OCR) waits while any chat request is
waiting, and at most ``ingestion_limit`` of it runs at once (1: one OCR page at
a time), so a big upload never occupies every slot.

Waiting is bounded: a lane holds at most ``max_waiting`` queued calls and a call
waits at most its lane's timeout, then :class:`SchedulerBusyError` is raised so
overload becomes a clean "busy" answer instead of a growing backlog.
"""

# Standard library imports
import asyncio
import logging
from enum import Enum
from typing import Any, Callable, Dict, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class Lane(str, Enum):
    """Which kind of work a job is."""

    CHAT = "chat"
    INGESTION = "ingestion"


class SchedulerBusyError(RuntimeError):
    """No slot became free in time, or the lane's queue is full."""


class PriorityScheduler:
    """Runs blocking model calls in threads, chat lane first."""

    def __init__(self, slots: int, ingestion_limit: int, max_waiting: int,
                 chat_wait_seconds: float, ingestion_wait_seconds: float):
        """
        Args:
            slots: Jobs that may run at once (bounds GPU memory use).
            ingestion_limit: Ingestion jobs that may run at once (below ``slots``,
                so a chat request always finds room).
            max_waiting: Calls that may queue per lane; one more is refused at once.
            chat_wait_seconds: Longest a chat call waits for a slot.
            ingestion_wait_seconds: Longest an ingestion call waits for a slot.
        """
        if slots < 1 or not 0 < ingestion_limit < slots:
            raise ValueError("need slots >= 2 and 0 < ingestion_limit < slots")
        if max_waiting < 1 or chat_wait_seconds <= 0 or ingestion_wait_seconds <= 0:
            raise ValueError("need max_waiting >= 1 and positive wait timeouts")
        self._slots = slots
        self._ingestion_limit = ingestion_limit
        self._max_waiting = max_waiting
        self._wait_seconds: Dict[Lane, float] = {Lane.CHAT: chat_wait_seconds, Lane.INGESTION: ingestion_wait_seconds}
        self._condition = asyncio.Condition()
        self._running = 0
        self._ingestion_running = 0
        self._waiting: Dict[Lane, int] = {Lane.CHAT: 0, Lane.INGESTION: 0}

    def _can_start(self, lane: Lane) -> bool:
        """Whether a job of ``lane`` may start now (caller holds the condition)."""
        if self._running >= self._slots:
            return False
        if lane == Lane.CHAT:
            return True
        return self._waiting[Lane.CHAT] == 0 and self._ingestion_running < self._ingestion_limit

    async def _acquire(self, lane: Lane) -> None:
        """
        Take a slot for ``lane`` (caller holds the condition).

        Raises:
            SchedulerBusyError: The lane's queue is full or the wait timed out.
        """
        if self._waiting[lane] >= self._max_waiting:
            raise SchedulerBusyError(f"{lane.value} queue is full ({self._max_waiting} waiting)")
        self._waiting[lane] += 1
        try:
            await asyncio.wait_for(self._condition.wait_for(lambda: self._can_start(lane)), self._wait_seconds[lane])
        except asyncio.TimeoutError:
            raise SchedulerBusyError(f"no {lane.value} slot free within {self._wait_seconds[lane]:g}s") from None
        finally:
            self._waiting[lane] -= 1
            if lane == Lane.CHAT:
                # Ingestion waits on chat waiters; a chat call that leaves may unblock it.
                self._condition.notify_all()
        self._running += 1
        if lane == Lane.INGESTION:
            self._ingestion_running += 1

    async def run(self, lane: Lane, function: Callable[..., T], *args: Any) -> T:
        """
        Wait for a slot in ``lane``, then run ``function(*args)`` in a worker thread.

        Raises:
            SchedulerBusyError: No slot in time (see the class docstring).
        """
        async with self._condition:
            try:
                await self._acquire(lane)
            except SchedulerBusyError:
                logger.warning("Model-server busy, refusing a %s call: %s", lane.value, self.stats())
                raise
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
        return {
            "running": self._running,
            "ingestion_running": self._ingestion_running,
            "chat_waiting": self._waiting[Lane.CHAT],
            "ingestion_waiting": self._waiting[Lane.INGESTION],
        }
