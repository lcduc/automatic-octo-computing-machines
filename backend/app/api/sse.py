"""
Server-Sent Events framing with keep-alive pings.
"""

# Standard library imports
import asyncio
import json
import logging
from typing import Any, AsyncIterator, Dict

logger = logging.getLogger(__name__)

#: Seconds of silence after which a comment line is sent so proxies keep the stream open.
HEARTBEAT_SECONDS = 15
#: Headers that stop proxies (nginx, Next.js) from buffering the stream.
STREAM_HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}
PING_FRAME = ": ping\n\n"


def encode_event(event: Dict[str, Any]) -> str:
    """Frame one event as ``event: <type>`` + ``data: <json>``."""
    return f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


async def sse_stream(events: AsyncIterator[Dict[str, Any]]) -> AsyncIterator[str]:
    """
    Encode ``events`` as SSE, inserting pings while the next event is slow.

    If the client disconnects, the pending step of ``events`` is cancelled and
    the generator closed, so the producer can persist what it has.
    """
    iterator = events.__aiter__()
    pending = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(iterator.__anext__())
            done, _ = await asyncio.wait({pending}, timeout=HEARTBEAT_SECONDS)
            if not done:
                yield PING_FRAME
                continue
            try:
                event = pending.result()
            except StopAsyncIteration:
                return
            finally:
                pending = None
            yield encode_event(event)
    except Exception:
        logger.exception("Chat stream failed")
        yield encode_event({"type": "error", "message": "Xin lỗi, hệ thống đang gặp sự cố."})
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            try:
                await pending
            except (asyncio.CancelledError, StopAsyncIteration, Exception):
                pass
        await iterator.aclose()
