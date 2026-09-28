"""
Settings for outgoing notifications: operator alerts and e-mail (SMTP).

The installer writes these from its answers; everything is optional so a
development run without any channel still starts.
"""

# Local imports
from .env import env_int, env_str

#: Channels an operator alert can be sent through.
ALERT_CHANNELS = ("telegram", "slack", "smtp")
#: How an SMTP connection is secured.
SMTP_SECURITY_MODES = ("starttls", "ssl", "none")


class AlertConfig:
    """Where operator alerts (service down, spend, disk, failed jobs) are sent."""

    @staticmethod
    def ALERT_CHANNEL() -> str:
        """``telegram``, ``slack`` or ``smtp``; empty disables alerts."""
        return env_str("ALERT_CHANNEL", "").strip().lower()

    @staticmethod
    def ALERT_TELEGRAM_BOT_TOKEN() -> str:
        """Bot token from @BotFather (``telegram`` channel)."""
        return env_str("ALERT_TELEGRAM_BOT_TOKEN", "")

    @staticmethod
    def ALERT_TELEGRAM_CHAT_ID() -> str:
        """Chat or group the bot posts to (``telegram`` channel)."""
        return env_str("ALERT_TELEGRAM_CHAT_ID", "")

    @staticmethod
    def ALERT_SLACK_WEBHOOK_URL() -> str:
        """Incoming-webhook URL (``slack`` channel)."""
        return env_str("ALERT_SLACK_WEBHOOK_URL", "")

    @staticmethod
    def ALERT_EMAIL_TO() -> str:
        """Comma-separated recipients (``smtp`` channel)."""
        return env_str("ALERT_EMAIL_TO", "")

    @staticmethod
    def ALERT_DEPLOYMENT_NAME() -> str:
        """Label prefixed to every alert so several client boxes can share one channel."""
        return env_str("ALERT_DEPLOYMENT_NAME", "") or env_str("PUBLIC_DOMAIN_CHAT", "chatbot")


class SmtpConfig:
    """Outgoing mail server, shared by e-mail alerts and ticket replies."""

    @staticmethod
    def SMTP_HOST() -> str:
        """Mail server host; empty disables e-mail."""
        return env_str("SMTP_HOST", "")

    @staticmethod
    def SMTP_PORT() -> int:
        """Mail server port (587 for STARTTLS, 465 for SSL)."""
        return env_int("SMTP_PORT", 587)

    @staticmethod
    def SMTP_USERNAME() -> str:
        """Login name; empty sends without authentication."""
        return env_str("SMTP_USERNAME", "")

    @staticmethod
    def SMTP_PASSWORD() -> str:
        """Login password."""
        return env_str("SMTP_PASSWORD", "")

    @staticmethod
    def SMTP_FROM() -> str:
        """Sender address."""
        return env_str("SMTP_FROM", "")

    @staticmethod
    def SMTP_SECURITY() -> str:
        """``starttls`` (default), ``ssl`` or ``none``."""
        return env_str("SMTP_SECURITY", "starttls").strip().lower()

    @staticmethod
    def SMTP_TIMEOUT_SECONDS() -> int:
        """Connection and command timeout."""
        return env_int("SMTP_TIMEOUT_SECONDS", 15)
