"""
Per-client-IP request ceiling across every endpoint except health probes.
"""

# Standard library imports
import logging

# Local imports
from config.settings import Config
from core.storage.tables.usage_tables import WINDOW_MINUTE
from services.rate_limit_service import Limit, hashed
from .asgi_helpers import QUIET_PATH_PREFIXES, send_json

logger = logging.getLogger(__name__)


class IpRateLimitMiddleware:
    """Per-client-IP request ceiling across all endpoints except health probes."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"].startswith(QUIET_PATH_PREFIXES):
            return await self.app(scope, receive, send)
        container = getattr(scope["app"].state, "container", None)
        client = scope.get("client")
        if container is not None and client:
            limit = Limit(f"http:ip:{hashed(client[0])}", WINDOW_MINUTE, Config.Security.RATE_LIMIT_IP_PER_MINUTE())
            try:
                retry_after = await container.rate_limiter.hit([limit])
            except Exception:
                # A coarse guard: when the counter store is down the endpoint itself fails properly.
                logger.exception("IP rate limit check failed; letting the request through")
                retry_after = None
            if retry_after is not None:
                return await send_json(
                    send,
                    429,
                    {"detail": "Too many requests"},
                    [(b"retry-after", str(retry_after).encode())],
                )
        await self.app(scope, receive, send)
