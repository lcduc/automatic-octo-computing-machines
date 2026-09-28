"""
The installer's answers: what varies per client box, validated before anything is written.

Everything else (every secret, every internal address) is generated or fixed.
Answers come from a TOML file (``--answers client.toml``, repeatable installs)
or from interactive prompts; see ``deploy/answers.example.toml``.
"""

# Standard library imports
import re
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple
from urllib.parse import urlsplit

# Local imports
from .backup_target import BackupTarget, BackupTargetError
from .env_file import EnvFile

DOMAIN_PATTERN = re.compile(r"^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
#: Top-level keys of the answers file.
TOP_LEVEL_ANSWERS = ("chat_domain", "admin_domain", "host_origin", "admin_email", "openai_api_key")
#: Tables of the answers file (``env`` passes extra settings straight into .env).
ANSWER_SECTIONS = ("backup", "alert", "host_auth", "env")
#: Hosts a development/staging host page may use over plain HTTP.
LOCAL_HOSTS = ("localhost", "127.0.0.1")
ALERT_CHANNELS = ("telegram", "slack", "smtp")
HOST_AUTH_MODES = ("rs256", "hs256", "none")
DEFAULT_HOST_TIERS = "user,premium"
DEFAULT_BACKUP_KEEP_DAYS = 30


class AnswersError(ValueError):
    """One or more answers are invalid; the message lists every problem."""


@dataclass(frozen=True)
class BackupAnswers:
    """Where nightly and pre-migration backups are shipped."""

    target: str
    s3_endpoint: str = ""
    s3_region: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    sftp_password: str = ""
    #: Private key for sftp, kept under the install directory's secrets/.
    sftp_key_file: str = ""
    keep_days: int = DEFAULT_BACKUP_KEEP_DAYS


@dataclass(frozen=True)
class AlertAnswers:
    """The operator alert channel and its credentials."""

    channel: str
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    slack_webhook_url: str = ""
    email_to: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_security: str = "starttls"


@dataclass(frozen=True)
class HostAuthAnswers:
    """How the host site's signed-in users are recognised (defaults: RS256 with a generated key)."""

    mode: str = "rs256"
    #: The host's JWKS endpoint instead of the generated key (rs256).
    jwks_url: str = ""
    #: Required ``iss``/``aud``; default to the first host origin / the chat domain's URL.
    issuer: str = ""
    audience: str = ""
    #: Logged-in tiers the host may send, lowest first.
    tiers: str = DEFAULT_HOST_TIERS


@dataclass(frozen=True)
class InstallAnswers:
    """Everything a person decides for one client box."""

    chat_domain: str
    admin_domain: str
    #: One or more origins of the host website, space separated.
    host_origin: str
    admin_email: str
    openai_api_key: str
    backup: BackupAnswers
    alert: AlertAnswers
    host_auth: HostAuthAnswers = field(default_factory=HostAuthAnswers)
    extra_env: Dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def problems(self) -> List[str]:
        """Every invalid answer, as human-readable text (empty when all are valid)."""
        issues: List[str] = []
        for label, domain in (("chat_domain", self.chat_domain), ("admin_domain", self.admin_domain)):
            if not DOMAIN_PATTERN.match(domain):
                issues.append(f"{label} must be a lower-case domain name like chat.example.com")
        if self.chat_domain == self.admin_domain:
            issues.append("chat_domain and admin_domain must differ (the admin web is never embeddable)")
        issues.extend(self._origin_problems())
        if not EMAIL_PATTERN.match(self.admin_email):
            issues.append("admin_email must be an e-mail address")
        if not self.openai_api_key.strip():
            issues.append("openai_api_key is required")
        try:
            BackupTarget.from_answers(self.backup)
        except BackupTargetError as exc:
            issues.append(str(exc))
        if self.backup.keep_days < 1:
            issues.append("backup.keep_days must be at least 1")
        issues.extend(self._alert_problems())
        if self.host_auth.mode not in HOST_AUTH_MODES:
            issues.append(f"host_auth.mode must be one of {', '.join(HOST_AUTH_MODES)}")
        if self.host_auth.jwks_url and not self.host_auth.jwks_url.startswith("https://"):
            issues.append("host_auth.jwks_url must be an https:// URL")
        return issues

    def _origin_problems(self) -> List[str]:
        """Each host origin must be scheme://host[:port] with no path."""
        origins = self.host_origins
        if not origins:
            return ["host_origin is required (the website that embeds the chat, e.g. https://www.example.com)"]
        issues = []
        for origin in origins:
            parts = urlsplit(origin)
            local = parts.hostname in LOCAL_HOSTS
            if parts.scheme != "https" and not (parts.scheme == "http" and local):
                issues.append(f"host_origin {origin!r} must use https://")
            elif not parts.hostname or parts.path not in ("", "/") or parts.query or parts.fragment:
                issues.append(f"host_origin {origin!r} must be an origin like https://www.example.com (no path)")
        return issues

    def _alert_problems(self) -> List[str]:
        """The chosen alert channel has its credentials."""
        alert = self.alert
        if alert.channel not in ALERT_CHANNELS:
            return [f"alert.channel must be one of {', '.join(ALERT_CHANNELS)}"]
        required = {
            "telegram": ("telegram_bot_token", "telegram_chat_id"),
            "slack": ("slack_webhook_url",),
            "smtp": ("email_to", "smtp_host", "smtp_from"),
        }[alert.channel]
        return [f"alert.{name} is required for the {alert.channel} channel" for name in required if not getattr(alert, name)]

    @property
    def host_origins(self) -> List[str]:
        """The host origins, normalised (no trailing slash)."""
        return [item.rstrip("/") for item in re.split(r"[\s,]+", self.host_origin.strip()) if item]

    def validate(self) -> None:
        """
        Raises:
            AnswersError: Listing every invalid answer.
        """
        issues = self.problems()
        if issues:
            raise AnswersError("Invalid answers:\n  - " + "\n  - ".join(issues))

    # ------------------------------------------------------------------
    # Mapping to settings
    # ------------------------------------------------------------------

    def apply(self, env: EnvFile, ops_env: EnvFile) -> None:
        """Write the answers into the app ``.env`` and the ops-only ``ops.env``."""
        for key, value in self.env_values().items():
            env.set(key, value)
        for key, value in self.ops_env_values().items():
            ops_env.set(key, value)

    def env_values(self) -> Dict[str, str]:
        """Settings for the application containers."""
        alert = self.alert
        values = {
            "PUBLIC_DOMAIN_CHAT": self.chat_domain,
            "PUBLIC_DOMAIN_ADMIN": self.admin_domain,
            "HOST_ORIGIN": " ".join(self.host_origins),
            "LLM_PROVIDER": "openai",
            "OPENAI_API_KEY": self.openai_api_key.strip(),
            "ALERT_CHANNEL": alert.channel,
            "ALERT_DEPLOYMENT_NAME": self.chat_domain,
            "ALERT_TELEGRAM_BOT_TOKEN": alert.telegram_bot_token,
            "ALERT_TELEGRAM_CHAT_ID": alert.telegram_chat_id,
            "ALERT_SLACK_WEBHOOK_URL": alert.slack_webhook_url,
            "ALERT_EMAIL_TO": alert.email_to,
            "SMTP_HOST": alert.smtp_host,
            "SMTP_PORT": str(alert.smtp_port),
            "SMTP_USERNAME": alert.smtp_username,
            "SMTP_PASSWORD": alert.smtp_password,
            "SMTP_FROM": alert.smtp_from,
            "SMTP_SECURITY": alert.smtp_security,
            "HOST_AUTH_MODE": self.host_auth.mode,
            "HOST_JWKS_URL": self.host_auth.jwks_url,
            "HOST_JWT_ISSUER": self.host_auth.issuer or self.host_origins[0],
            "HOST_JWT_AUDIENCE": self.host_auth.audience or f"https://{self.chat_domain}",
            "HOST_TIERS": self.host_auth.tiers,
        }
        values.update(self.extra_env)
        return values

    def ops_env_values(self) -> Dict[str, str]:
        """Settings only the ops CLI reads (never mounted into an app container)."""
        backup = self.backup
        return {
            "ADMIN_EMAIL": self.admin_email,
            "BACKUP_TARGET": backup.target,
            "BACKUP_S3_ENDPOINT": backup.s3_endpoint,
            "BACKUP_S3_REGION": backup.s3_region,
            "BACKUP_S3_ACCESS_KEY_ID": backup.s3_access_key_id,
            "BACKUP_S3_SECRET_ACCESS_KEY": backup.s3_secret_access_key,
            "BACKUP_SFTP_PASSWORD": backup.sftp_password,
            "BACKUP_SFTP_KEY_FILE": backup.sftp_key_file,
            "BACKUP_KEEP_DAYS": str(backup.keep_days),
        }


class AnswersFile:
    """Loads :class:`InstallAnswers` from a TOML file."""

    @staticmethod
    def load(path: Path) -> InstallAnswers:
        """
        Raises:
            AnswersError: Unreadable file, unknown keys or missing required answers.
        """
        try:
            with open(path, "rb") as handle:
                data = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise AnswersError(f"Cannot read answers file {path}: {exc}") from exc
        return AnswersFile.from_mapping(data)

    @staticmethod
    def from_mapping(data: Mapping[str, Any]) -> InstallAnswers:
        """
        Build answers from a parsed mapping (TOML layout).

        Raises:
            AnswersError: Unknown keys, malformed numbers or missing required answers.
        """
        missing = [name for name in TOP_LEVEL_ANSWERS if not str(data.get(name, "")).strip()]
        unknown = [key for key in data if key not in TOP_LEVEL_ANSWERS + ANSWER_SECTIONS]
        backup_data, backup_unknown = _section(data.get("backup", {}), BackupAnswers)
        alert_data, alert_unknown = _section(data.get("alert", {}), AlertAnswers)
        host_auth_data, host_auth_unknown = _section(data.get("host_auth", {}), HostAuthAnswers)
        unknown += [f"backup.{key}" for key in backup_unknown] + [f"alert.{key}" for key in alert_unknown]
        unknown += [f"host_auth.{key}" for key in host_auth_unknown]
        missing += [name for name, section in (("backup.target", backup_data), ("alert.channel", alert_data))
                    if not section.get(name.split(".")[1])]
        if missing or unknown:
            details = [f"missing: {', '.join(missing)}"] if missing else []
            details += [f"unknown: {', '.join(unknown)}"] if unknown else []
            raise AnswersError("Answers file: " + "; ".join(details))
        return InstallAnswers(
            chat_domain=str(data["chat_domain"]).strip().lower(),
            admin_domain=str(data["admin_domain"]).strip().lower(),
            host_origin=str(data["host_origin"]).strip(),
            admin_email=str(data["admin_email"]).strip(),
            openai_api_key=str(data["openai_api_key"]).strip(),
            backup=BackupAnswers(**backup_data),
            alert=AlertAnswers(**alert_data),
            host_auth=HostAuthAnswers(**host_auth_data),
            extra_env={str(key): str(value) for key, value in data.get("env", {}).items()},
        )


def _section(raw: Mapping[str, Any], model: type) -> Tuple[Dict[str, Any], List[str]]:
    """Split a TOML table into the dataclass's known fields (coerced) and unknown keys."""
    known = {item.name: item.type for item in fields(model)}
    values: Dict[str, Any] = {}
    unknown: List[str] = []
    for key, value in raw.items():
        if key not in known:
            unknown.append(key)
            continue
        if known[key] in (int, "int"):
            try:
                values[key] = int(value)
            except (TypeError, ValueError) as exc:
                raise AnswersError(f"{key} must be a whole number") from exc
        else:
            values[key] = str(value).strip()
    return values, unknown
