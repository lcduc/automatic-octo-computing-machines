"""
The host-site signing key and the hand-over bundle for the host's developers.

On first install an RSA key pair is generated (openssl): the public key goes to
``secrets/host_jwt_public.pem``, which the API reads as a Docker secret; the
private key goes only into ``handover/host-integration.zip`` together with the
host-sdk snippets, pre-filled with this deployment's issuer, audience and
domains. The private key is never written anywhere the application can read.
"""

# Standard library imports
import logging
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, Optional

# Local imports
from .layout import InstallLayout
from .runner import CommandRunner

logger = logging.getLogger(__name__)

PUBLIC_KEY_FILE = "host_jwt_public.pem"
BUNDLE_NAME = "host-integration.zip"
PRIVATE_KEY_NAME = "chatbot-signing-key.pem"
RSA_BITS = "2048"
#: Files of host-sdk/ copied into the bundle, with placeholders filled in.
SDK_FILES = ("README.md", "host-page.html", "node/chatbot-token.mjs", "php/chatbot_token.php", "python/chatbot_token.py")
PUBLIC_FILE_MODE = 0o644


class HostIntegrationBundle:
    """Generates the host signing key pair and packages the host-sdk hand-over."""

    def __init__(self, layout: InstallLayout, runner: CommandRunner, templates_dir: Path):
        """
        Args:
            layout: The install directory.
            runner: Runs openssl.
            templates_dir: Holds ``host-sdk/``.
        """
        self._layout = layout
        self._runner = runner
        self._templates_dir = templates_dir

    @property
    def public_key_path(self) -> Path:
        """Public key read by the API (a Docker secret)."""
        return self._layout.secrets_dir / PUBLIC_KEY_FILE

    @property
    def bundle_path(self) -> Path:
        """The zip handed to the host's developers."""
        return self._layout.handover_dir / BUNDLE_NAME

    def ensure_keys(self, rotate: bool = False) -> Optional[str]:
        """
        Generate the key pair unless a public key exists (or ``rotate``).

        Returns:
            The new private key in PEM (for the bundle only), or ``None`` when
            the existing key pair was kept.
        """
        if self.public_key_path.exists() and not rotate:
            return None
        self._layout.secrets_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as scratch:
            private_path = Path(scratch) / PRIVATE_KEY_NAME
            self._runner.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", f"rsa_keygen_bits:{RSA_BITS}",
                              "-out", str(private_path)])
            public_pem = _normalise_pem(self._runner.run(["openssl", "pkey", "-in", str(private_path), "-pubout"]).stdout)
            private_pem = _normalise_pem(private_path.read_text(encoding="utf-8"))
        temporary = self.public_key_path.with_name(PUBLIC_KEY_FILE + ".tmp")
        temporary.write_text(public_pem, encoding="utf-8", newline="\n")
        os.chmod(temporary, PUBLIC_FILE_MODE)
        os.replace(temporary, self.public_key_path)
        logger.info("Generated a new host signing key pair")
        return private_pem

    def write(self, env: Dict[str, str], private_key_pem: Optional[str], shared_secret: Optional[str] = None) -> Path:
        """
        Build the hand-over zip (mode 0600 in the 0700 handover directory).

        Args:
            env: ``.env`` values (domains, issuer, audience).
            private_key_pem: RS256 signing key to include, if newly generated.
            shared_secret: HS256 secret to include instead (hs256 mode).
        """
        values = {
            "{{ISSUER}}": env.get("HOST_JWT_ISSUER", ""),
            "{{AUDIENCE}}": env.get("HOST_JWT_AUDIENCE", ""),
            "{{CHAT_DOMAIN}}": env.get("PUBLIC_DOMAIN_CHAT", ""),
            "{{HOST_ORIGIN}}": env.get("HOST_ORIGIN", ""),
        }
        self._layout.handover_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.bundle_path.with_name(BUNDLE_NAME + ".tmp")
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for relative in SDK_FILES:
                text = (self._templates_dir / "host-sdk" / relative).read_text(encoding="utf-8")
                for placeholder, value in values.items():
                    text = text.replace(placeholder, value)
                archive.writestr(relative, text)
            if private_key_pem:
                archive.writestr(PRIVATE_KEY_NAME, private_key_pem)
            if shared_secret:
                archive.writestr("chatbot-shared-secret.txt", shared_secret + "\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.bundle_path)
        return self.bundle_path


def _normalise_pem(pem: str) -> str:
    """One LF per line, whatever line endings openssl produced (CRLF on Windows builds)."""
    return "\n".join(line.strip() for line in pem.splitlines() if line.strip()) + "\n"
