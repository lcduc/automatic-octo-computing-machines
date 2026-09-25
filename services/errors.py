"""
Exceptions raised by services and mapped to HTTP status codes by the API layer.
"""


class ServiceError(Exception):
    """Base class; ``str(error)`` is safe to show to the caller."""


class NotFoundError(ServiceError):
    """The referenced entity does not exist (HTTP 404)."""


class ConflictError(ServiceError):
    """The request conflicts with existing state (HTTP 409)."""


class InvalidRequestError(ServiceError):
    """The request is well-formed but not acceptable (HTTP 400)."""


class PermissionDeniedError(ServiceError):
    """The caller is authenticated but not allowed to do this (HTTP 403)."""


class RateLimitedError(ServiceError):
    """The caller exceeded a request or token quota (HTTP 429)."""

    def __init__(self, message: str, retry_after_seconds: int):
        """
        Args:
            message: User-facing explanation.
            retry_after_seconds: Value for the ``Retry-After`` header.
        """
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class ServiceUnavailableError(ServiceError):
    """A dependency is down or the server is saturated (HTTP 503)."""
