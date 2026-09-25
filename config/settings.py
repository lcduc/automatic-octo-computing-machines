"""
Centralized configuration for the RAG chatbot.

Every setting is read from the environment through the typed helpers in
:mod:`config.env`. Each environment variable is defined in exactly one place;
the grouped classes (``LLM``, ``RAG``, …) are namespaced views over those
definitions, collected under :class:`Config`. Platform settings (database,
server, security, chat policy) live in :mod:`config.platform_settings`.
"""

# Standard library imports
import logging
import os
from pathlib import Path
from typing import List, Optional

# Third-party imports
from dotenv import load_dotenv

# Local imports
from .env import env_bool, env_float, env_int, env_list, env_str
from .platform_settings import ChatConfig, DatabaseConfig, SecurityConfig, ServerConfig

load_dotenv()

logger = logging.getLogger(__name__)

#: Shortest admin JWT secret accepted in production (bytes of entropy ≈ chars/2 for hex).
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


class LLMConfig:
    """LLM provider selection, credentials, model selection and answer-cache tuning."""

    @staticmethod
    def LLM_PROVIDER() -> str:
        """Which chat-completion backend to use: ``openai``, ``anthropic`` or ``gemini``."""
        return env_str("LLM_PROVIDER", "openai")

    @staticmethod
    def ACTIVE_MODEL() -> str:
        """Main answer-generation model for whichever provider is active."""
        provider = LLMConfig.LLM_PROVIDER().strip().lower()
        if provider == "anthropic":
            return LLMConfig.ANTHROPIC_MODEL()
        if provider == "gemini":
            return LLMConfig.GEMINI_MODEL()
        return LLMConfig.OPENAI_MODEL()

    @staticmethod
    def ACTIVE_LIGHT_MODEL() -> str:
        """Cheap/fast model (query rewriting, intent classification) for the active provider."""
        provider = LLMConfig.LLM_PROVIDER().strip().lower()
        if provider == "anthropic":
            return LLMConfig.ANTHROPIC_LIGHT_MODEL()
        if provider == "gemini":
            return LLMConfig.GEMINI_LIGHT_MODEL()
        return LLMConfig.OPENAI_LIGHT_MODEL()

    @staticmethod
    def ACTIVE_API_KEY() -> Optional[str]:
        """API key for whichever provider ``LLM_PROVIDER`` selects."""
        provider = LLMConfig.LLM_PROVIDER().strip().lower()
        if provider == "anthropic":
            return LLMConfig.ANTHROPIC_API_KEY()
        if provider == "gemini":
            return LLMConfig.GEMINI_API_KEY()
        return LLMConfig.OPENAI_API_KEY()

    @staticmethod
    def OPENAI_API_KEY() -> Optional[str]:
        """API key; ``None`` when unset so callers can degrade gracefully."""
        return os.getenv("OPENAI_API_KEY") or None

    @staticmethod
    def OPENAI_MODEL() -> str:
        """Chat completion model used for answer generation."""
        return env_str("OPENAI_MODEL", "gpt-5-mini")

    @staticmethod
    def OPENAI_LIGHT_MODEL() -> str:
        """Cheaper model for lightweight judgment calls (query rewriting, intent classification)."""
        return env_str("OPENAI_LIGHT_MODEL", "gpt-4.1-nano")

    @staticmethod
    def TOOL_CALLING_ENABLED() -> bool:
        """
        Route chat turns through ``IntentRouter``/``ToolCallingAgent``.

        Every turn otherwise pays for an extra intent-classification call, so
        this can disable the action engine without a redeploy.
        """
        return env_bool("TOOL_CALLING_ENABLED", False)

    @staticmethod
    def EMBEDDING_MODEL() -> str:
        """Sentence-transformers model used to embed chunks and queries."""
        return env_str("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")

    @staticmethod
    def MAX_CONTEXT_LENGTH() -> int:
        """Character budget for the retrieved context block."""
        return env_int("MAX_CONTEXT_LENGTH", 6000)

    @staticmethod
    def OPENAI_MAX_TOKENS() -> int:
        """Completion token cap per request."""
        return env_int("OPENAI_MAX_TOKENS", 4000)

    @staticmethod
    def OPENAI_TEMPERATURE() -> float:
        """
        Sampling temperature for answer generation.

        Ignored for ``gpt-5*`` models, which only support the default
        temperature of 1 - see ``OpenAIClientProvider._completion_kwargs``.
        """
        return env_float("OPENAI_TEMPERATURE", 0.1)

    @staticmethod
    def OPENAI_REASONING_EFFORT() -> str:
        """
        Reasoning depth for ``gpt-5*`` models.

        Which values are accepted is model-dependent and enforced server-side
        (``gpt-5-mini`` accepts ``minimal``/``low``/``medium``/``high``).
        Ignored for non-reasoning models - see
        ``OpenAIClientProvider._completion_kwargs``.
        """
        return env_str("OPENAI_REASONING_EFFORT", "low")

    @staticmethod
    def OPENAI_TIMEOUT() -> int:
        """Per-request timeout in seconds."""
        return env_int("OPENAI_TIMEOUT", 30)

    @staticmethod
    def TRANSCRIPTION_MODEL() -> str:
        """Speech-to-text model used to transcribe voice queries."""
        return env_str("TRANSCRIPTION_MODEL", "gpt-transcribe")

    @staticmethod
    def TRANSCRIPTION_LANGUAGE() -> str:
        """ISO-639-1 language hint for voice queries; empty lets the model auto-detect."""
        return env_str("TRANSCRIPTION_LANGUAGE", "vi")

    @staticmethod
    def ANTHROPIC_API_KEY() -> Optional[str]:
        """API key; ``None`` when unset so callers can degrade gracefully."""
        return os.getenv("ANTHROPIC_API_KEY") or None

    @staticmethod
    def ANTHROPIC_MODEL() -> str:
        """Chat completion model used for answer generation."""
        return env_str("ANTHROPIC_MODEL", "claude-sonnet-5")

    @staticmethod
    def ANTHROPIC_LIGHT_MODEL() -> str:
        """Cheaper model for lightweight judgment calls."""
        return env_str("ANTHROPIC_LIGHT_MODEL", "claude-haiku-4-5")

    @staticmethod
    def ANTHROPIC_MAX_TOKENS() -> int:
        """Completion token cap per request."""
        return env_int("ANTHROPIC_MAX_TOKENS", 4000)

    @staticmethod
    def ANTHROPIC_TIMEOUT() -> int:
        """Per-request timeout in seconds."""
        return env_int("ANTHROPIC_TIMEOUT", 30)

    @staticmethod
    def GEMINI_API_KEY() -> Optional[str]:
        """API key; ``None`` when unset so callers can degrade gracefully."""
        return os.getenv("GEMINI_API_KEY") or None

    @staticmethod
    def GEMINI_MODEL() -> str:
        """Chat completion model used for answer generation."""
        return env_str("GEMINI_MODEL", "gemini-3.6-flash")

    @staticmethod
    def GEMINI_LIGHT_MODEL() -> str:
        """Cheaper model for lightweight judgment calls."""
        return env_str("GEMINI_LIGHT_MODEL", "gemini-3.5-flash-lite")

    @staticmethod
    def GEMINI_MAX_TOKENS() -> int:
        """Completion token cap per request."""
        return env_int("GEMINI_MAX_TOKENS", 4000)

    @staticmethod
    def GEMINI_TIMEOUT() -> int:
        """Per-request timeout in seconds."""
        return env_int("GEMINI_TIMEOUT", 30)

    @staticmethod
    def LLM_CACHE_TTL() -> int:
        """Lifetime of a cached answer, in seconds."""
        return env_int("LLM_CACHE_TTL", 3600)

    @staticmethod
    def LLM_CACHE_MAX_ENTRIES() -> int:
        """Maximum answers held by the in-process LLM cache."""
        return env_int("LLM_CACHE_MAX_ENTRIES", 1000)

    @staticmethod
    def TURN_TIMEOUT_SECONDS() -> int:
        """Hard deadline for one whole chat turn (retrieval + all LLM calls)."""
        return env_int("TURN_TIMEOUT_SECONDS", 90)


