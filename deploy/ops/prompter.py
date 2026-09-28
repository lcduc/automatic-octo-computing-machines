"""
Interactive questions for ``chatbot install`` when no answers file is given.

On a rerun, the values already in ``.env``/``ops.env`` are offered as
defaults, and secrets can be kept by pressing Enter.
"""

# Standard library imports
import getpass
from typing import Callable, Dict, Optional

# Local imports
from .answers import (
    ALERT_CHANNELS,
    DEFAULT_BACKUP_KEEP_DAYS,
    DOMAIN_PATTERN,
    EMAIL_PATTERN,
    AlertAnswers,
    AnswersError,
    BackupAnswers,
    InstallAnswers,
)

Ask = Callable[[str], str]
Validator = Callable[[str], Optional[str]]


def _domain_error(value: str) -> Optional[str]:
    """Why ``value`` is not a domain name, or ``None``."""
    return None if DOMAIN_PATTERN.match(value) else "enter a lower-case domain like chat.example.com"


def _email_error(value: str) -> Optional[str]:
    """Why ``value`` is not an e-mail address, or ``None``."""
    return None if EMAIL_PATTERN.match(value) else "enter an e-mail address"


def _required(value: str) -> Optional[str]:
    """Rejects an empty answer."""
    return None if value else "this answer is required"


class InteractivePrompter:
    """Asks the installer's questions on the terminal."""

    def __init__(self, ask: Ask = input, ask_secret: Ask = getpass.getpass, out: Callable[[str], None] = print):
        """
        Args:
            ask: Reads one visible answer.
            ask_secret: Reads one hidden answer (passwords, keys).
            out: Writes guidance to the operator.
        """
        self._ask = ask
        self._ask_secret = ask_secret
        self._out = out

    def _question(self, label: str, default: Optional[str] = None, validator: Validator = _required,
                  secret: bool = False) -> str:
        """Ask until the answer is valid; an empty answer takes ``default``."""
        while True:
            if secret:
                hint = " [press Enter to keep the current value]" if default else ""
                answer = self._ask_secret(f"{label}{hint}: ").strip() or (default or "")
            else:
                hint = f" [{default}]" if default else ""
                answer = self._ask(f"{label}{hint}: ").strip() or (default or "")
            problem = validator(answer)
            if problem is None:
                return answer
            self._out(f"  -> {problem}")

    def collect(self, current: Dict[str, str]) -> InstallAnswers:
        """
        Ask every question, offering ``current`` settings as defaults.

        Raises:
            AnswersError: The combined answers are still inconsistent (e.g. equal domains).
        """
        self._out("Answer six questions; everything else, including every secret, is generated.\n")
        answers = InstallAnswers(
            chat_domain=self._question("1/6 Chat domain (serves the widget)", current.get("PUBLIC_DOMAIN_CHAT"), _domain_error).lower(),
            admin_domain=self._question("2/6 Admin domain (the admin web, never embeddable)", current.get("PUBLIC_DOMAIN_ADMIN"), _domain_error).lower(),
            host_origin=self._question("3/6 Website that embeds the chat, e.g. https://www.example.com", current.get("HOST_ORIGIN")),
            admin_email=self._question("4/6 E-mail of the first admin", current.get("ADMIN_EMAIL"), _email_error),
            backup=self._backup(current),
            alert=self._alert(current),
            openai_api_key=self._question("OpenAI API key", current.get("OPENAI_API_KEY"), secret=True),
        )
        answers.validate()
        return answers

    def _backup(self, current: Dict[str, str]) -> BackupAnswers:
        """Question 5: where backups go, then the credentials that target needs."""
        target = self._question(
            "5/6 Backup target: s3://bucket/prefix, sftp://user@host/path or /mounted/path", current.get("BACKUP_TARGET")
        )
        values: Dict[str, str] = {}
        if target.startswith("s3://"):
            values["s3_endpoint"] = self._question("   S3 endpoint URL (empty for AWS)", current.get("BACKUP_S3_ENDPOINT"), lambda _: None)
            values["s3_region"] = self._question("   S3 region", current.get("BACKUP_S3_REGION"), lambda _: None)
            values["s3_access_key_id"] = self._question("   S3 access key id", current.get("BACKUP_S3_ACCESS_KEY_ID"))
            values["s3_secret_access_key"] = self._question("   S3 secret access key", current.get("BACKUP_S3_SECRET_ACCESS_KEY"), secret=True)
        elif target.startswith("sftp://"):
            values["sftp_password"] = self._question("   SFTP password (empty to use a key file)", current.get("BACKUP_SFTP_PASSWORD"), lambda _: None, secret=True)
            if not values["sftp_password"]:
                values["sftp_key_file"] = self._question("   SFTP private key file inside the install directory", current.get("BACKUP_SFTP_KEY_FILE"))
        keep = self._question("   Days to keep backups", current.get("BACKUP_KEEP_DAYS", str(DEFAULT_BACKUP_KEEP_DAYS)),
                              lambda value: None if value.isdigit() and int(value) > 0 else "enter a positive number")
        return BackupAnswers(target=target, keep_days=int(keep), **values)

    def _alert(self, current: Dict[str, str]) -> AlertAnswers:
        """Question 6: the alert channel, then its credentials."""
        channel = self._question(f"6/6 Alert channel ({' | '.join(ALERT_CHANNELS)})", current.get("ALERT_CHANNEL"),
                                 lambda value: None if value in ALERT_CHANNELS else f"choose one of {', '.join(ALERT_CHANNELS)}")
        if channel == "telegram":
            return AlertAnswers(
                channel,
                telegram_bot_token=self._question("   Telegram bot token", current.get("ALERT_TELEGRAM_BOT_TOKEN"), secret=True),
                telegram_chat_id=self._question("   Telegram chat id", current.get("ALERT_TELEGRAM_CHAT_ID")),
            )
        if channel == "slack":
            return AlertAnswers(channel, slack_webhook_url=self._question("   Slack webhook URL", current.get("ALERT_SLACK_WEBHOOK_URL"), secret=True))
        return AlertAnswers(
            channel,
            email_to=self._question("   Alert recipients (comma separated)", current.get("ALERT_EMAIL_TO")),
            smtp_host=self._question("   SMTP host", current.get("SMTP_HOST")),
            smtp_port=int(self._question("   SMTP port", current.get("SMTP_PORT", "587"),
                                         lambda value: None if value.isdigit() else "enter a port number")),
            smtp_security=self._question("   SMTP security (starttls | ssl | none)", current.get("SMTP_SECURITY", "starttls"),
                                         lambda value: None if value in ("starttls", "ssl", "none") else "choose starttls, ssl or none"),
            smtp_username=self._question("   SMTP username", current.get("SMTP_USERNAME"), lambda _: None),
            smtp_password=self._question("   SMTP password", current.get("SMTP_PASSWORD"), lambda _: None, secret=True),
            smtp_from=self._question("   Sender address", current.get("SMTP_FROM"), _email_error),
        )


__all__ = ["InteractivePrompter", "AnswersError"]
