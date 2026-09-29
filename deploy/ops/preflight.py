"""
``chatbot preflight``: proves a box can run the stack before anything is deployed.

Checks the GPU (through the API image, exactly as the stack will see it),
memory, disk, DNS for both domains, that the backup target accepts writes,
and that the alert channel delivers a test message (sent by the backend's own
notifier, so the check proves the code that will send real alerts). After a
deploy, :class:`~deploy.ops.security_check.SecuritySelfCheck` runs too.
"""

# Standard library imports
import logging
import shutil
import socket
from pathlib import Path
from typing import Callable, Dict, List, Optional

# Local imports
from .backup import BackupManager
from .backup_target import BackupTargetError
from .check_result import CheckResult
from .compose import Compose
from .layout import InstallLayout
from .runner import CommandError, CommandRunner

logger = logging.getLogger(__name__)

#: Defaults sized for the reference box (12 GB GPU, 16 GB RAM); overridable in ops.env for staging.
DEFAULT_MIN_FREE_VRAM_MB = 8000
DEFAULT_MIN_RAM_MB = 15000
DEFAULT_MIN_FREE_DISK_GB = 30
#: Disk usage above this share is reported (the same threshold as the disk alert).
DISK_WARN_RATIO = 0.8
MEMINFO_PATH = Path("/proc/meminfo")
GIB = 1024 ** 3


