"""
App-wide HTTP middleware, written as plain ASGI so streaming responses and
``contextvars`` (the request id used by logging) behave correctly.

Only ``main.py`` imports this package. It registers the middleware in this order
(outermost first): CORS, request context, security headers, body size limit,
per-IP rate limit, admin audit.
"""

from .admin_audit_middleware import AdminAuditMiddleware
from .body_size_limit_middleware import BodySizeLimitMiddleware
from .ip_rate_limit_middleware import IpRateLimitMiddleware
from .request_context_middleware import RequestContextMiddleware
from .security_headers_middleware import SecurityHeadersMiddleware

__all__ = [
    "AdminAuditMiddleware",
    "BodySizeLimitMiddleware",
    "IpRateLimitMiddleware",
    "RequestContextMiddleware",
    "SecurityHeadersMiddleware",
]
