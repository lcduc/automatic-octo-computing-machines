"""
Per-request context (request id) propagated to every log record via ``contextvars``.
"""

# Standard library imports
from contextvars import ContextVar
from typing import Optional

#: Id of the HTTP request currently being handled in this task, if any.
request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


def current_request_id() -> Optional[str]:
    """The request id bound to the running task, or ``None`` outside a request."""
    return request_id_var.get()
