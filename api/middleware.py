"""
Custom middleware for the FastAPI application.
Provides request logging, security headers, rate limiting, and error handling.
"""

# Standard library imports
import asyncio
import hmac
import logging
import time
import uuid
from typing import Callable, Dict, List

# Third-party imports
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# Local imports
from config.settings import Config

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to log all requests and responses with timing information.
    Provides comprehensive request tracking for monitoring and debugging.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        request_id = uuid.uuid4().hex[:8]
        client_host = request.client.host if request.client else "unknown"

        logger.info(
            "-> %s %s client=%s request_id=%s",
            request.method,
            request.url.path,
            client_host,
            request_id,
        )

        response = await call_next(request)
        process_time = time.time() - start_time

        logger.info(
            "<- %s %s status=%s duration=%.3fs request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            process_time,
            request_id,
        )

        response.headers["X-Process-Time"] = f"{process_time:.3f}"
        response.headers["X-Request-ID"] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add security headers for enhanced application security.
    Implements common security best practices for web applications.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        # Add security headers to prevent common attacks
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        return response


class RateLimitingMiddleware(BaseHTTPMiddleware):
    """
    Sliding-window rate limiting per client IP plus a concurrency ceiling.

    Counters are per worker process; with more than one Uvicorn worker the
    effective limits are multiplied by the worker count. Use a shared store
    (e.g. Redis) or an edge proxy if a cluster-wide limit is required.
    """

    #: Idle clients are dropped from the tracking map after this many windows.
    STALE_CLIENT_WINDOWS = 2
    #: Tracked client IPs are pruned once the map grows past this size.
    PRUNE_THRESHOLD = 10_000

    def __init__(self, app, max_requests: int = 100, window_seconds: int = 60, max_concurrent: int = 10):
        """
        Args:
            app: Wrapped ASGI application.
            max_requests: Requests allowed per client IP per window.
            window_seconds: Sliding window width in seconds.
            max_concurrent: In-flight requests allowed in this process.
        """
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.max_concurrent = max_concurrent
        self._request_times: Dict[str, List[float]] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent)

    def _prune_stale_clients(self, now: float) -> None:
        """Drop tracking entries for clients idle for several windows."""
        cutoff = now - self.window_seconds * self.STALE_CLIENT_WINDOWS
        stale = [ip for ip, times in self._request_times.items() if not times or times[-1] < cutoff]
        for ip in stale:
            del self._request_times[ip]

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()

        # Bound memory: without this the tracking map grows once per unique IP.
        if len(self._request_times) > self.PRUNE_THRESHOLD:
            self._prune_stale_clients(now)

        window_start = now - self.window_seconds
        recent = [t for t in self._request_times.get(client_ip, []) if t > window_start]

        if len(recent) >= self.max_requests:
            self._request_times[client_ip] = recent
            logger.warning("Rate limit exceeded for %s", client_ip)
            return Response(
                content="Rate limit exceeded",
                status_code=429,
                headers={"Retry-After": str(self.window_seconds)},
            )

        if self._semaphore.locked():
            logger.warning("Concurrent request limit reached (%d)", self.max_concurrent)
            return Response(
                content="Server busy, too many concurrent requests. Please try again later.",
                status_code=503,
                headers={"Retry-After": "5"},
            )

        recent.append(now)
        self._request_times[client_ip] = recent

        async with self._semaphore:
            response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(self.max_requests)
            response.headers["X-RateLimit-Remaining"] = str(
                max(0, self.max_requests - len(recent))
            )
            response.headers["X-RateLimit-Reset"] = str(int(now + self.window_seconds))
            return response


class APIKeyMiddleware(BaseHTTPMiddleware):
    """
    Optional shared-secret check via the ``X-API-Key`` header.

    Only installed when ``API_KEY`` is set (see ``setup_middleware``) — on a
    private VPS reachable only over a VPN/internal network this is often
    unnecessary, so it stays fully opt-in rather than a mandatory auth system.
    Health checks and API docs are exempt so monitoring and manual review keep
    working without a key.
    """

    #: Paths reachable without a key even when one is configured.
    EXEMPT_PATHS = frozenset({"/", "/docs", "/redoc", "/openapi.json"})

    def __init__(self, app, api_key: str):
        """
        Args:
            app: Wrapped ASGI application.
            api_key: Expected secret value; never empty (caller checks first).
        """
        super().__init__(app)
        self._api_key = api_key

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        provided = request.headers.get("X-API-Key", "")
        if not hmac.compare_digest(provided, self._api_key):
            logger.warning("Rejected request to %s: missing/invalid API key", request.url.path)
            return Response(content="Invalid or missing API key", status_code=401)

        return await call_next(request)


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to handle and log unhandled errors gracefully.
    Prevents application crashes and provides consistent error responses.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            return await call_next(request)
        except Exception:
            request_id = uuid.uuid4().hex[:8]
            logger.exception(
                "Unhandled error in %s %s request_id=%s",
                request.method,
                request.url.path,
                request_id,
            )
            # Generic body: never leak internals to the caller.
            return Response(
                content="Internal server error",
                status_code=500,
                headers={"Content-Type": "text/plain", "X-Request-ID": request_id},
            )


class CacheControlMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add appropriate cache control headers.
    Optimizes caching for static content while preventing API response caching.
    """

    def __init__(self, app, static_max_age: int = 3600, api_max_age: int = 0):
        super().__init__(app)
        self.static_max_age = static_max_age
        self.api_max_age = api_max_age

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        # Set cache headers based on content type and path
        if request.url.path.startswith("/static/"):
            # Static content - allow caching for performance
            response.headers["Cache-Control"] = f"public, max-age={self.static_max_age}"
        elif request.url.path.startswith("/docs") or request.url.path.startswith(
            "/redoc"
        ):
            # Documentation - allow caching
            response.headers["Cache-Control"] = f"public, max-age={self.static_max_age}"
        else:
            # API endpoints - no cache to ensure fresh data
            response.headers["Cache-Control"] = (
                f"no-cache, no-store, max-age={self.api_max_age}"
            )

        return response


def setup_middleware(
    app, enable_rate_limiting: bool = False, enable_request_logging: bool = True
) -> None:
    """
    Register the application middleware stack.

    Args:
        app: FastAPI application to configure.
        enable_rate_limiting: Enable per-IP rate limiting and the concurrency cap.
        enable_request_logging: Log one line per request with its duration.
    """
    if enable_request_logging:
        app.add_middleware(RequestLoggingMiddleware)
        logger.info("Request logging middleware enabled")

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(CacheControlMiddleware)

    if enable_rate_limiting:
        app.add_middleware(
            RateLimitingMiddleware,
            max_requests=Config.Server.RATE_LIMIT_MAX_REQUESTS(),
            window_seconds=Config.Server.RATE_LIMIT_WINDOW_SECONDS(),
            max_concurrent=Config.Server.RATE_LIMIT_MAX_CONCURRENT(),
        )
        logger.info("Rate limiting middleware enabled")

    api_key = Config.Server.API_KEY()
    if api_key:
        app.add_middleware(APIKeyMiddleware, api_key=api_key)
        logger.info("API key middleware enabled")
    else:
        logger.info("API key middleware disabled (no API_KEY configured)")

    app.add_middleware(ErrorHandlingMiddleware)
    logger.info("Middleware stack configured")
