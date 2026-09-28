"""
Per-client-IP request ceiling across every endpoint except health probes.
"""

# Local imports
from config.settings import Config
from .asgi_helpers import QUIET_PATH_PREFIXES, send_json


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
            retry_after = container.rate_limiter.hit(f"ip:{client[0]}", Config.Security.RATE_LIMIT_IP_PER_MINUTE())
            if retry_after is not None:
                return await send_json(
                    send,
                    429,
                    {"detail": "Too many requests"},
                    [(b"retry-after", str(retry_after).encode())],
                )
        await self.app(scope, receive, send)
