"""
Centralized configuration for the RAG chatbot.

Every setting is read from the environment through the typed helpers in
:mod:`app.config.env`. Each environment variable is defined in exactly one place;
the grouped classes (``LLM``, ``RAG``, …) are namespaced views over those
definitions, collected under :class:`Config`. The groups live in the
``*_settings.py`` modules beside this one (LLM in ``llm_settings``; uploads,
retrieval, OCR and routing in ``knowledge_settings``; database, server,
security and chat policy in ``platform_settings``); only paths and logging stay here.
"""

# Standard library imports
import logging
import os
from pathlib import Path
from typing import List

# Third-party imports
from dotenv import load_dotenv

# Local imports
from .env import env_str
from .identity_settings import HostAuthConfig
from .knowledge_settings import FileConfig, OCRConfig, RAGConfig, RoutingConfig
from .llm_settings import STUB_PROVIDER, LLMConfig
from .model_server_settings import ModelServerConfig
from .notification_settings import ALERT_CHANNELS, SMTP_SECURITY_MODES, AlertConfig, SmtpConfig
from .platform_settings import ChatConfig, DatabaseConfig, SecurityConfig, ServerConfig

load_dotenv()

logger = logging.getLogger(__name__)

#: Shortest admin JWT secret or service token accepted in production (bytes of entropy ≈ chars/2 for hex).
MIN_JWT_SECRET_LENGTH = 32


class PathConfig:
    """Local directories the application writes to."""

    @staticmethod
    def LOG_DIR() -> str:
        """Directory for rotating JSON application logs."""
        return env_str("LOG_DIR", "data/logs")

    @staticmethod
    def MODELS_DIR() -> str:
        """
        Local cache directory for downloaded ML models.

        Kept inside the project root (rather than the OS-wide Hugging Face
        cache) so the weights of a deployment are visible and reviewable on
        disk. Named distinctly from the ``models/`` Python package.
        """
        return env_str("MODELS_DIR", "model_weights")

    @staticmethod
    def UPLOAD_DIR() -> str:
        """Uploaded files awaiting ingestion; must be shared by the API and the ingestion worker."""
        return env_str("UPLOAD_DIR", "data/uploads")


class LoggingConfig:
    """Log level and destination."""

    @staticmethod
    def LOG_LEVEL() -> str:
        """Root logger level name."""
        return env_str("LOG_LEVEL", "INFO")

    LOG_DIR = PathConfig.LOG_DIR


class Config:
    """Namespaced access point for every configuration group."""

    Paths = PathConfig
    Database = DatabaseConfig
    LLM = LLMConfig
    File = FileConfig
    Server = ServerConfig
    Security = SecurityConfig
    RAG = RAGConfig
    Routing = RoutingConfig
    Chat = ChatConfig
    OCR = OCRConfig
    Logging = LoggingConfig
    Alerts = AlertConfig
    Smtp = SmtpConfig
    HostAuth = HostAuthConfig
    ModelServer = ModelServerConfig

    @staticmethod
    def problems() -> List[str]:
        """
        Settings that are unsafe or missing for a real deployment.

        Returns:
            Human-readable problem descriptions; empty when all is well.
        """
        issues: List[str] = []
        if len(SecurityConfig.ADMIN_JWT_SECRET()) < MIN_JWT_SECRET_LENGTH:
            issues.append(
                f"ADMIN_JWT_SECRET must be at least {MIN_JWT_SECRET_LENGTH} characters "
                "(generate one with: python -c \"import secrets; print(secrets.token_hex(32))\")"
            )
        if len(SecurityConfig.BFF_SERVICE_TOKEN()) < MIN_JWT_SECRET_LENGTH:
            issues.append(
                f"BFF_SERVICE_TOKEN must be at least {MIN_JWT_SECRET_LENGTH} characters (the installer generates it)"
            )
        if not DatabaseConfig.POSTGRES_PASSWORD() and not os.getenv("DATABASE_URL"):
            issues.append("POSTGRES_PASSWORD is empty")
        if "*" in SecurityConfig.CORS_ORIGINS():
            issues.append("CORS_ORIGINS must list explicit origins, not '*'")
        if LLMConfig.LLM_PROVIDER().strip().lower() == STUB_PROVIDER:
            issues.append("LLM_PROVIDER=stub answers with canned load-test tokens; never use it for real visitors")
        elif not LLMConfig.ACTIVE_API_KEY() and not (
            LLMConfig.LLM_PROVIDER().strip().lower() == "openai" and LLMConfig.OPENAI_BASE_URL()
        ):
            issues.append(f"No API key set for LLM_PROVIDER={LLMConfig.LLM_PROVIDER()!r}")
        if ChatConfig.FALLBACK_MODE() not in {"deny", "handoff"}:
            issues.append("FALLBACK_MODE must be 'deny' or 'handoff'")
        if OCRConfig.INGESTION_WORKER() not in {"embedded", "external"}:
            issues.append("INGESTION_WORKER must be 'embedded' or 'external'")
        if AlertConfig.ALERT_CHANNEL() and AlertConfig.ALERT_CHANNEL() not in ALERT_CHANNELS:
            issues.append(f"ALERT_CHANNEL must be one of {', '.join(ALERT_CHANNELS)} (or empty)")
        if SmtpConfig.SMTP_SECURITY() not in SMTP_SECURITY_MODES:
            issues.append(f"SMTP_SECURITY must be one of {', '.join(SMTP_SECURITY_MODES)}")
        issues.extend(HostAuthConfig.problems())
        if ModelServerConfig.MODEL_SERVER_URL() and len(ModelServerConfig.MODEL_SERVER_TOKEN()) < MIN_JWT_SECRET_LENGTH:
            issues.append("MODEL_SERVER_URL is set but MODEL_SERVER_TOKEN is missing or short (the installer generates it)")
        return issues

    @staticmethod
    def validate() -> None:
        """
        Check the configuration at start-up.

        In production any problem is fatal; in development each one is logged
        as a warning so a local run still starts.

        Raises:
            RuntimeError: ``APP_ENV=production`` and :meth:`problems` is non-empty.
        """
        Path(PathConfig.LOG_DIR()).mkdir(parents=True, exist_ok=True)
        issues = Config.problems()
        if issues and ServerConfig.IS_PRODUCTION():
            raise RuntimeError("Refusing to start with an unsafe configuration: " + "; ".join(issues))
        for issue in issues:
            logger.warning("Configuration problem: %s", issue)
        if HostAuthConfig.HOST_AUTH_MODE() == "hs256":
            logger.warning(
                "HOST_AUTH_MODE=hs256: this server holds the secret that signs host tokens; "
                "switch to rs256 once the host backend can sign with RSA"
            )
