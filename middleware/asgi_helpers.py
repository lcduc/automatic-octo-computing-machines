"""
Small ASGI helpers shared by the middleware classes.
"""

# Standard library imports
import json
from typing import Iterable, Tuple

#: Paths never rate limited or logged per request (health probes).
QUIET_PATH_PREFIXES = ("/health",)


def header_value(scope, name: bytes) -> str:
    """First value of a request header, decoded, or ``""``."""
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return ""


async def send_json(send, status: int, body: dict, extra_headers: Iterable[Tuple[bytes, bytes]] = ()) -> None:
    """Send a complete JSON response from inside a middleware."""
    payload = json.dumps(body).encode("utf-8")
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())]
    await send({"type": "http.response.start", "status": status, "headers": headers + list(extra_headers)})
    await send({"type": "http.response.body", "body": payload})
