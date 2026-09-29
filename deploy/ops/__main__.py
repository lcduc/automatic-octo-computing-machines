"""
Command line: ``python -m deploy.ops <command>`` (``chatbot <command>`` on a client box).

    install [--answers FILE] [--tag TAG] [--registry REG] [--skip-deploy]
    preflight [--after-deploy]
    deploy TAG
    rollback [TAG]
    backup [--label LABEL]
    backups
    restore [NAME]
    rotate-secrets [--include-visitor-cookie]
"""

# Standard library imports
import argparse
import logging
import os
import sys
from pathlib import Path
from typing import List, Optional

# Local imports
from .answers import AnswersError, AnswersFile
from .backup import BackupError
from .backup_target import BackupTargetError
from .check_result import report
from .context import OpsContext
from .deployer import DeployError
from .host_bundle import HostIntegrationBundle
from .installer import InstallError, Installer
from .operator_alert import OperatorAlert
from .rotation import SecretRotator
from .runner import CommandError
from .secret_generator import SecretGenerator

logger = logging.getLogger(__name__)

DEFAULT_INSTALL_DIR = "/opt/chatbot"
DEFAULT_REGISTRY = "ghcr.io/lcduc"
#: Templates live next to the package in a checkout, or under OPS_TEMPLATES_DIR in the ops image.
CHECKOUT_ROOT = Path(__file__).resolve().parents[2]
EXIT_FAILURE = 1


class OpsCli:
    """Parses arguments and dispatches to the command objects."""

    def __init__(self, context: OpsContext):
        """
        Args:
            context: The install directory being operated on.
        """
        self._context = context

    def install(self, args: argparse.Namespace) -> None:
        """Install or reconfigure this box."""
        answers = AnswersFile.load(Path(args.answers)) if args.answers else None
        Installer(self._context).install(answers, args.tag, args.registry, args.skip_deploy)

    def preflight(self, args: argparse.Namespace) -> None:
        """Run the checks; exit non-zero when a fatal one fails."""
        checks = self._context.security_check().run() if args.after_deploy else self._context.preflight().run()
        if not report(checks, self._context.out):
            raise InstallError("Preflight failed")

    def deploy(self, args: argparse.Namespace) -> None:
        """Deploy a tagged release."""
        self._context.deployer().deploy(args.tag)

    def rollback(self, args: argparse.Namespace) -> None:
        """Redeploy the previous (or a given) release."""
        self._context.deployer().rollback(args.tag)

    def backup(self, args: argparse.Namespace) -> None:
        """Back up now; a failure is also sent to the alert channel (nightly runs are unattended)."""
        try:
            manager = self._require_backups()
            name = manager.create(args.label).name
        except (BackupError, BackupTargetError, CommandError) as exc:
            OperatorAlert(self._context.compose).send("Backup failed", str(exc))
            raise
        self._context.out(f"Backup {name} shipped.")

    def backups(self, args: argparse.Namespace) -> None:
        """List the backups on the target, newest first."""
        for name in self._require_backups().list_remote():
            self._context.out(name)

    def restore(self, args: argparse.Namespace) -> None:
        """Restore a backup (the newest by default) and report the time it took."""
        seconds = self._require_backups().restore(args.name)
        self._context.out(f"Restore finished in {seconds:.0f}s (record this as the RTO).")

    def rotate_secrets(self, args: argparse.Namespace) -> None:
        """Rotate the generated secrets on the running stack (and, on request, the host signing key)."""
        if args.host_keys:
            bundle = HostIntegrationBundle(self._context.layout, self._context.runner, self._context.templates_dir)
            path = bundle.write(self._context.env(), bundle.ensure_keys(rotate=True))
            self._context.out(f"New host signing key in {path}: the host must switch to it before tokens verify again.")
        rotated = SecretRotator(self._context.layout, self._context.compose, SecretGenerator(), self._context.out).rotate(
            args.include_visitor_cookie
        )
        self._context.out(f"Rotated: {', '.join(rotated)}")

    def _require_backups(self):
        """
        Raises:
            BackupError: No backup target is configured.
        """
        manager = self._context.backup_manager()
        if manager is None:
            raise BackupError("No backup target configured; rerun `chatbot install`")
        return manager


def _parser() -> argparse.ArgumentParser:
    """Command-line interface definition."""
    parser = argparse.ArgumentParser(prog="chatbot", description="Install and operate the chatbot on this box")
    parser.add_argument("--dir", default=os.getenv("OPS_DIR", DEFAULT_INSTALL_DIR), help="Install directory")
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("install", help="Install or reconfigure this box")
    install.add_argument("--answers", help="TOML answers file (see deploy/answers.example.toml)")
    install.add_argument("--tag", default=os.getenv("OPS_TAG", "dev"), help="Release tag to deploy")
    install.add_argument("--registry", default=os.getenv("OPS_REGISTRY", DEFAULT_REGISTRY), help="Image registry prefix")
    install.add_argument("--skip-deploy", action="store_true", help="Only write settings and secrets")
    preflight = commands.add_parser("preflight", help="Check this box can run the stack")
    preflight.add_argument("--after-deploy", action="store_true", help="Run the security self-check on the running stack")
    deploy = commands.add_parser("deploy", help="Deploy a tagged release")
    deploy.add_argument("tag")
    rollback = commands.add_parser("rollback", help="Redeploy the previous release")
    rollback.add_argument("tag", nargs="?")
    backup = commands.add_parser("backup", help="Back up the database and uploads off-server now")
    backup.add_argument("--label", default="manual")
    commands.add_parser("backups", help="List off-server backups")
    restore = commands.add_parser("restore", help="Restore a backup (default: the newest)")
    restore.add_argument("name", nargs="?")
    rotate = commands.add_parser("rotate-secrets", help="Replace the generated secrets")
    rotate.add_argument("--include-visitor-cookie", action="store_true",
                        help="Also rotate the visitor cookie secret (anonymous visitors lose their history)")
    rotate.add_argument("--host-keys", action="store_true",
                        help="Also replace the host signing key pair and write a new hand-over bundle")
    return parser


class _ConsoleFormatter(logging.Formatter):
    """One line per record on the terminal; tracebacks go to the log file only."""

    def format(self, record: logging.LogRecord) -> str:
        return f"{record.levelname.lower()}: {record.getMessage()}"


def _configure_logging(install_dir: Path) -> None:
    """Warnings on the terminal, everything (with tracebacks) in ``<dir>/logs/ops.log``."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(os.getenv("OPS_LOG_LEVEL", "WARNING"))
    console.setFormatter(_ConsoleFormatter())
    root.addHandler(console)
    log_dir = install_dir / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_dir / "ops.log", encoding="utf-8")
    except OSError:
        root.warning("Cannot write %s; logging to the terminal only", log_dir)
        return
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point; returns the process exit status."""
    args = _parser().parse_args(argv)
    _configure_logging(Path(args.dir))
    templates = Path(os.getenv("OPS_TEMPLATES_DIR", str(CHECKOUT_ROOT)))
    cli = OpsCli(OpsContext(Path(args.dir), templates))
    handler = getattr(cli, args.command.replace("-", "_"))
    try:
        handler(args)
    except (AnswersError, BackupError, BackupTargetError, CommandError, DeployError, InstallError) as exc:
        logger.exception("%s failed", args.command)
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_FAILURE
    return 0


if __name__ == "__main__":
    sys.exit(main())
