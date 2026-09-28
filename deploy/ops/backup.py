"""
Backups: a PostgreSQL dump (knowledge, vectors, conversations, settings) plus
the original uploaded files, shipped off-server with rclone.

Each backup is a pair ``<stamp>-<label>.dump`` + ``<stamp>-<label>-uploads.tar.gz``.
``chatbot backup`` runs nightly from cron and before every migration.
"""

# Standard library imports
import logging
import os
import re
import shutil
import tarfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

# Local imports
from .backup_target import BackupTarget
from .compose import Compose
from .layout import InstallLayout
from .runner import CommandError, CommandRunner, merged_env

logger = logging.getLogger(__name__)

#: Owner role and database of the stack (see docker-compose.yml).
DB_OWNER = "chatbot"
DB_NAME = "chatbot"
#: Backups kept in the local staging directory (the off-server copy is the real one).
LOCAL_BACKUPS_KEPT = 3
DUMP_SUFFIX = ".dump"
UPLOADS_SUFFIX = "-uploads.tar.gz"
LABEL_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{0,40}$")
#: Services stopped during a restore so nothing writes to the database meanwhile.
WRITER_SERVICES = ("web", "api", "ingestion-worker")
PREFLIGHT_MARKER = ".chatbot-preflight"
#: Seconds the restarted services get to become healthy after a restore.
RESTART_TIMEOUT_SECONDS = 900


class BackupError(RuntimeError):
    """A backup or restore step failed."""


@dataclass(frozen=True)
class BackupSet:
    """The files of one backup."""

    name: str
    dump: Path
    uploads: Path


