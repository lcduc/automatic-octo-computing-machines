"""
Where everything lives in an install directory (``/opt/chatbot`` on a client box).
"""

# Standard library imports
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

#: Files and folders copied from the ops image (or a checkout) into the install directory.
TEMPLATE_FILES = ("docker-compose.yml", "deploy/Caddyfile", "deploy/postgres/10-app-role.sh")
#: Hand-over file for the client's DBA (read-only role, views, row-level security).
BUSINESS_DB_GRANTS_TEMPLATE = "deploy/business_db/reader_grants.sql"
#: Name of the owner role's password file under ``secrets/``.
OWNER_PASSWORD_FILE = "postgres_owner_password"
#: Compose project name (prefix of container, network and volume names).
COMPOSE_PROJECT = "chatbot"


@dataclass(frozen=True)
class InstallLayout:
    """Paths inside one install directory."""

    root: Path

    @property
    def env_file(self) -> Path:
        """App configuration read by compose and the backend containers (0600)."""
        return self.root / ".env"

    @property
    def ops_env_file(self) -> Path:
        """Settings only the ops CLI reads, e.g. backup credentials (0600)."""
        return self.root / "ops.env"

    @property
    def secrets_dir(self) -> Path:
        """File-based Docker secrets (directory 0700)."""
        return self.root / "secrets"

    @property
    def owner_password_file(self) -> Path:
        """PostgreSQL owner role's password (used by migrations and backups)."""
        return self.secrets_dir / OWNER_PASSWORD_FILE

    @property
    def compose_file(self) -> Path:
        """The production compose file."""
        return self.root / "docker-compose.yml"

    @property
    def history_file(self) -> Path:
        """Deployed image tags, oldest first, one per line."""
        return self.root / ".deploy_history"

    @property
    def backups_dir(self) -> Path:
        """Local staging area for backups before they are shipped off-server."""
        return self.root / "backups"

    @property
    def handover_dir(self) -> Path:
        """Files to hand to the client (host integration bundle, DB grants)."""
        return self.root / "handover"

    @property
    def uploads_dir(self) -> Path:
        """Original uploaded documents (mounted into the backend containers)."""
        return self.root / "data" / "uploads"

    def ensure_dirs(self) -> None:
        """Create the directories an install needs, with private permissions where it matters."""
        for directory in (self.root, self.backups_dir, self.handover_dir, self.uploads_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.secrets_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.secrets_dir, 0o700)
        os.chmod(self.handover_dir, 0o700)
        os.chmod(self.backups_dir, 0o700)


def copy_templates(templates_dir: Path, root: Path) -> None:
    """
    Copy the release's compose file and deploy assets into an install directory.

    Skipped when installing into the checkout itself (development).
    """
    source_root = templates_dir.resolve()
    target_root = root.resolve()
    if source_root == target_root:
        return
    for relative in TEMPLATE_FILES:
        target = target_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_root / relative, target)
