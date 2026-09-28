"""
Rejects request bodies larger than the upload limit, declared or streamed.
"""

# Local imports
from config.settings import Config
from .asgi_helpers import header_value, send_json

#: Allowance above ``MAX_FILE_SIZE`` for multipart framing and form fields.
BODY_OVERHEAD_BYTES = 1024 * 1024


class BodySizeLimitMiddleware:
    """Rejects request bodies larger than the upload limit (declared or streamed)."""

    def __init__(self, app):
        self.app = app
        self._max_bytes = Config.File.MAX_FILE_SIZE() + BODY_OVERHEAD_BYTES

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        declared = header_value(scope, b"content-length")
        if declared.isdigit() and int(declared) > self._max_bytes:
            return await send_json(send, 413, {"detail": "Request body too large"})

        received = {"bytes": 0}

        async def limited_receive():
            message = await receive()
            if message["type"] == "http.request":
                received["bytes"] += len(message.get("body", b""))
                if received["bytes"] > self._max_bytes:
                    raise ValueError("Request body too large")
            return message

        await self.app(scope, limited_receive, send)