class FileConfig:
    """Upload limits and chunking parameters."""

    @staticmethod
    def MAX_FILE_SIZE() -> int:
        """Largest accepted single upload, in bytes."""
        return env_int("MAX_FILE_SIZE", 52_428_800)

    @staticmethod
    def ALLOWED_EXTENSIONS() -> List[str]:
        """
        File extensions accepted by the knowledge upload endpoint.

        The legacy Office binary formats ``.doc`` and ``.xls`` are deliberately
        absent. Save such files as ``.docx``/``.xlsx`` before uploading.
        """
        return env_list("ALLOWED_EXTENSIONS", ".txt,.md,.pdf,.docx,.csv,.xlsx")

    @staticmethod
    def MAX_AUDIO_FILE_SIZE() -> int:
        """Largest accepted voice-query recording, in bytes (OpenAI's own cap is 25MB)."""
        return env_int("MAX_AUDIO_FILE_SIZE", 26_214_400)

    @staticmethod
    def CHUNK_SIZE() -> int:
        """Target characters per document chunk."""
        return env_int("CHUNK_SIZE", 1000)

    @staticmethod
    def CHUNK_OVERLAP() -> int:
        """Characters shared between consecutive chunks."""
        return env_int("CHUNK_OVERLAP", 0)


class RAGConfig:
    """Retrieval, ranking and context-expansion behaviour."""

    @staticmethod
    def SIMILARITY_THRESHOLD() -> float:
        """
        Minimum relevance a chunk needs to count as a match.

        Applied to the reranker score when reranking is on, otherwise to the
        fused hybrid score. A turn with no chunk above it takes the fallback
        path (deny / hand off) without calling the LLM.
        """
        return env_float("SIMILARITY_THRESHOLD", 0.3)

    @staticmethod
    def RERANKING_ENABLED() -> bool:
        """Run the cross-encoder reranker over retrieval candidates."""
        return env_bool("RERANKING_ENABLED", True)

    @staticmethod
    def QUERY_ADAPTER_PATH() -> str:
        """Path of the saved query adapter matrix (NumPy ``.npy``); optional."""
        return env_str("QUERY_ADAPTER_PATH", "data/query_adapter.npy")

    @staticmethod
    def RETRIEVAL_TOP_K() -> int:
        """Chunks returned by hybrid search before context expansion."""
        return env_int("RETRIEVAL_TOP_K", 4)

    @staticmethod
    def SEMANTIC_WEIGHT() -> float:
        """Weight of semantic similarity when fused with BM25 (0-1)."""
        return env_float("SEMANTIC_WEIGHT", 0.7)

    @staticmethod
    def MAX_CONTEXT_CHUNKS() -> int:
        """Hard cap on chunks included after context expansion."""
        return env_int("MAX_CONTEXT_CHUNKS", 6)

    @staticmethod
    def CONTEXT_EXPANSION_RADIUS() -> int:
        """Neighbour chunks of the same document pulled in on each side of a hit (0 disables)."""
        return env_int("CONTEXT_EXPANSION_RADIUS", 1)

    @staticmethod
    def RERANKER_MODEL() -> str:
        """
        Cross-encoder model used for reranking.

        Defaults to a multilingual model because the corpus and queries are a
        mix of English and Vietnamese.
        """
        return env_str("RERANKER_MODEL", "jinaai/jina-reranker-v2-base-multilingual")

    @staticmethod
    def RETRIEVAL_MAX_CONCURRENCY() -> int:
        """
        Concurrent hybrid-search+rerank operations allowed per process.

        Embedding and cross-encoder inference are GPU-bound and run in a worker
        thread; this bounds how many run at once so a burst of chats cannot
        exhaust the GPU's memory (tuned for a 12GB card by default).
        """
        return env_int("RETRIEVAL_MAX_CONCURRENCY", 4)

    EMBEDDING_MODEL = LLMConfig.EMBEDDING_MODEL


