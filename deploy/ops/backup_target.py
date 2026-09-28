"""
Off-server backup destinations, expressed as an rclone remote.

``BACKUP_TARGET`` is one of:

* ``s3://bucket/prefix`` (any S3-compatible store; ``BACKUP_S3_*`` credentials)
* ``sftp://user@host[:port]/path`` (``BACKUP_SFTP_PASSWORD`` or a key file)
* ``/absolute/path`` (a mounted disk or network share)

rclone reads remote definitions from ``RCLONE_CONFIG_<NAME>_<OPTION>``
environment variables, so no rclone config file is ever written.
"""

# Standard library imports
from dataclasses import dataclass
from typing import Any, Callable, Dict
from urllib.parse import urlsplit

#: Name of the rclone remote defined through environment variables.
REMOTE_NAME = "BACKUP"
DEFAULT_SFTP_PORT = 22


class BackupTargetError(ValueError):
    """``BACKUP_TARGET`` or its credentials are malformed."""


@dataclass(frozen=True)
class BackupTarget:
    """A parsed destination plus the credentials rclone needs for it."""

    kind: str
    #: Bucket/prefix (s3), absolute or home-relative path (sftp), or directory (local).
    location: str
    host: str = ""
    port: int = DEFAULT_SFTP_PORT
    user: str = ""
    s3_endpoint: str = ""
    s3_region: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    sftp_password: str = ""
    sftp_key_file: str = ""

    @classmethod
    def parse(cls, target: str, **credentials: Any) -> "BackupTarget":
        """
        Args:
            target: The ``BACKUP_TARGET`` value.
            **credentials: ``s3_*`` / ``sftp_*`` fields.

        Raises:
            BackupTargetError: Unsupported scheme or missing credentials.
        """
        target = target.strip()
        if target.startswith("/"):
            return cls("local", target.rstrip("/") or "/")
        parts = urlsplit(target)
        if parts.scheme == "s3":
            location = f"{parts.netloc}{parts.path}".rstrip("/")
            if not parts.netloc:
                raise BackupTargetError("backup.target s3://bucket[/prefix] needs a bucket name")
            if not credentials.get("s3_access_key_id") or not credentials.get("s3_secret_access_key"):
                raise BackupTargetError("backup.s3_access_key_id and backup.s3_secret_access_key are required for s3://")
            return cls("s3", location, **_pick(credentials, "s3_"))
        if parts.scheme == "sftp":
            if not parts.hostname or not parts.username:
                raise BackupTargetError("backup.target sftp:// needs user@host, e.g. sftp://backup@nas.example.com/chatbot")
            if not credentials.get("sftp_password") and not credentials.get("sftp_key_file"):
                raise BackupTargetError("backup.sftp_password or backup.sftp_key_file is required for sftp://")
            return cls(
                "sftp", parts.path or ".", host=parts.hostname, port=parts.port or DEFAULT_SFTP_PORT,
                user=parts.username, **_pick(credentials, "sftp_"),
            )
        raise BackupTargetError("backup.target must be s3://bucket/prefix, sftp://user@host/path or an absolute path")

    @classmethod
    def from_answers(cls, backup: Any) -> "BackupTarget":
        """Build from :class:`deploy.ops.answers.BackupAnswers`."""
        return cls.parse(
            backup.target,
            s3_endpoint=backup.s3_endpoint, s3_region=backup.s3_region,
            s3_access_key_id=backup.s3_access_key_id, s3_secret_access_key=backup.s3_secret_access_key,
            sftp_password=backup.sftp_password, sftp_key_file=getattr(backup, "sftp_key_file", ""),
        )

    @classmethod
    def from_env(cls, values: Dict[str, str]) -> "BackupTarget":
        """
        Build from ``ops.env`` values.

        Raises:
            BackupTargetError: ``BACKUP_TARGET`` is unset or invalid.
        """
        target = values.get("BACKUP_TARGET", "")
        if not target:
            raise BackupTargetError("BACKUP_TARGET is not configured; rerun `chatbot install`")
        return cls.parse(
            target,
            s3_endpoint=values.get("BACKUP_S3_ENDPOINT", ""), s3_region=values.get("BACKUP_S3_REGION", ""),
            s3_access_key_id=values.get("BACKUP_S3_ACCESS_KEY_ID", ""),
            s3_secret_access_key=values.get("BACKUP_S3_SECRET_ACCESS_KEY", ""),
            sftp_password=values.get("BACKUP_SFTP_PASSWORD", ""), sftp_key_file=values.get("BACKUP_SFTP_KEY_FILE", ""),
        )

    @property
    def remote(self) -> str:
        """What to pass to rclone as the destination directory."""
        if self.kind == "local":
            return self.location
        return f"{REMOTE_NAME}:{self.location}"

    def rclone_env(self, obscure: Callable[[str], str]) -> Dict[str, str]:
        """
        Environment variables defining the remote for rclone.

        Args:
            obscure: Turns a clear-text password into rclone's obscured form
                (``rclone obscure``), as its ``pass`` option requires.
        """
        prefix = f"RCLONE_CONFIG_{REMOTE_NAME}_"
        if self.kind == "s3":
            env = {
                f"{prefix}TYPE": "s3",
                f"{prefix}PROVIDER": "Other" if self.s3_endpoint else "AWS",
                f"{prefix}ACCESS_KEY_ID": self.s3_access_key_id,
                f"{prefix}SECRET_ACCESS_KEY": self.s3_secret_access_key,
            }
            if self.s3_endpoint:
                env[f"{prefix}ENDPOINT"] = self.s3_endpoint
            if self.s3_region:
                env[f"{prefix}REGION"] = self.s3_region
            return env
        if self.kind == "sftp":
            env = {f"{prefix}TYPE": "sftp", f"{prefix}HOST": self.host, f"{prefix}USER": self.user, f"{prefix}PORT": str(self.port)}
            if self.sftp_key_file:
                env[f"{prefix}KEY_FILE"] = self.sftp_key_file
            else:
                env[f"{prefix}PASS"] = obscure(self.sftp_password)
            return env
        return {}


def _pick(credentials: Dict[str, Any], prefix: str) -> Dict[str, str]:
    """The credentials whose names start with ``prefix``, as strings."""
    return {key: str(value) for key, value in credentials.items() if key.startswith(prefix) and value}
