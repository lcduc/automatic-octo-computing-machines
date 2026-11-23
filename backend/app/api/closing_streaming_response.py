"""
Streaming response that runs a callback once it is finished, however it ends.
"""

# Standard library imports
from typing import Any, Callable

# Third-party imports
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send


class ClosingStreamingResponse(StreamingResponse):
    """
    ``StreamingResponse`` that calls ``on_close`` after sending, whether the body
    finished, failed or never started.

    A ``finally`` inside the body iterator is not enough: when the client is gone
    before the body starts, Starlette never starts the iterator, so its cleanup
    never runs.
    """

    def __init__(self, content: Any, on_close: Callable[[], None], **kwargs: Any) -> None:
        """
        Args:
            content: The body iterator, as for ``StreamingResponse``.
            on_close: Called once the response is over; must not raise.
            **kwargs: Passed to ``StreamingResponse`` (media type, headers).
        """
        super().__init__(content, **kwargs)
        self._on_close = on_close

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Send the response, then run ``on_close``."""
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._on_close()
