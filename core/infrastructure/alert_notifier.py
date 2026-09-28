"""
Operator alerts: one short message to the deployment's configured channel.

Telegram (Bot API ``sendMessage``), a Slack incoming webhook, or e-mail. Used
by the monitoring jobs and by ``scripts.manage test-alert`` (run by the
installer's preflight to prove the channel works before go-live).
"""

# Standard library imports
import logging
from typing import Callable, List, Optional

# Third-party imports
import httpx

# Local imports
from config.notification_settings import ALERT_CHANNELS, AlertConfig
from .smtp_mailer import MailDeliveryError, SmtpMailer

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"
#: Seconds allowed for one alert HTTP call.
ALERT_HTTP_TIMEOUT_SECONDS = 10.0
#: Telegram rejects messages longer than this.
TELEGRAM_MAX_MESSAGE_LENGTH = 4096

HttpClientFactory = Callable[[], httpx.AsyncClient]


class AlertDeliveryError(RuntimeError):
    """The alert could not be delivered to its channel."""


class AlertNotifier:
    """Sends alerts to a single channel; :attr:`enabled` is false when none is configured."""

    def __init__(
        self,
        channel: str,
        deployment_name: str,
        telegram_bot_token: str = "",
        telegram_chat_id: str = "",
        slack_webhook_url: str = "",
        email_recipients: Optional[List[str]] = None,
        mailer: Optional[SmtpMailer] = None,
        http_client_factory: Optional[HttpClientFactory] = None,
    ):
        """
        Args:
            channel: ``telegram``, ``slack``, ``smtp`` or empty (disabled).
            deployment_name: Prefix identifying this deployment in every alert.
            telegram_bot_token: Bot token (``telegram``).
            telegram_chat_id: Target chat (``telegram``).
            slack_webhook_url: Incoming webhook (``slack``).
            email_recipients: Recipients (``smtp``).
            mailer: Mail sender (``smtp``).
            http_client_factory: Builds the HTTP client (tests pass a mock transport).

        Raises:
            ValueError: Unknown channel.
        """
        if channel and channel not in ALERT_CHANNELS:
            raise ValueError(f"ALERT_CHANNEL must be one of {', '.join(ALERT_CHANNELS)}")
        self._channel = channel
        self._deployment_name = deployment_name
        self._telegram_bot_token = telegram_bot_token
        self._telegram_chat_id = telegram_chat_id
        self._slack_webhook_url = slack_webhook_url
        self._email_recipients = email_recipients or []
        self._mailer = mailer
        self._http_client_factory = http_client_factory or (
            lambda: httpx.AsyncClient(timeout=ALERT_HTTP_TIMEOUT_SECONDS)
        )

    @classmethod
    def from_config(cls) -> "AlertNotifier":
        """The notifier described by the ``ALERT_*`` and ``SMTP_*`` settings."""
        recipients = [item.strip() for item in AlertConfig.ALERT_EMAIL_TO().split(",") if item.strip()]
        return cls(
            AlertConfig.ALERT_CHANNEL(),
            AlertConfig.ALERT_DEPLOYMENT_NAME(),
            AlertConfig.ALERT_TELEGRAM_BOT_TOKEN(),
            AlertConfig.ALERT_TELEGRAM_CHAT_ID(),
            AlertConfig.ALERT_SLACK_WEBHOOK_URL(),
            recipients,
            SmtpMailer.from_config(),
        )

    @property
    def enabled(self) -> bool:
        """True when a channel is configured."""
        return bool(self._channel)

    @property
    def channel(self) -> str:
        """The configured channel name (empty when disabled)."""
        return self._channel

    async def send(self, subject: str, body: str) -> None:
        """
        Deliver one alert; a disabled notifier only logs it.

        Raises:
            AlertDeliveryError: The channel is misconfigured or refused the message.
        """
        title = f"[{self._deployment_name}] {subject}"
        if not self.enabled:
            logger.warning("Alert not sent (no ALERT_CHANNEL configured): %s", title)
            return
        logger.info("Sending %s alert: %s", self._channel, title)
        if self._channel == "telegram":
            await self._send_telegram(title, body)
        elif self._channel == "slack":
            await self._send_slack(title, body)
        else:
            await self._send_email(title, body)

    async def _post_json(self, url: str, payload: dict) -> None:
        """POST a JSON body and require a 2xx answer."""
        try:
            async with self._http_client_factory() as client:
                response = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            logger.exception("Alert HTTP call failed")
            raise AlertDeliveryError(f"Alert channel unreachable: {type(exc).__name__}") from exc
        if response.status_code >= 300:
            logger.error("Alert channel answered HTTP %s", response.status_code)
            raise AlertDeliveryError(f"Alert channel answered HTTP {response.status_code}")

    async def _send_telegram(self, title: str, body: str) -> None:
        """Post through the Telegram Bot API."""
        if not self._telegram_bot_token or not self._telegram_chat_id:
            raise AlertDeliveryError("ALERT_TELEGRAM_BOT_TOKEN and ALERT_TELEGRAM_CHAT_ID are required")
        text = f"{title}\n\n{body}"[:TELEGRAM_MAX_MESSAGE_LENGTH]
        await self._post_json(
            TELEGRAM_API_URL.format(token=self._telegram_bot_token),
            {"chat_id": self._telegram_chat_id, "text": text, "disable_web_page_preview": True},
        )

    async def _send_slack(self, title: str, body: str) -> None:
        """Post to a Slack incoming webhook."""
        if not self._slack_webhook_url:
            raise AlertDeliveryError("ALERT_SLACK_WEBHOOK_URL is required")
        await self._post_json(self._slack_webhook_url, {"text": f"*{title}*\n{body}"})

    async def _send_email(self, title: str, body: str) -> None:
        """Send through SMTP."""
        if self._mailer is None or not self._email_recipients:
            raise AlertDeliveryError("SMTP_HOST, SMTP_FROM and ALERT_EMAIL_TO are required")
        try:
            await self._mailer.send_async(self._email_recipients, title, body)
        except MailDeliveryError as exc:
            raise AlertDeliveryError(str(exc)) from exc
