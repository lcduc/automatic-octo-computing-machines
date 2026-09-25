"""
Maps service exceptions to HTTP responses so routes stay "parse -> call -> return".
"""

# Standard library imports
import logging

# Third-party imports
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Local imports
from services.errors import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitedError,
    ServiceError,
    ServiceUnavailableError,
)
from utils.request_context import current_request_id

logger = logging.getLogger(__name__)

#: HTTP status for each service error type (checked in order; subclasses first).
STATUS_BY_ERROR = (
    (NotFoundError, 404),
    (ConflictError, 409),
    (InvalidRequestError, 400),
    (PermissionDeniedError, 403),
    (RateLimitedError, 429),
    (ServiceUnavailableError, 503),
)
#: Seconds a client should wait after a 503 from a saturated server.
UNAVAILABLE_RETRY_AFTER_SECONDS = 5


async def _service_error(_request: Request, exc: ServiceError) -> JSONResponse:
    """Render a :class:`ServiceError`; its message is safe for clients."""
    status = next((code for error_type, code in STATUS_BY_ERROR if isinstance(exc, error_type)), 400)
    headers = {}
    if isinstance(exc, RateLimitedError):
        headers["Retry-After"] = str(exc.retry_after_seconds)
    elif isinstance(exc, ServiceUnavailableError):
        headers["Retry-After"] = str(UNAVAILABLE_RETRY_AFTER_SECONDS)
    return JSONResponse({"detail": str(exc)}, status_code=status, headers=headers)


async def _unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
    """Log an unhandled exception and return a generic 500 with the request id."""
    logger.exception("Unhandled error", exc_info=exc)
    return JSONResponse(
        {"detail": "Internal server error", "request_id": current_request_id()}, status_code=500
    )


def register_error_handlers(app: FastAPI) -> None:
    """Attach the handlers to ``app``."""
    app.add_exception_handler(ServiceError, _service_error)
    app.add_exception_handler(Exception, _unexpected_error)
