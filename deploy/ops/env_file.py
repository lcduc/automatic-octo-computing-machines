"""
Reads and writes the generated ``.env``/``ops.env`` files.

The format stays within what docker compose, Docker's ``env_file`` and
python-dotenv all parse the same way: ``KEY=value``, with single quotes (no
interpolation) around any value outside a plain character set.
"""

# Standard library imports
import os
import re
import tempfile
from pathlib import Path
from typing import Dict, Optional

#: Values made only of these characters are written unquoted.
PLAIN_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9_./:@,+=-]*$")
KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
PRIVATE_FILE_MODE = 0o600


class EnvFileError(ValueError):
    """A key or value cannot be written safely."""


class EnvFile:
    """An ordered ``KEY=value`` file; unknown keys found on disk are preserved."""

    def __init__(self, path: Path):
        """
        Args:
            path: File location (need not exist yet).
        """
        self._path = path
        self._values: Dict[str, str] = {}

    @property
    def path(self) -> Path:
        """Where the file lives."""
        return self._path

    def load(self) -> "EnvFile":
        """Read the file if it exists (comments and blank lines are dropped)."""
        if not self._path.exists():
            return self
        for line in self._path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, raw = stripped.partition("=")
            self._values[key.strip()] = self._unquote(raw.strip())
        return self

    @staticmethod
    def _unquote(raw: str) -> str:
        """Strip one pair of surrounding single or double quotes."""
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
            return raw[1:-1]
        return raw

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """The value of ``key``, or ``default`` when absent or empty."""
        value = self._values.get(key)
        return value if value else default

    def set(self, key: str, value: str) -> None:
        """
        Set ``key`` (validated so the written file parses identically everywhere).

        Raises:
            EnvFileError: Malformed key, or a value containing quotes or newlines.
        """
        if not KEY_PATTERN.match(key):
            raise EnvFileError(f"Invalid setting name {key!r}")
        if any(char in value for char in ("'", "\n", "\r")):
            raise EnvFileError(f"{key} must not contain single quotes or line breaks")
        self._values[key] = value

    def setdefault(self, key: str, value: str) -> str:
        """Set ``key`` only when it is missing or empty; return its resulting value."""
        if not self._values.get(key):
            self.set(key, value)
        return self._values[key]

    def as_dict(self) -> Dict[str, str]:
        """A copy of every value."""
        return dict(self._values)

    def save(self, header: str) -> None:
        """
        Write atomically with mode 0600.

        Args:
            header: Comment placed at the top of the file.
        """
        lines = [f"# {line}" if line else "#" for line in header.splitlines()]
        for key, value in self._values.items():
            lines.append(f"{key}={value}" if PLAIN_VALUE_PATTERN.match(value) else f"{key}='{value}'")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=self._path.parent, prefix=".env.")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write("\n".join(lines) + "\n")
            os.chmod(temporary, PRIVATE_FILE_MODE)
            os.replace(temporary, self._path)
        except OSError:
            Path(temporary).unlink(missing_ok=True)
            raise
