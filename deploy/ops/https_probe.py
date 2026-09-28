"""
HTTPS requests to this box's public domains without leaving the box.

Connects to ``127.0.0.1:443`` but presents the real domain as SNI and Host,
so Caddy's certificate for that domain is fully verified while clouds without
hairpin NAT still work.
"""

# Standard library imports
import http.client
import logging
import socket
import ssl
import time
from dataclasses import dataclass
from typing import Callable, Dict

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_SECONDS = 10
#: A fresh install may still be obtaining its certificate; retry for about this long.
CERTIFICATE_WAIT_SECONDS = 120
RETRY_PAUSE_SECONDS = 5


@dataclass(frozen=True)
class ProbeResponse:
    """Status and lower-cased headers of one response."""

    status: int
    headers: Dict[str, str]


class ProbeError(RuntimeError):
    """The domain could not be reached over verified TLS."""


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS to a fixed address, verifying the certificate of ``host``."""

    def __init__(self, host: str, address: str, context: ssl.SSLContext, timeout: float):
        super().__init__(host, 443, timeout=timeout, context=context)
        self._address = address
        self._verified_context = context

    def connect(self) -> None:
        """Open the TCP connection to the pinned address, then TLS with SNI = host."""
        raw = socket.create_connection((self._address, self.port), self.timeout)
        self.sock = self._verified_context.wrap_socket(raw, server_hostname=self.host)


class HttpsProbe:
    """GETs ``https://<domain><path>`` through the local Caddy."""

    def __init__(self, address: str = "127.0.0.1", sleep: Callable[[float], None] = time.sleep,
                 wait_seconds: int = CERTIFICATE_WAIT_SECONDS):
        """
        Args:
            address: Where Caddy listens (this box).
            sleep: Pause between retries (injectable for tests).
            wait_seconds: How long to keep retrying TLS failures.
        """
        self._address = address
        self._sleep = sleep
        self._wait_seconds = wait_seconds
        self._context = ssl.create_default_context()

    def get(self, domain: str, path: str) -> ProbeResponse:
        """
        Raises:
            ProbeError: Still unreachable (or an invalid certificate) after retrying.
        """
        deadline = time.monotonic() + self._wait_seconds
        while True:
            connection = _PinnedHTTPSConnection(domain, self._address, self._context, PROBE_TIMEOUT_SECONDS)
            try:
                connection.request("GET", path, headers={"User-Agent": "chatbot-preflight"})
                response = connection.getresponse()
                response.read()
                return ProbeResponse(response.status, {key.lower(): value for key, value in response.getheaders()})
            except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
                if time.monotonic() >= deadline:
                    raise ProbeError(f"https://{domain}{path}: {exc}") from exc
                logger.info("https://%s not ready yet (%s); retrying", domain, type(exc).__name__)
                self._sleep(RETRY_PAUSE_SECONDS)
            finally:
                connection.close()