class Preflight:
    """Runs the pre-deploy checks for one install."""

    def __init__(
        self,
        layout: InstallLayout,
        runner: CommandRunner,
        compose: Compose,
        env: Dict[str, str],
        ops_env: Dict[str, str],
        backups: Callable[[], Optional[BackupManager]],
        resolve: Callable[[str], List[str]] = None,
        meminfo_path: Path = MEMINFO_PATH,
    ):
        """
        Args:
            layout: The install directory.
            runner: Runs ``docker``.
            compose: Compose for the stack.
            env: Values of ``.env``.
            ops_env: Values of ``ops.env`` (thresholds, backup target).
            backups: Builds the backup manager (raises :class:`BackupTargetError` when misconfigured).
            resolve: Domain -> addresses (injectable for tests).
            meminfo_path: Where total memory is read from.
        """
        self._layout = layout
        self._runner = runner
        self._compose = compose
        self._env = env
        self._ops_env = ops_env
        self._backups = backups
        self._resolve = resolve or _resolve
        self._meminfo_path = meminfo_path

    def _threshold(self, key: str, default: int) -> int:
        """An ``ops.env`` override of a threshold, or ``default``."""
        raw = self._ops_env.get(key, "")
        return int(raw) if raw.isdigit() else default

    def run(self) -> List[CheckResult]:
        """Every pre-deploy check, in order."""
        return [
            self.check_gpu(),
            self.check_memory(),
            *self.check_disk(),
            *self.check_dns(),
            self.check_backup_target(),
            self.check_alert(),
            *([self.check_business_db()] if self._env.get("BUSINESS_DB_URL") else []),
        ]

    def api_image(self) -> str:
        """The API image of the configured release."""
        return f"{self._env.get('REGISTRY', 'ghcr.io/lcduc')}/chatbot-api:{self._env.get('IMAGE_TAG', 'dev')}"

    def check_gpu(self) -> CheckResult:
        """A GPU is visible to containers and has enough free memory."""
        minimum = self._threshold("PREFLIGHT_MIN_FREE_VRAM_MB", DEFAULT_MIN_FREE_VRAM_MB)
        try:
            output = self._runner.run(
                ["docker", "run", "--rm", "--gpus", "all", "--entrypoint", "nvidia-smi", self.api_image(),
                 "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"],
                timeout=300,
            ).stdout
        except CommandError as exc:
            return CheckResult("gpu", False, f"no GPU visible to Docker (install the NVIDIA driver and Container Toolkit): {exc}")
        rows = [[part.strip() for part in line.split(",")] for line in output.strip().splitlines() if line.strip()]
        if not rows:
            return CheckResult("gpu", False, "nvidia-smi reported no GPU")
        name, total, free = rows[0][0], int(rows[0][1]), int(rows[0][2])
        ok = free >= minimum
        return CheckResult("gpu", ok, f"{name}, {free} MB free of {total} MB (need {minimum} MB)")

    def check_memory(self) -> CheckResult:
        """The host has enough RAM for the memory limits in the compose file."""
        minimum = self._threshold("PREFLIGHT_MIN_RAM_MB", DEFAULT_MIN_RAM_MB)
        try:
            meminfo = self._meminfo_path.read_text(encoding="utf-8")
        except OSError as exc:
            return CheckResult("memory", False, f"cannot read {self._meminfo_path}: {exc}")
        total_kb = next((int(line.split()[1]) for line in meminfo.splitlines() if line.startswith("MemTotal:")), 0)
        total_mb = total_kb // 1024
        return CheckResult("memory", total_mb >= minimum, f"{total_mb} MB total (need {minimum} MB)")

    def check_disk(self) -> List[CheckResult]:
        """Enough free space in the install directory, and usage below the alert threshold."""
        minimum = self._threshold("PREFLIGHT_MIN_FREE_DISK_GB", DEFAULT_MIN_FREE_DISK_GB)
        usage = shutil.disk_usage(self._layout.root)
        free_gb = usage.free // GIB
        ratio = usage.used / usage.total if usage.total else 0.0
        return [
            CheckResult("disk", free_gb >= minimum, f"{free_gb} GB free in {self._layout.root} (need {minimum} GB)"),
            CheckResult("disk usage", ratio < DISK_WARN_RATIO, f"{ratio:.0%} used", fatal=False),
        ]

    def check_dns(self) -> List[CheckResult]:
        """Both public domains resolve (to the same addresses, which is expected on one box)."""
        results = []
        addresses: Dict[str, List[str]] = {}
        for key in ("PUBLIC_DOMAIN_CHAT", "PUBLIC_DOMAIN_ADMIN"):
            domain = self._env.get(key, "")
            found = self._resolve(domain) if domain else []
            addresses[key] = found
            results.append(CheckResult(f"dns {domain or key}", bool(found),
                                       ", ".join(found) if found else "does not resolve; create an A/AAAA record for this box"))
        chat, admin = addresses["PUBLIC_DOMAIN_CHAT"], addresses["PUBLIC_DOMAIN_ADMIN"]
        if chat and admin:
            same = set(chat) == set(admin)
            results.append(CheckResult("dns same box", same, "both domains point at the same addresses" if same
                                       else "the domains point at different addresses", fatal=False))
        return results

    def check_backup_target(self) -> CheckResult:
        """The backup target accepts a write and a delete."""
        try:
            manager = self._backups()
            if manager is None:
                return CheckResult("backup target", False, "BACKUP_TARGET is not configured")
            manager.check_reachable()
        except (BackupTargetError, CommandError, OSError) as exc:
            return CheckResult("backup target", False, str(exc)[:300])
        return CheckResult("backup target", True, f"writable ({self._ops_env.get('BACKUP_TARGET', '')})")

    def check_alert(self) -> CheckResult:
        """The backend's notifier delivers a test alert."""
        try:
            output = self._compose.run_once("api", ["python", "-m", "scripts.manage", "test-alert"], timeout=180).stdout
        except CommandError as exc:
            return CheckResult("alert channel", False, str(exc)[:300])
        return CheckResult("alert channel", True, output.strip().splitlines()[-1] if output.strip() else "sent")


    def check_business_db(self) -> CheckResult:
        """The business database role given to the SQL tools cannot write (TOOL-05)."""
        try:
            output = self._compose.run_once("api", ["python", "-m", "scripts.manage", "check-business-db"], timeout=120).stdout
        except CommandError as exc:
            return CheckResult("business db read-only", False, str(exc)[:300])
        return CheckResult("business db read-only", True, output.strip().splitlines()[-1] if output.strip() else "ok")


def _resolve(domain: str) -> List[str]:
    """Addresses a domain resolves to (empty when it does not)."""
    try:
        return sorted({info[4][0] for info in socket.getaddrinfo(domain, 443, proto=socket.IPPROTO_TCP)})
    except socket.gaierror:
        logger.warning("DNS lookup failed for %s", domain)
        return []