class BackupManager:
    """Creates, ships, prunes and restores backups for one install."""

    def __init__(
        self,
        layout: InstallLayout,
        compose: Compose,
        runner: CommandRunner,
        target: BackupTarget,
        keep_days: int,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        """
        Args:
            layout: The install directory.
            compose: Compose for the stack (``postgres`` must be running).
            runner: Runs rclone.
            target: Where backups are shipped.
            keep_days: Off-server retention.
            now: Clock (injectable for tests).
        """
        self._layout = layout
        self._compose = compose
        self._runner = runner
        self._target = target
        self._keep_days = keep_days
        self._now = now

    # ------------------------------------------------------------------
    # rclone
    # ------------------------------------------------------------------

    def _rclone(self, *args: str, timeout: int = 3600) -> str:
        """Run rclone with the target's remote defined in the environment."""
        env = merged_env(os.environ, self._target.rclone_env(self._obscure))
        return self._runner.run(["rclone", *args], env=env, timeout=timeout).stdout

    def _obscure(self, password: str) -> str:
        """rclone's reversible obscuring of a clear-text password (required for sftp ``pass``)."""
        return self._runner.run(["rclone", "obscure", "-"], input_text=password).stdout.strip()

    def check_reachable(self) -> None:
        """
        Write, list and delete a marker file on the target.

        Raises:
            CommandError: The target cannot be written.
        """
        marker = self._layout.backups_dir / PREFLIGHT_MARKER
        self._layout.backups_dir.mkdir(parents=True, exist_ok=True)
        marker.write_text(self._now().isoformat(), encoding="utf-8")
        try:
            self._rclone("copyto", str(marker), f"{self._target.remote}/{PREFLIGHT_MARKER}", timeout=120)
            self._rclone("deletefile", f"{self._target.remote}/{PREFLIGHT_MARKER}", timeout=120)
        finally:
            marker.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Backup
    # ------------------------------------------------------------------

    def create(self, label: str) -> BackupSet:
        """
        Dump the database and archive the uploads, then ship both off-server.

        Raises:
            BackupError: Invalid label, or the dump/shipping failed.
        """
        if not LABEL_PATTERN.match(label):
            raise BackupError("Backup labels are lower-case letters, digits, dots and dashes")
        stamp = self._now().strftime("%Y%m%dT%H%M%SZ")
        name = f"{stamp}-{label}"
        self._layout.backups_dir.mkdir(parents=True, exist_ok=True)
        backup = BackupSet(name, self._layout.backups_dir / f"{name}{DUMP_SUFFIX}",
                           self._layout.backups_dir / f"{name}{UPLOADS_SUFFIX}")
        started = time.monotonic()
        try:
            self._compose.exec("postgres", ["pg_dump", "-U", DB_OWNER, "-d", DB_NAME, "-Fc"], stdout_path=backup.dump)
            self._archive_uploads(backup.uploads)
            for path in (backup.dump, backup.uploads):
                self._rclone("copyto", str(path), f"{self._target.remote}/{path.name}")
        except (CommandError, OSError) as exc:
            logger.exception("Backup %s failed", name)
            raise BackupError(f"Backup {name} failed: {exc}") from exc
        logger.info("Backup %s shipped in %.0fs (%d bytes)", name, time.monotonic() - started,
                    backup.dump.stat().st_size + backup.uploads.stat().st_size)
        self._prune_local()
        self._prune_remote()
        return backup

    def _archive_uploads(self, destination: Path) -> None:
        """Tar+gzip the uploads directory (empty archive when there are none)."""
        with tarfile.open(destination, "w:gz") as archive:
            if self._layout.uploads_dir.exists():
                archive.add(self._layout.uploads_dir, arcname="uploads")

    def _prune_local(self) -> None:
        """Keep only the newest local backups; older ones exist off-server."""
        dumps = sorted(self._layout.backups_dir.glob(f"*{DUMP_SUFFIX}"))
        for dump in dumps[:-LOCAL_BACKUPS_KEPT]:
            dump.unlink(missing_ok=True)
            dump.with_name(dump.name[: -len(DUMP_SUFFIX)] + UPLOADS_SUFFIX).unlink(missing_ok=True)

    def _prune_remote(self) -> None:
        """Delete off-server backups older than the retention period."""
        try:
            self._rclone("delete", "--min-age", f"{self._keep_days}d", self._target.remote, timeout=600)
        except CommandError:
            # A failed prune must not fail the backup that just succeeded.
            logger.exception("Pruning old off-server backups failed")

    def list_remote(self) -> List[str]:
        """Names of the backups on the target, newest first."""
        output = self._rclone("lsf", "--include", f"*{DUMP_SUFFIX}", self._target.remote, timeout=120)
        names = [line[: -len(DUMP_SUFFIX)] for line in output.splitlines() if line.endswith(DUMP_SUFFIX)]
        return sorted(names, reverse=True)

    # ------------------------------------------------------------------
    # Restore
    # ------------------------------------------------------------------

    def restore(self, name: Optional[str]) -> float:
        """
        Replace the database and uploads with backup ``name`` (the newest when ``None``).

        Returns:
            Seconds the restore took (record it as the RTO).

        Raises:
            BackupError: Unknown backup, or a restore step failed.
        """
        available = self.list_remote()
        chosen = name or (available[0] if available else None)
        if chosen is None or chosen not in available:
            raise BackupError(f"Backup {name or '(latest)'} not found on {self._target.kind} target")
        started = time.monotonic()
        restore_dir = self._layout.backups_dir / "restore"
        shutil.rmtree(restore_dir, ignore_errors=True)
        restore_dir.mkdir(parents=True)
        try:
            for suffix in (DUMP_SUFFIX, UPLOADS_SUFFIX):
                self._rclone("copyto", f"{self._target.remote}/{chosen}{suffix}", str(restore_dir / f"{chosen}{suffix}"))
            self._compose.stop(WRITER_SERVICES)
            # One transaction: a failed restore leaves the current database untouched.
            self._compose.exec(
                "postgres",
                ["pg_restore", "-U", DB_OWNER, "-d", DB_NAME, "--clean", "--if-exists", "--single-transaction"],
                stdin_path=restore_dir / f"{chosen}{DUMP_SUFFIX}", timeout=7200,
            )
            self._restore_uploads(restore_dir / f"{chosen}{UPLOADS_SUFFIX}")
            self._compose.up()
            self._compose.wait_healthy(WRITER_SERVICES[:2], RESTART_TIMEOUT_SECONDS)
        except (CommandError, OSError, tarfile.TarError) as exc:
            logger.exception("Restore of %s failed", chosen)
            raise BackupError(f"Restore of {chosen} failed: {exc}") from exc
        finally:
            shutil.rmtree(restore_dir, ignore_errors=True)
        elapsed = time.monotonic() - started
        logger.info("Restored %s in %.0fs", chosen, elapsed)
        return elapsed

    def _restore_uploads(self, archive_path: Path) -> None:
        """Replace the uploads directory with the archived one."""
        uploads = self._layout.uploads_dir
        staging = uploads.with_name("uploads.restoring")
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        with tarfile.open(archive_path, "r:gz") as archive:
            archive.extractall(staging, filter="data")
        restored = staging / "uploads"
        shutil.rmtree(uploads, ignore_errors=True)
        if restored.exists():
            os.replace(restored, uploads)
        else:
            uploads.mkdir(parents=True)
        shutil.rmtree(staging, ignore_errors=True)
