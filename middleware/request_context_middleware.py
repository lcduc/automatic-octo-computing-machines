"""
Request id for every request (bound to the task for logs) and one log line per request.
"""

# Standard library imports
import logging
import re
import time
import uuid

# Local imports
from utils.request_context import request_id_var
from .asgi_helpers import QUIET_PATH_PREFIXES, header_value

logger = logging.getLogger(__name__)

#: Incoming ``X-Request-ID`` values accepted as-is (e.g. from the widget's server).
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9\-]{8,64}$")


class RequestContextMiddleware:
    """Binds a request id to the task (for logs), echoes it, and logs one line per request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        incoming = header_value(scope, b"x-request-id")
        request_id = incoming if REQUEST_ID_PATTERN.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_holder = {"status": 500}

        async def send_with_id(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                message.setdefault("headers", []).append((b"x-request-id", request_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            if not scope["path"].startswith(QUIET_PATH_PREFIXES):
                logger.info(
                    "%s %s -> %d in %.0f ms",
                    scope["method"],
                    scope["path"],
                    status_holder["status"],
                    (time.perf_counter() - started) * 1000,
                )
            request_id_var.reset(token)
