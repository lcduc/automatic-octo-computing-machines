"""
Builds the ops collaborators for one install directory, reading its current settings.
"""

# Standard library imports
from functools import cached_property
from pathlib import Path
from typing import Callable, Dict, Optional

# Local imports
from .backup import BackupManager
from .backup_target import BackupTarget
from .compose import Compose
from .deployer import Deployer
from .env_file import EnvFile
from .https_probe import HttpsProbe
from .layout import InstallLayout
from .preflight import Preflight
from .runner import CommandRunner
from .security_check import SecuritySelfCheck

DEFAULT_BACKUP_KEEP_DAYS = 30


class OpsContext:
    """The install directory plus everything the commands need to act on it."""

    def __init__(self, root: Path, templates_dir: Path, runner: Optional[CommandRunner] = None,
                 out: Callable[[str], None] = print):
        """
        Args:
            root: Install directory (``/opt/chatbot`` on a client box).
            templates_dir: Where docker-compose.yml and deploy/ are copied from.
            runner: Command runner (tests pass a fake).
            out: Operator output.
        """
        self.layout = InstallLayout(root)
        self.templates_dir = templates_dir
        self.runner = runner or CommandRunner()
        self.out = out

    @cached_property
    def compose(self) -> Compose:
        """Compose for this install's stack."""
        return Compose(self.layout, self.runner)

    def env(self) -> Dict[str, str]:
        """Current ``.env`` values (re-read on every call)."""
        return EnvFile(self.layout.env_file).load().as_dict()

    def ops_env(self) -> Dict[str, str]:
        """Current ``ops.env`` values (re-read on every call)."""
        return EnvFile(self.layout.ops_env_file).load().as_dict()

    def backup_manager(self) -> Optional[BackupManager]:
        """
        The backup manager, or ``None`` before a target is configured.

        Raises:
            BackupTargetError: ``BACKUP_TARGET`` is set but invalid.
        """
        values = self.ops_env()
        if not values.get("BACKUP_TARGET"):
            return None
        keep = values.get("BACKUP_KEEP_DAYS", "")
        return BackupManager(self.layout, self.compose, self.runner, BackupTarget.from_env(values),
                             int(keep) if keep.isdigit() else DEFAULT_BACKUP_KEEP_DAYS)

    def deployer(self) -> Deployer:
        """Deploys and rolls back releases."""
        return Deployer(self.layout, self.compose, self.backup_manager, self.out, self.templates_dir)

    def preflight(self) -> Preflight:
        """Pre-deploy checks with the current settings."""
        return Preflight(self.layout, self.runner, self.compose, self.env(), self.ops_env(), self.backup_manager)

    def security_check(self) -> SecuritySelfCheck:
        """Post-deploy security self-check with the current settings."""
        return SecuritySelfCheck(self.layout, self.runner, self.compose, self.env(), HttpsProbe())
