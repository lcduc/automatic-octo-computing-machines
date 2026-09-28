"""
App-wide HTTP middleware, written as plain ASGI so streaming responses and
``contextvars`` (the request id used by logging) behave correctly.

Registered by ``main.py`` in this order (outermost first): CORS, request
context, security headers, body size limit, per-IP rate limit, admin audit.
"""

# Standard library imports
import json
import logging
import re
import time
import uuid
from typing import Any, Iterable, Tuple

# Local imports
from config.settings import Config
from services.audit_service import AuditRecord
from utils.request_context import request_id_var
from .dependencies import ADMIN_COOKIE_PATH, UNSAFE_METHODS

logger = logging.getLogger(__name__)

#: Incoming ``X-Request-ID`` values accepted as-is (e.g. from the Next.js server).
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9\-]{8,64}$")
#: Paths never rate limited or logged per request (health probes).
QUIET_PATH_PREFIXES = ("/health",)
#: Interactive API docs need inline scripts/styles, so they get a looser CSP.
DOCS_PATH_PREFIXES = ("/docs", "/redoc", "/openapi.json")
#: Allowance above ``MAX_FILE_SIZE`` for multipart framing and form fields.
BODY_OVERHEAD_BYTES = 1024 * 1024
HSTS_VALUE = "max-age=31536000; includeSubDomains"
#: Largest request/response body kept verbatim in an audit entry.
AUDIT_MAX_BODY_BYTES = 16_384
#: Sign-ins are audited with the submitted e-mail, since no one is signed in yet.
LOGIN_PATH_SUFFIX = "/auth/login"


def _header(scope, name: bytes) -> str:
    """First value of a request header, decoded, or ``""``."""
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return ""


async def _send_json(send, status: int, body: dict, extra_headers: Iterable[Tuple[bytes, bytes]] = ()) -> None:
    """Send a complete JSON response from inside a middleware."""
    payload = json.dumps(body).encode("utf-8")
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())]
    await send({"type": "http.response.start", "status": status, "headers": headers + list(extra_headers)})
    await send({"type": "http.response.body", "body": payload})


class RequestContextMiddleware:
    """Binds a request id to the task (for logs), echoes it, and logs one line per request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        incoming = _header(scope, b"x-request-id")
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


class BodySizeLimitMiddleware:
    """Rejects request bodies larger than the upload limit (declared or streamed)."""

    def __init__(self, app):
        self.app = app
        self._max_bytes = Config.File.MAX_FILE_SIZE() + BODY_OVERHEAD_BYTES

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        declared = _header(scope, b"content-length")
        if declared.isdigit() and int(declared) > self._max_bytes:
            return await _send_json(send, 413, {"detail": "Request body too large"})

        received = {"bytes": 0}

        async def limited_receive():
            message = await receive()
            if message["type"] == "http.request":
                received["bytes"] += len(message.get("body", b""))
                if received["bytes"] > self._max_bytes:
                    raise ValueError("Request body too large")
            return message

        await self.app(scope, limited_receive, send)


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
                return await _send_json(
                    send,
                    429,
                    {"detail": "Too many requests"},
                    [(b"retry-after", str(retry_after).encode())],
                )
        await self.app(scope, receive, send)


class AdminAuditMiddleware:
    """
    Records every admin write (POST/PATCH/DELETE under the admin API) and every
    sign-in attempt in the append-only audit log, after the response is sent.

    The actor is the principal ``require_admin`` stored on the request state;
    JSON bodies up to ``AUDIT_MAX_BODY_BYTES`` are kept (secrets are redacted by
    the audit service), anything larger or non-JSON is summarised.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope["method"] not in UNSAFE_METHODS
            or not scope["path"].startswith(ADMIN_COOKIE_PATH + "/")
        ):
            return await self.app(scope, receive, send)
        request_body = bytearray()
        response_body = bytearray()
        response = {"status": 500, "content_type": ""}

        async def capturing_receive():
            message = await receive()
            if message["type"] == "http.request" and len(request_body) <= AUDIT_MAX_BODY_BYTES:
                request_body.extend(message.get("body", b""))
            return message

        async def capturing_send(message):
            if message["type"] == "http.response.start":
                response["status"] = message["status"]
                headers = dict(message.get("headers", []))
                response["content_type"] = headers.get(b"content-type", b"").decode("latin-1")
            elif message["type"] == "http.response.body" and len(response_body) <= AUDIT_MAX_BODY_BYTES:
                response_body.extend(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, capturing_receive, capturing_send)
        finally:
            await self._record(scope, request_body, response_body, response)

    @staticmethod
    def _decode(body: bytes, content_type: str) -> Any:
        """A JSON body as data; anything else as a short description."""
        if not body:
            return None
        if "json" in content_type and len(body) <= AUDIT_MAX_BODY_BYTES:
            try:
                return json.loads(body)
            except ValueError:
                logger.warning("Audited body is not valid JSON (%d bytes)", len(body))
        return {"omitted": content_type or "unknown", "bytes": len(body)}

    async def _record(self, scope, request_body: bytes, response_body: bytes, response: dict) -> None:
        """Write the entry; a failure is logged, never raised (the change already happened)."""
        container = getattr(scope["app"].state, "container", None)
        if container is None:
            return
        principal = scope.get("state", {}).get("admin")
        request_data = self._decode(bytes(request_body), _header(scope, b"content-type"))
        actor_email = principal.email if principal else None
        if actor_email is None and scope["path"].endswith(LOGIN_PATH_SUFFIX) and isinstance(request_data, dict):
            actor_email = str(request_data.get("email", ""))[:255] or None
        client = scope.get("client")
        try:
            await container.audit.record(
                AuditRecord(
                    method=scope["method"],
                    path=scope["path"],
                    status_code=response["status"],
                    actor_id=principal.id if principal else None,
                    actor_email=actor_email,
                    actor_role=principal.role if principal else None,
                    request_id=request_id_var.get(None),
                    client_ip=client[0] if client else None,
                    request_body=request_data,
                    response_body=self._decode(bytes(response_body), response["content_type"]),
                )
            )
        except Exception:
            logger.exception("Could not write the audit entry for %s %s", scope["method"], scope["path"])
