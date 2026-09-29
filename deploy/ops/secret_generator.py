"""
Generates every secret an install needs; none is ever typed in or given a default.

Reruns keep existing values, so an install can be repeated safely; rotation
is an explicit command (``chatbot rotate-secrets``).
"""

# Standard library imports
import os
import secrets
from typing import Callable, Dict, List

# Local imports
from .env_file import EnvFile
from .layout import InstallLayout

#: Generated settings and their entropy in bytes (URL-safe base64, so no quoting is ever needed).
GENERATED_SECRETS: Dict[str, int] = {
    "POSTGRES_APP_PASSWORD": 32,
    "ADMIN_JWT_SECRET": 48,
    "VISITOR_COOKIE_SECRET": 48,
    "BFF_SERVICE_TOKEN": 48,
    # api and ingestion-worker -> model-server.
    "MODEL_SERVER_TOKEN": 48,
    # Used only with HOST_AUTH_MODE=hs256 (shared with the host backend through the hand-over bundle).
    "HOST_JWT_SECRET": 48,
}
#: Rotating this signs every anonymous visitor out of their history, so it is opt-in.
VISITOR_COOKIE_SECRET = "VISITOR_COOKIE_SECRET"
OWNER_PASSWORD_BYTES = 32
#: Readable inside the containers (unprivileged users); private on the host through the 0700 directory.
SECRET_FILE_MODE = 0o644

TokenFactory = Callable[[int], str]


class SecretGenerator:
    """Fills in and rotates generated secrets."""

    def __init__(self, token_factory: TokenFactory = secrets.token_urlsafe):
        """
        Args:
            token_factory: Returns a random URL-safe string from a byte count.
        """
        self._token = token_factory

    def ensure(self, env: EnvFile) -> List[str]:
        """
        Generate every missing secret in ``env``.

        Returns:
            Names of the settings that were generated now.
        """
        generated = []
        for name, size in GENERATED_SECRETS.items():
            if not env.get(name):
                env.set(name, self._token(size))
                generated.append(name)
        return generated

    def rotate(self, env: EnvFile, include_visitor_cookie: bool = False) -> List[str]:
        """
        Replace the generated secrets with new values.

        Returns:
            Names of the settings that changed.
        """
        rotated = []
        for name, size in GENERATED_SECRETS.items():
            if name == VISITOR_COOKIE_SECRET and not include_visitor_cookie:
                continue
            env.set(name, self._token(size))
            rotated.append(name)
        return rotated

    def new_owner_password(self) -> str:
        """A fresh PostgreSQL owner password (not yet written anywhere)."""
        return self._token(OWNER_PASSWORD_BYTES)

    def ensure_owner_password(self, layout: InstallLayout) -> str:
        """
        Create the PostgreSQL owner password file unless it exists.

        Returns:
            The password in the file.
        """
        path = layout.owner_password_file
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        password = self.new_owner_password()
        self.write_owner_password(layout, password)
        return password

    @staticmethod
    def write_owner_password(layout: InstallLayout, password: str) -> None:
        """Atomically (re)write the owner password file."""
        layout.secrets_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(layout.secrets_dir, 0o700)
        path = layout.owner_password_file
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(password, encoding="utf-8")
        os.chmod(temporary, SECRET_FILE_MODE)
        os.replace(temporary, path)
