"""
Settings for logged-in users of the host website (host-issued JWTs).

``HOST_AUTH_MODE`` is per deployment and needs no code change:

* ``rs256`` (default): the host signs short-lived tokens with its private key;
  we verify with ``HOST_JWKS_URL`` when set, else ``HOST_JWT_PUBLIC_KEY`` (PEM).
  The host's secret never reaches this server.
* ``hs256``: fallback for hosts that cannot do RS256; ``HOST_JWT_SECRET`` is shared.
* ``none``: anonymous-only; private tools and per-user features are off.
"""

# Standard library imports
import logging
from pathlib import Path
from typing import List

# Local imports
from .env import env_int, env_list, env_str

logger = logging.getLogger(__name__)

HOST_AUTH_RS256 = "rs256"
HOST_AUTH_HS256 = "hs256"
HOST_AUTH_NONE = "none"
HOST_AUTH_MODES = (HOST_AUTH_RS256, HOST_AUTH_HS256, HOST_AUTH_NONE)


class HostAuthConfig:
    """How host-site tokens are verified."""

    @staticmethod
    def HOST_AUTH_MODE() -> str:
        """``rs256``, ``hs256`` or ``none``."""
        return env_str("HOST_AUTH_MODE", HOST_AUTH_RS256).strip().lower()

    @staticmethod
    def HOST_ORIGINS() -> List[str]:
        """Origins of the host website (space or comma separated ``HOST_ORIGIN``)."""
        raw = env_str("HOST_ORIGIN", "")
        return [item.rstrip("/") for item in raw.replace(",", " ").split() if item]

    @staticmethod
    def HOST_JWT_ISSUER() -> str:
        """Required ``iss`` claim (defaults to the first host origin)."""
        origins = HostAuthConfig.HOST_ORIGINS()
        return env_str("HOST_JWT_ISSUER", "") or (origins[0] if origins else "")

    @staticmethod
    def HOST_JWT_AUDIENCE() -> str:
        """Required ``aud`` claim (defaults to the chat domain's URL)."""
        chat_domain = env_str("PUBLIC_DOMAIN_CHAT", "")
        return env_str("HOST_JWT_AUDIENCE", "") or (f"https://{chat_domain}" if chat_domain else "")

    @staticmethod
    def HOST_JWKS_URL() -> str:
        """The host's JWKS endpoint (``rs256``, takes precedence over a static key)."""
        return env_str("HOST_JWKS_URL", "")

    @staticmethod
    def HOST_JWT_PUBLIC_KEY() -> str:
        """
        The host's RSA public key in PEM (``rs256`` without JWKS).

        Read from ``HOST_JWT_PUBLIC_KEY_FILE`` (the installer's Docker secret)
        when set, else from ``HOST_JWT_PUBLIC_KEY`` with ``\\n`` escapes.
        """
        path = env_str("HOST_JWT_PUBLIC_KEY_FILE", "")
        if path:
            try:
                return Path(path).read_text(encoding="utf-8").strip()
            except OSError:
                logger.exception("Cannot read HOST_JWT_PUBLIC_KEY_FILE")
                return ""
        return env_str("HOST_JWT_PUBLIC_KEY", "").replace("\\n", "\n").strip()

    @staticmethod
    def HOST_JWT_SECRET() -> str:
        """Shared HMAC secret (``hs256`` only)."""
        return env_str("HOST_JWT_SECRET", "")

    @staticmethod
    def HOST_TIERS() -> List[str]:
        """Logged-in tiers the host may put in the ``tier`` claim, lowest first."""
        return [tier.lower() for tier in env_list("HOST_TIERS", "user,premium")]

    @staticmethod
    def HOST_TOKEN_MAX_TTL_SECONDS() -> int:
        """Longest accepted token lifetime (``exp - iat``); longer tokens are refused."""
        return env_int("HOST_TOKEN_MAX_TTL_SECONDS", 900)

    @staticmethod
    def HOST_TOKEN_LEEWAY_SECONDS() -> int:
        """Clock skew tolerated between the host and this server."""
        return env_int("HOST_TOKEN_LEEWAY_SECONDS", 30)

    @staticmethod
    def problems() -> List[str]:
        """Missing or unsafe host-auth settings (fatal in production)."""
        mode = HostAuthConfig.HOST_AUTH_MODE()
        if mode not in HOST_AUTH_MODES:
            return [f"HOST_AUTH_MODE must be one of {', '.join(HOST_AUTH_MODES)}"]
        if mode == HOST_AUTH_NONE:
            return []
        issues = []
        if not HostAuthConfig.HOST_JWT_ISSUER() or not HostAuthConfig.HOST_JWT_AUDIENCE():
            issues.append("HOST_JWT_ISSUER and HOST_JWT_AUDIENCE (or HOST_ORIGIN and PUBLIC_DOMAIN_CHAT) are required")
        if mode == HOST_AUTH_RS256 and not (HostAuthConfig.HOST_JWKS_URL() or HostAuthConfig.HOST_JWT_PUBLIC_KEY()):
            issues.append("HOST_AUTH_MODE=rs256 needs HOST_JWKS_URL or HOST_JWT_PUBLIC_KEY(_FILE)")
        if mode == HOST_AUTH_HS256 and len(HostAuthConfig.HOST_JWT_SECRET()) < 32:
            issues.append("HOST_AUTH_MODE=hs256 needs a HOST_JWT_SECRET of at least 32 characters")
        return issues
