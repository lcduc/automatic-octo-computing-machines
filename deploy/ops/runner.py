"""
Runs external commands (docker, rclone, openssl) for the ops CLI.

A single seam around :mod:`subprocess`, so every other ops class can be
tested with a fake runner and no Docker daemon.
"""

# Standard library imports
import logging
import subprocess
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

#: Default seconds a command may run before it is killed.
DEFAULT_TIMEOUT_SECONDS = 600


class CommandError(RuntimeError):
    """A command exited non-zero (its stderr is in the message) or could not start."""


@dataclass(frozen=True)
class CommandResult:
    """Outcome of one finished command."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        """True when the command exited with status 0."""
        return self.returncode == 0


class CommandRunner:
    """Thin wrapper over :func:`subprocess.run` with logging and uniform errors."""

    def run(
        self,
        args: Sequence[str],
        env: Optional[Mapping[str, str]] = None,
        input_text: Optional[str] = None,
        stdin_path: Optional[Path] = None,
        stdout_path: Optional[Path] = None,
        check: bool = True,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> CommandResult:
        """
        Run ``args`` to completion.

        Args:
            args: Program and arguments (never passed through a shell).
            env: Full environment for the child; ``None`` inherits ours.
            input_text: Written to the child's stdin.
            stdin_path: Stream this file into the child's stdin (for restores).
            stdout_path: Stream stdout into this file instead of capturing it
                (for dumps too large to hold in memory).
            check: Raise :class:`CommandError` on a non-zero exit.
            timeout: Seconds before the child is killed.

        Raises:
            CommandError: The command failed (``check``), timed out or is missing.
        """
        logger.debug("Running %s", args[0] if args else "")
        child_env = dict(env) if env is not None else None
        try:
            with ExitStack() as stack:
                stdin = stack.enter_context(open(stdin_path, "rb")) if stdin_path is not None else None
                stdout = stack.enter_context(open(stdout_path, "wb")) if stdout_path is not None else subprocess.PIPE
                completed = subprocess.run(
                    list(args), env=child_env, stdin=stdin, stdout=stdout, stderr=subprocess.PIPE,
                    input=input_text.encode() if input_text is not None and stdin is None else None,
                    timeout=timeout,
                )
        except FileNotFoundError as exc:
            raise CommandError(f"{args[0]} is not installed") from exc
        except subprocess.TimeoutExpired as exc:
            raise CommandError(f"{args[0]} timed out after {timeout}s") from exc
        captured = completed.stdout.decode("utf-8", errors="replace") if isinstance(completed.stdout, bytes) else ""
        stderr = completed.stderr.decode("utf-8", errors="replace") if completed.stderr else ""
        result = CommandResult(completed.returncode, captured, stderr)
        if check and not result.ok:
            raise CommandError(f"{' '.join(args[:3])} failed ({result.returncode}): {stderr.strip()[-800:]}")
        return result


def merged_env(base: Mapping[str, str], extra: Dict[str, str]) -> Dict[str, str]:
    """A copy of ``base`` with ``extra`` applied on top."""
    merged = dict(base)
    merged.update(extra)
    return merged
