"""
Settings for the product platform: database, HTTP server, security and chat policy.

Split from ``settings.py`` (which keeps the AI/retrieval knobs) so neither file
grows past a readable size. Everything is re-exported through ``Config``.
"""

# Standard library imports
from typing import List
from urllib.parse import quote_plus

# Local imports
from .env import env_bool, env_int, env_list, env_str

#: Values of ``APP_ENV`` that enable strict start-up validation.
PRODUCTION_ENVIRONMENTS = {"production", "prod"}


class DatabaseConfig:
    """PostgreSQL (+ pgvector) connection settings."""

    @staticmethod
    def POSTGRES_HOST() -> str:
        """Database host name."""
        return env_str("POSTGRES_HOST", "localhost")

    @staticmethod
    def POSTGRES_PORT() -> int:
        """Database port."""
        return env_int("POSTGRES_PORT", 5432)

    @staticmethod
    def POSTGRES_DB() -> str:
        """Database name."""
        return env_str("POSTGRES_DB", "chatbot")

    @staticmethod
    def POSTGRES_USER() -> str:
        """Database role."""
        return env_str("POSTGRES_USER", "chatbot")

    @staticmethod
    def POSTGRES_PASSWORD() -> str:
        """Database password."""
        return env_str("POSTGRES_PASSWORD", "")

    @staticmethod
    def DB_POOL_SIZE() -> int:
        """Connections kept open in the async pool."""
        return env_int("DB_POOL_SIZE", 10)

    @staticmethod
    def DATABASE_URL() -> str:
        """
        SQLAlchemy async URL assembled from the ``POSTGRES_*`` variables.

        ``DATABASE_URL`` overrides the assembled value when set (useful for
        tests pointing at a throw-away database).
        """
        override = env_str("DATABASE_URL", "")
        if override:
            return override
        return (
            f"postgresql+asyncpg://{quote_plus(DatabaseConfig.POSTGRES_USER())}:"
            f"{quote_plus(DatabaseConfig.POSTGRES_PASSWORD())}@{DatabaseConfig.POSTGRES_HOST()}:"
            f"{DatabaseConfig.POSTGRES_PORT()}/{DatabaseConfig.POSTGRES_DB()}"
        )


class ServerConfig:
    """HTTP server binding and deployment environment."""

    @staticmethod
    def APP_ENV() -> str:
        """``development`` or ``production``; production refuses insecure settings."""
        return env_str("APP_ENV", "development").strip().lower()

    @staticmethod
    def IS_PRODUCTION() -> bool:
        """True when ``APP_ENV`` names a production deployment."""
        return ServerConfig.APP_ENV() in PRODUCTION_ENVIRONMENTS

    @staticmethod
    def HOST() -> str:
        """Bind address."""
        return env_str("HOST", "0.0.0.0")

    @staticmethod
    def PORT() -> int:
        """Bind port."""
        return env_int("PORT", 8500)

    @staticmethod
    def DEBUG() -> bool:
        """Enable FastAPI debug mode and Uvicorn auto-reload."""
        return env_bool("DEBUG", False)

    @staticmethod
    def APP_TIMEZONE() -> str:
        """IANA time zone used for "today" in token budgets and daily statistics."""
        return env_str("APP_TIMEZONE", "Asia/Ho_Chi_Minh")

    @staticmethod
    def FORWARDED_ALLOW_IPS() -> str:
        """
        Proxies whose ``X-Forwarded-For`` header is trusted for the client IP.

        The browser never talks to this API directly: the Next.js server (and
        any TLS proxy in front of it) does, so their addresses go here. Passed
        straight to Uvicorn's ``forwarded_allow_ips``.
        """
        return env_str("FORWARDED_ALLOW_IPS", "127.0.0.1")


class SecurityConfig:
    """Authentication, CORS, rate limiting and guardrail switches."""

    @staticmethod
    def CORS_ORIGINS() -> List[str]:
        """Browser origins allowed to call the API directly (the web frontend)."""
        return env_list("CORS_ORIGINS", "http://localhost:3000")

    @staticmethod
    def ADMIN_JWT_SECRET() -> str:
        """HMAC secret signing admin session tokens; must be long and random."""
        return env_str("ADMIN_JWT_SECRET", "")

    @staticmethod
    def ADMIN_TOKEN_TTL_MINUTES() -> int:
        """Lifetime of an admin session token."""
        return env_int("ADMIN_TOKEN_TTL_MINUTES", 480)

    @staticmethod
    def RATE_LIMIT_USER_PER_MINUTE() -> int:
        """Chat requests allowed per end user per minute."""
        return env_int("RATE_LIMIT_USER_PER_MINUTE", 20)

    @staticmethod
    def RATE_LIMIT_IP_PER_MINUTE() -> int:
        """Requests allowed per client IP per minute, across all endpoints."""
        return env_int("RATE_LIMIT_IP_PER_MINUTE", 120)

    @staticmethod
    def DAILY_TOKEN_BUDGET_PER_USER() -> int:
        """LLM tokens (prompt + completion) one end user may consume per day; 0 = unlimited."""
        return env_int("DAILY_TOKEN_BUDGET_PER_USER", 60000)

    @staticmethod
    def MAX_CONCURRENT_CHATS() -> int:
        """Chat turns generated at the same time; extra requests get HTTP 503."""
        return env_int("MAX_CONCURRENT_CHATS", 16)

    @staticmethod
    def PII_REDACTION_ENABLED() -> bool:
        """Mask phone numbers, ID numbers, emails… before logging, storing or prompting."""
        return env_bool("PII_REDACTION_ENABLED", True)

    @staticmethod
    def MODERATION_ENABLED() -> bool:
        """Screen user messages with OpenAI's free moderation endpoint (needs ``OPENAI_API_KEY``)."""
        return env_bool("MODERATION_ENABLED", True)


class ChatConfig:
    """Conversation policy defaults (runtime values are editable in the admin web)."""

    @staticmethod
    def MAX_HISTORY_TURNS() -> int:
        """
        Prior question/answer pairs replayed into the prompt.

        History is loaded server-side from the conversation's stored messages;
        one turn = one user message + one assistant reply.
        """
        return env_int("MAX_HISTORY_TURNS", 6)

    @staticmethod
    def MAX_MESSAGE_LENGTH() -> int:
        """Longest accepted user message, in characters."""
        return env_int("MAX_MESSAGE_LENGTH", 2000)

    @staticmethod
    def FALLBACK_MODE() -> str:
        """
        Initial fallback mode, used until an admin changes it at runtime.

        ``deny`` answers with ``AutoReplies.DENY`` without calling the LLM;
        ``handoff`` records a transfer-to-human request instead.
        """
        return env_str("FALLBACK_MODE", "deny").strip().lower()

