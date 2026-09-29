"""
``chatbot rotate-secrets``: replace the generated secrets on a running box.

Database passwords are changed inside PostgreSQL first, then written to
``.env``/``secrets/``, then the stack is recreated so every container picks up
its new value. Admin sessions end (new signing secret); anonymous visitors
keep their history unless the visitor-cookie secret is rotated too.
"""

# Standard library imports
import logging
from typing import Callable, List

# Local imports
from .compose import Compose
from .deployer import APP_ROLE_SCRIPT, ENV_HEADER, HEALTH_GATE_SERVICES, HEALTH_TIMEOUT_SECONDS
from .env_file import EnvFile
from .layout import InstallLayout
from .secret_generator import SecretGenerator

logger = logging.getLogger(__name__)

DB_OWNER = "chatbot"


class SecretRotator:
    """Rotates generated secrets without downtime beyond a container restart."""

    def __init__(self, layout: InstallLayout, compose: Compose, generator: SecretGenerator,
                 out: Callable[[str], None] = print):
        """
        Args:
            layout: The install directory.
            compose: Compose for the (running) stack.
            generator: Produces the new values.
            out: Progress output for the operator.
        """
        self._layout = layout
        self._compose = compose
        self._generator = generator
        self._out = out

    def rotate(self, include_visitor_cookie: bool = False) -> List[str]:
        """
        Rotate and apply the secrets.

        Returns:
            Names of the rotated settings.

        Raises:
            CommandError: The database could not be updated (nothing was written then).
        """
        env = EnvFile(self._layout.env_file).load()
        rotated = self._generator.rotate(env, include_visitor_cookie)
        new_owner_password = self._generator.new_owner_password()
        self._out("Changing database passwords…")
        self._compose.exec("postgres", ["sh", APP_ROLE_SCRIPT], env={"POSTGRES_APP_PASSWORD": env.get("POSTGRES_APP_PASSWORD", "")})
        # The token alphabet is URL-safe base64, so it is a safe SQL string literal.
        self._compose.exec("postgres", ["psql", "-v", "ON_ERROR_STOP=1", "-U", DB_OWNER, "-d", DB_OWNER],
                           input_text=f"ALTER ROLE {DB_OWNER} PASSWORD '{new_owner_password}';\n")
        env.save(ENV_HEADER)
        self._generator.write_owner_password(self._layout, new_owner_password)
        self._out("Recreating containers with the new secrets…")
        self._compose.up()
        self._compose.wait_healthy(HEALTH_GATE_SERVICES, HEALTH_TIMEOUT_SECONDS)
        logger.info("Rotated %d secrets", len(rotated) + 1)
        return [*rotated, "postgres owner password"]
