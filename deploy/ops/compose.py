"""
``docker compose`` for the install directory's stack.
"""

# Standard library imports
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence

# Local imports
from .layout import COMPOSE_PROJECT, InstallLayout
from .runner import CommandError, CommandResult, CommandRunner

logger = logging.getLogger(__name__)

#: Seconds between health polls while waiting for services.
HEALTH_POLL_SECONDS = 5


class Compose:
    """Runs compose commands against ``docker-compose.yml`` in one install directory."""

    def __init__(self, layout: InstallLayout, runner: CommandRunner, clock=time.monotonic, sleep=time.sleep):
        """
        Args:
            layout: The install directory.
            runner: Executes the ``docker`` commands.
            clock: Monotonic time source (injectable for tests).
            sleep: Pause function (injectable for tests).
        """
        self._layout = layout
        self._runner = runner
        self._clock = clock
        self._sleep = sleep

    def _base(self) -> List[str]:
        """The ``docker compose`` prefix pinned to this install."""
        return [
            "docker", "compose", "--project-name", COMPOSE_PROJECT,
            "--project-directory", str(self._layout.root), "--file", str(self._layout.compose_file),
        ]

    def run(self, args: Sequence[str], **kwargs) -> CommandResult:
        """Run ``docker compose <args>`` (keyword arguments go to :meth:`CommandRunner.run`)."""
        return self._runner.run([*self._base(), *args], **kwargs)

    def pull(self) -> None:
        """Pull every image of the current ``IMAGE_TAG``."""
        logger.info("Pulling images")
        self.run(["pull", "--quiet"], timeout=3600)

    def up(self, services: Sequence[str] = ()) -> None:
        """
        Create/refresh services in the background (all when ``services`` is empty).

        Compose still honours ``depends_on`` conditions, so this returns only
        after ``migrate`` completed and the services the others wait for are healthy.
        """
        self.run(["up", "--detach", "--remove-orphans", *services], timeout=1800)

    def stop(self, services: Sequence[str]) -> None:
        """Stop the given services, keeping their containers."""
        self.run(["stop", *services], timeout=300)

    def exec(self, service: str, command: Sequence[str], env: Optional[Mapping[str, str]] = None,
             input_text: Optional[str] = None, stdin_path: Optional[Path] = None,
             stdout_path: Optional[Path] = None, timeout: int = 3600) -> CommandResult:
        """Run a command inside a running service container (no TTY)."""
        env_args: List[str] = []
        for key, value in (env or {}).items():
            env_args += ["--env", f"{key}={value}"]
        return self.run(["exec", "-T", *env_args, service, *command], input_text=input_text,
                        stdin_path=stdin_path, stdout_path=stdout_path, timeout=timeout)

    def run_once(self, service: str, command: Sequence[str], timeout: int = 600) -> CommandResult:
        """Run a one-off container of ``service`` without starting its dependencies."""
        return self.run(["run", "--rm", "--no-deps", "-T", service, *command], timeout=timeout)

    def ps(self) -> List[Dict]:
        """Status of every service container (``docker compose ps --format json``)."""
        result = self.run(["ps", "--all", "--format", "json"])
        text = result.stdout.strip()
        if not text:
            return []
        if text.startswith("["):
            return json.loads(text)
        # Compose >= 2.21 prints one JSON object per line.
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def is_running(self, service: str) -> bool:
        """True when ``service`` has a running container."""
        try:
            return any(item.get("Service") == service and item.get("State") == "running" for item in self.ps())
        except CommandError:
            logger.exception("Could not read compose status")
            return False

    def wait_healthy(self, services: Sequence[str], timeout_seconds: int) -> None:
        """
        Wait until each service is running and (when it has a healthcheck) healthy.

        Raises:
            CommandError: A service is not healthy before the timeout.
        """
        deadline = self._clock() + timeout_seconds
        pending = list(services)
        while pending:
            states = {item.get("Service"): item for item in self.ps()}
            pending = [name for name in pending if not _healthy(states.get(name))]
            if not pending:
                return
            if self._clock() >= deadline:
                raise CommandError(f"Not healthy after {timeout_seconds}s: {', '.join(pending)}")
            self._sleep(HEALTH_POLL_SECONDS)


def _healthy(state: Optional[Dict]) -> bool:
    """A running container whose healthcheck (if any) reports healthy."""
    if not state or state.get("State") != "running":
        return False
    return state.get("Health", "") in ("", "healthy")
