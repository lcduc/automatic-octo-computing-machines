"""
The time budget of one chat turn, shared by every stage that waits on a model.
"""

# Standard library imports
import asyncio
from typing import AsyncIterator, TypeVar

StreamItem = TypeVar("StreamItem")


class TurnDeadline:
    """A point on the event loop's clock after which the turn fails with ``asyncio.TimeoutError``."""

    def __init__(self, at: float):
        """
        Args:
            at: Deadline in ``loop.time()`` seconds.
        """
        self._at = at

    @classmethod
    def after(cls, seconds: float) -> "TurnDeadline":
        """A deadline ``seconds`` from now on the running loop's clock."""
        return cls(asyncio.get_running_loop().time() + seconds)

    def remaining(self) -> float:
        """Seconds left (raises ``asyncio.TimeoutError`` when already passed)."""
        remaining = self._at - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError()
        return remaining

    async def guard(self, stream: AsyncIterator[StreamItem]) -> AsyncIterator[StreamItem]:
        """Re-yield ``stream``, failing with ``asyncio.TimeoutError`` if the next item misses the deadline."""
        iterator = stream.__aiter__()
        while True:
            try:
                item = await asyncio.wait_for(iterator.__anext__(), timeout=self.remaining())
            except StopAsyncIteration:
                return
            yield item