class OCRConfig:
    """
    OCR settings for scanned/image-only documents.

    See ``core/document_processing/engine_selector.py`` for the engines:
    PP-OCRv6 (local CPU), PaddleOCR-VL (local GPU), Datalab Surya (online).
    """

    @staticmethod
    def DOCLING_OCR_ENABLED() -> bool:
        """Run OCR at all for PDFs with no extractable text layer."""
        return env_bool("DOCLING_OCR_ENABLED", False)

    @staticmethod
    def OCR_FORCE_ALL_PDFS() -> bool:
        """OCR every PDF, even those with an extractable text layer."""
        return env_bool("OCR_FORCE_ALL_PDFS", False)

    @staticmethod
    def OCR_CONCURRENT_PAGES() -> int:
        """Pages OCR'd in parallel within a single document."""
        return env_int("OCR_CONCURRENT_PAGES", 2)

    @staticmethod
    def OCR_MAX_CONCURRENT_FILES() -> int:
        """Files processed (parsed/OCR'd) in parallel across the process."""
        return env_int("OCR_MAX_CONCURRENT_FILES", 1)

    @staticmethod
    def OCR_PROVIDER() -> str:
        """``auto`` (local, GPU/CPU auto-detected) or ``datalab`` (needs ``DATALAB_API_KEY``)."""
        return env_str("OCR_PROVIDER", "auto")

    @staticmethod
    def DATALAB_API_KEY() -> str:
        """API key for Datalab's hosted Surya OCR (https://www.datalab.to)."""
        return env_str("DATALAB_API_KEY", "")


class LoggingConfig:
    """Log level and destination."""

    @staticmethod
    def LOG_LEVEL() -> str:
        """Root logger level name."""
        return env_str("LOG_LEVEL", "INFO")

    LOG_DIR = PathConfig.LOG_DIR


class HealthConfig:
    """Thresholds used by the live performance monitor."""

    @staticmethod
    def SLOW_REQUEST_THRESHOLD_MS() -> float:
        """Single-request latency above which a warning is logged immediately."""
        return env_float("SLOW_REQUEST_THRESHOLD_MS", 8000.0)


class Config:
    """Namespaced access point for every configuration group."""

    Paths = PathConfig
    Database = DatabaseConfig
    LLM = LLMConfig
    File = FileConfig
    Server = ServerConfig
    Security = SecurityConfig
    RAG = RAGConfig
    Chat = ChatConfig
    OCR = OCRConfig
    Logging = LoggingConfig
    Health = HealthConfig

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
        if not DatabaseConfig.POSTGRES_PASSWORD() and not os.getenv("DATABASE_URL"):
            issues.append("POSTGRES_PASSWORD is empty")
        if "*" in SecurityConfig.CORS_ORIGINS():
            issues.append("CORS_ORIGINS must list explicit origins, not '*'")
        if not LLMConfig.ACTIVE_API_KEY():
            issues.append(f"No API key set for LLM_PROVIDER={LLMConfig.LLM_PROVIDER()!r}")
        if ChatConfig.FALLBACK_MODE() not in {"deny", "handoff"}:
            issues.append("FALLBACK_MODE must be 'deny' or 'handoff'")
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
