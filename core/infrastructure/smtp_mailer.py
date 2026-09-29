"""
Plain-text e-mail over SMTP (stdlib ``smtplib``), for alerts and ticket replies.
"""

# Standard library imports
import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Optional, Sequence

# Local imports
from config.notification_settings import SMTP_SECURITY_MODES, SmtpConfig

logger = logging.getLogger(__name__)


class MailDeliveryError(RuntimeError):
    """The mail server refused or could not be reached."""


class SmtpMailer:
    """Sends one message per call; a new connection each time (mail volume is tiny)."""

    def __init__(
        self,
        host: str,
        port: int,
        sender: str,
        username: str = "",
        password: str = "",
        security: str = "starttls",
        timeout_seconds: int = 15,
    ):
        """
        Args:
            host: Mail server host.
            port: Mail server port.
            sender: ``From`` address.
            username: Login name; empty skips authentication.
            password: Login password.
            security: ``starttls``, ``ssl`` or ``none``.
            timeout_seconds: Socket timeout.

        Raises:
            ValueError: Unknown ``security`` mode.
        """
        if security not in SMTP_SECURITY_MODES:
            raise ValueError(f"SMTP security must be one of {', '.join(SMTP_SECURITY_MODES)}")
        self._host = host
        self._port = port
        self._sender = sender
        self._username = username
        self._password = password
        self._security = security
        self._timeout = timeout_seconds

    @classmethod
    def from_config(cls) -> Optional["SmtpMailer"]:
        """The configured mailer, or ``None`` when ``SMTP_HOST``/``SMTP_FROM`` are unset."""
        if not SmtpConfig.SMTP_HOST() or not SmtpConfig.SMTP_FROM():
            return None
        return cls(
            SmtpConfig.SMTP_HOST(),
            SmtpConfig.SMTP_PORT(),
            SmtpConfig.SMTP_FROM(),
            SmtpConfig.SMTP_USERNAME(),
            SmtpConfig.SMTP_PASSWORD(),
            SmtpConfig.SMTP_SECURITY(),
            SmtpConfig.SMTP_TIMEOUT_SECONDS(),
        )

    def _connect(self) -> smtplib.SMTP:
        """Open an authenticated connection with the configured security."""
        context = ssl.create_default_context()
        if self._security == "ssl":
            client: smtplib.SMTP = smtplib.SMTP_SSL(self._host, self._port, timeout=self._timeout, context=context)
        else:
            client = smtplib.SMTP(self._host, self._port, timeout=self._timeout)
            if self._security == "starttls":
                client.starttls(context=context)
        if self._username:
            client.login(self._username, self._password)
        return client

    def send(self, recipients: Sequence[str], subject: str, body: str) -> None:
        """
        Deliver a plain-text message (blocking).

        Raises:
            MailDeliveryError: Connection, authentication or delivery failed.
        """
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = ", ".join(recipients)
        message["Subject"] = subject
        message.set_content(body)
        logger.info("Sending e-mail '%s' to %d recipient(s)", subject, len(recipients))
        try:
            with self._connect() as client:
                client.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            logger.exception("E-mail delivery via %s:%s failed", self._host, self._port)
            raise MailDeliveryError(f"E-mail delivery failed: {type(exc).__name__}") from exc

    async def send_async(self, recipients: Sequence[str], subject: str, body: str) -> None:
        """:meth:`send` off the event loop."""
        await asyncio.to_thread(self.send, recipients, subject, body)
