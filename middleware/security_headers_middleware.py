"""
Defensive response headers (no framing, no sniffing, strict CSP, HSTS in production).
"""

# Local imports
from config.settings import Config

#: Interactive API docs need inline scripts/styles, so they get a looser CSP.
DOCS_PATH_PREFIXES = ("/docs", "/redoc", "/openapi.json")
HSTS_VALUE = "max-age=31536000; includeSubDomains"


class SecurityHeadersMiddleware:
    """Adds defensive headers to every response."""

    def __init__(self, app):
        self.app = app
        self._hsts = Config.Server.IS_PRODUCTION()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        is_docs = scope["path"].startswith(DOCS_PATH_PREFIXES)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"strict-origin-when-cross-origin"),
                        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                    ]
                )
                if not is_docs:
                    headers.append((b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"))
                if self._hsts:
                    headers.append((b"strict-transport-security", HSTS_VALUE.encode()))
            await send(message)

        await self.app(scope, receive, send_with_headers)
