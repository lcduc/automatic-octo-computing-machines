"""
Centralized configuration for the RAG chatbot.

Every setting is read from the environment through one of the typed helpers
below. Each environment variable is defined in exactly one place; the grouped
classes (``File``, ``RAG``, …) are namespaced views over those definitions, so
there is no risk of two accessors disagreeing on a default.
"""

# Standard library imports
import logging
import os
from typing import List

# Third-party imports
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def env_str(name: str, default: str) -> str:
    """Read a string environment variable."""
    return os.getenv(name, default)


def env_int(name: str, default: int) -> int:
    """Read an integer environment variable, falling back on malformed input."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid integer for %s=%r; using default %s", name, raw, default)
        return default


def env_float(name: str, default: float) -> float:
    """Read a float environment variable, falling back on malformed input."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid float for %s=%r; using default %s", name, raw, default)
        return default


def env_bool(name: str, default: bool) -> bool:
    """Read a boolean environment variable (``true/1/yes/on`` are truthy)."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"true", "1", "yes", "on"}


def env_list(name: str, default: str) -> List[str]:
    """Read a comma-separated environment variable into a list."""
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


class DatabaseConfig:
    """Storage locations for chunks, vectors and logs."""

    @staticmethod
    def CHUNKS_DIR() -> str:
        """Directory holding extracted document chunks."""
        return env_str("CHUNKS_DIR", "data/chunks")

    @staticmethod
    def VECTORS_DIR() -> str:
        """Directory holding the vector store artifacts."""
        return env_str("VECTORS_DIR", "data/vectors")

    @staticmethod
    def TEMP_DIR() -> str:
        """Scratch directory for uploads and the persistent cache."""
        return env_str("TEMP_DIR", "data/temp")

    @staticmethod
    def VECTOR_STORE_PATH() -> str:
        """Base path for the vector store; the HDF5/FAISS names derive from it."""
        return env_str("VECTOR_STORE_PATH", "data/vectors/vector_store.pkl")

    @staticmethod
    def LOG_DIR() -> str:
        """Directory for rotating application logs."""
        return env_str("LOG_DIR", "data/logs")

    @staticmethod
    def MODELS_DIR() -> str:
        """
        Local cache directory for downloaded ML models.

        Kept inside the project root (rather than the user/OS-wide Hugging Face
        cache) so the weights baked into a deployment are visible and reviewable
        on disk, e.g. `docker exec ... ls /app/models`.
        """
        return env_str("MODELS_DIR", "models")


class LLMConfig:
    """OpenAI credentials, model selection and answer-cache tuning."""

    @staticmethod
    def OPENAI_API_KEY():
        """API key; ``None`` when unset so callers can degrade gracefully."""
        return os.getenv("OPENAI_API_KEY")

    @staticmethod
    def OPENAI_MODEL() -> str:
        """Chat completion model used for answer generation."""
        return env_str("OPENAI_MODEL", "gpt-4o-mini")

    @staticmethod
    def EMBEDDING_MODEL() -> str:
        """Sentence-transformers model used to embed chunks and queries."""
        return env_str("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")

    @staticmethod
    def MAX_CONTEXT_LENGTH() -> int:
        """Character budget for the retrieved context block."""
        return env_int("MAX_CONTEXT_LENGTH", 5000)

    @staticmethod
    def OPENAI_MAX_TOKENS() -> int:
        """Completion token cap per request."""
        return env_int("OPENAI_MAX_TOKENS", 4000)

    @staticmethod
    def OPENAI_TEMPERATURE() -> float:
        """Sampling temperature for answer generation."""
        return env_float("OPENAI_TEMPERATURE", 0.1)

    @staticmethod
    def OPENAI_TIMEOUT() -> int:
        """Per-request timeout in seconds."""
        return env_int("OPENAI_TIMEOUT", 30)

    @staticmethod
    def LLM_CACHE_TTL() -> int:
        """Lifetime of a cached answer, in seconds."""
        return env_int("LLM_CACHE_TTL", 3600)

    @staticmethod
    def LLM_CACHE_MAX_ENTRIES() -> int:
        """Maximum answers held by the in-process LLM cache."""
        return env_int("LLM_CACHE_MAX_ENTRIES", 1000)

    @staticmethod
    def LLM_CACHE_MAX_SIZE() -> int:
        """Maximum entries held by the smart (similarity-matching) cache."""
        return env_int("LLM_CACHE_MAX_SIZE", 100)

    @staticmethod
    def CHAT_BATCH_MAX_QUERIES() -> int:
        """
        Maximum queries accepted by one ``POST /chat/batch`` request.

        Batch items run concurrently on the event loop (bounded for GPU work by
        ``RETRIEVAL_MAX_CONCURRENCY``); this cap is a basic sanity/DoS limit on
        request size, not a performance tuning knob.
        """
        return env_int("CHAT_BATCH_MAX_QUERIES", 20)


class FileConfig:
    """Upload limits and chunking parameters."""

    @staticmethod
    def MAX_FILE_SIZE() -> int:
        """Largest accepted single upload, in bytes."""
        return env_int("MAX_FILE_SIZE", 52_428_800)

    @staticmethod
    def ALLOWED_EXTENSIONS() -> List[str]:
        """File extensions accepted by the upload endpoint."""
        return env_list("ALLOWED_EXTENSIONS", ".txt,.pdf,.docx,.doc,.csv,.xlsx,.xls")

    @staticmethod
    def MAX_FILES_PER_BATCH() -> int:
        """Maximum files accepted in one upload request."""
        return env_int("MAX_FILES_PER_BATCH", 10)

    @staticmethod
    def MAX_TOTAL_BATCH_SIZE() -> int:
        """Combined byte size limit across one upload batch."""
        return env_int("MAX_TOTAL_BATCH_SIZE", 209_715_200)

    @staticmethod
    def CHUNK_SIZE() -> int:
        """Target characters per document chunk."""
        return env_int("CHUNK_SIZE", 1000)

    @staticmethod
    def CHUNK_OVERLAP() -> int:
        """Characters shared between consecutive chunks."""
        return env_int("CHUNK_OVERLAP", 0)

    # Storage paths are owned by DatabaseConfig; these are namespaced aliases.
    TEMP_DIR = DatabaseConfig.TEMP_DIR
    CHUNKS_DIR = DatabaseConfig.CHUNKS_DIR
    VECTORS_DIR = DatabaseConfig.VECTORS_DIR
    VECTOR_STORE_PATH = DatabaseConfig.VECTOR_STORE_PATH


class ServerConfig:
    """HTTP server, CORS and rate-limiting settings."""

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
    def UVICORN_WORKERS() -> int:
        """Worker process count."""
        return env_int("UVICORN_WORKERS", 1)

    @staticmethod
    def CORS_ORIGINS() -> List[str]:
        """Allowed CORS origins; ``*`` permits any origin."""
        origins = os.getenv("CORS_ORIGINS", "*")
        return ["*"] if origins.strip() == "*" else env_list("CORS_ORIGINS", "*")

    @staticmethod
    def CORS_ALLOW_CREDENTIALS() -> bool:
        """Whether cross-origin credentials are accepted."""
        return env_bool("CORS_ALLOW_CREDENTIALS", True)

    @staticmethod
    def RATE_LIMIT_ENABLED() -> bool:
        """Enable the per-IP rate limiting middleware."""
        return env_bool("RATE_LIMIT_ENABLED", False)

    @staticmethod
    def RATE_LIMIT_MAX_REQUESTS() -> int:
        """Requests allowed per client IP inside the sliding window."""
        return env_int("RATE_LIMIT_MAX_REQUESTS", 100)

    @staticmethod
    def RATE_LIMIT_WINDOW_SECONDS() -> int:
        """Width of the rate limiting sliding window, in seconds."""
        return env_int("RATE_LIMIT_WINDOW_SECONDS", 60)

    @staticmethod
    def RATE_LIMIT_MAX_CONCURRENT() -> int:
        """Concurrent in-flight requests allowed per worker process."""
        return env_int("RATE_LIMIT_MAX_CONCURRENT", 10)

    @staticmethod
    def DESTRUCTIVE_CLEANUP_ENABLED() -> bool:
        """
        Allow ``POST /cleanup/`` to wipe chunks, vectors, temp files and logs.

        Off by default: this endpoint has no confirmation step and no
        authorization check of its own, so leaving it reachable is a standing
        "delete the whole knowledge base" button. Enable only for maintenance
        windows.
        """
        return env_bool("DESTRUCTIVE_CLEANUP_ENABLED", False)

    @staticmethod
    def API_KEY() -> str:
        """
        Optional shared-secret key required via the ``X-API-Key`` header.

        Empty (the default) disables the check entirely — appropriate when the
        service is only reachable on a private network/VPN. Set a value to
        require every request to present it.
        """
        return env_str("API_KEY", "")


class RAGConfig:
    """Retrieval, ranking and context-expansion behaviour."""

    @staticmethod
    def SIMILARITY_THRESHOLD() -> float:
        """Minimum fused score a chunk must reach to be considered."""
        return env_float("SIMILARITY_THRESHOLD", 0.7)

    @staticmethod
    def RERANKING_ENABLED() -> bool:
        """Run the cross-encoder reranker over retrieval candidates."""
        return env_bool("RERANKING_ENABLED", True)

    @staticmethod
    def QUERY_ADAPTER_PATH() -> str:
        """Path of the saved query adapter matrix (NumPy ``.npy``)."""
        return env_str("QUERY_ADAPTER_PATH", "data/vectors/query_adapter.npy")

    @staticmethod
    def RETRIEVAL_TOP_K() -> int:
        """Chunks returned by hybrid search before context expansion."""
        return env_int("RETRIEVAL_TOP_K", 3)

    @staticmethod
    def SEMANTIC_WEIGHT() -> float:
        """Weight of semantic similarity when fused with BM25 (0-1)."""
        return env_float("SEMANTIC_WEIGHT", 0.7)

    @staticmethod
    def MAX_CONTEXT_CHUNKS() -> int:
        """Hard cap on chunks included after context expansion."""
        return env_int("MAX_CONTEXT_CHUNKS", 5)

    @staticmethod
    def MIN_CONTEXT_CHUNKS() -> int:
        """Chunks padded in when retrieval returns too few results."""
        return env_int("MIN_CONTEXT_CHUNKS", 2)

    @staticmethod
    def RERANKER_MODEL() -> str:
        """
        Cross-encoder model used for reranking.

        Defaults to a multilingual model (not the common English-only
        ms-marco-MiniLM) because the corpus and queries are a mix of English
        and Vietnamese.
        """
        return env_str("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")

    @staticmethod
    def RETRIEVAL_MAX_CONCURRENCY() -> int:
        """
        Concurrent in-flight hybrid-search+rerank operations allowed per process.

        Embedding and cross-encoder inference are CPU/GPU-bound and run off the
        event loop in a worker thread; this bounds how many run at once so a
        burst of concurrent chat requests cannot exhaust a single GPU's memory
        (tuned for a 12GB card by default). Raise it if running CPU-only or on a
        larger GPU.
        """
        return env_int("RETRIEVAL_MAX_CONCURRENCY", 4)

    @staticmethod
    def CONTEXT_EXPANSION_ENABLED() -> bool:
        """Include chunks adjacent to each hit from the same source document."""
        return env_bool("CONTEXT_EXPANSION_ENABLED", True)

    @staticmethod
    def CONTEXT_EXPANSION_RADIUS() -> int:
        """Neighbour chunks pulled in on each side of a hit."""
        return env_int("CONTEXT_EXPANSION_RADIUS", 1)

    @staticmethod
    def USE_FAISS_INDEX() -> bool:
        """Use the FAISS index for semantic search when one is available."""
        return env_bool("USE_FAISS_INDEX", True)

    @staticmethod
    def VIETNAMESE_PREPROCESSING_ENABLED() -> bool:
        """Apply Vietnamese-specific query preprocessing."""
        return env_bool("VIETNAMESE_PREPROCESSING_ENABLED", True)

    @staticmethod
    def CLEAN_SPECIAL_CHARS() -> bool:
        """Strip special characters during preprocessing."""
        return env_bool("CLEAN_SPECIAL_CHARS", True)

    @staticmethod
    def EXTRACT_CONTENT_WORDS() -> bool:
        """Keep only content words during preprocessing."""
        return env_bool("EXTRACT_CONTENT_WORDS", True)

    # The embedding model is owned by LLMConfig; this is a namespaced alias.
    EMBEDDING_MODEL = LLMConfig.EMBEDDING_MODEL


class ChatConfig:
    """Conversation mode settings."""

    @staticmethod
    def CHAT_MODE() -> str:
        """``query_only`` or ``with_history``."""
        return env_str("CHAT_MODE", "with_history")

    @staticmethod
    def ENABLE_HISTORY() -> bool:
        """Whether conversation history is replayed into the prompt."""
        return ChatConfig.CHAT_MODE().strip().lower() == "with_history"

    @staticmethod
    def MAX_HISTORY_TURNS() -> int:
        """
        Maximum prior question/answer pairs replayed into the prompt.

        History is supplied by the caller on each request (no server-side
        session store); this is a server-side cap applied regardless of what
        the caller sends, so a misbehaving client cannot blow the context
        budget. One turn = one user message + one assistant reply, so the
        default of 10 turns means up to 20 prior messages are replayed.
        """
        return env_int("MAX_HISTORY_TURNS", 10)


class OCRConfig:
    """
    OCR settings for scanned/image-only documents.

    Three engines are available (see ``core/document_processing/ocr``):
    PP-OCRv6 (local, CPU), PaddleOCR-VL (local, GPU) and Datalab's hosted
    Surya OCR (online). Both local engines are multilingual and need no
    per-language configuration; ``OCR_PROVIDER`` picks between local
    (GPU/CPU auto-detected) and the online engine.
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
        """PDF files OCR'd in parallel across the process."""
        return env_int("OCR_MAX_CONCURRENT_FILES", 1)

    @staticmethod
    def OCR_PROVIDER() -> str:
        """
        Which OCR engine to use: ``auto`` (local, GPU/CPU auto-detected) or
        ``datalab`` (online, via Datalab's Surya OCR API — requires
        ``DATALAB_API_KEY``). Falls back to ``auto`` if ``datalab`` is
        selected without a key configured.
        """
        return env_str("OCR_PROVIDER", "auto")

    @staticmethod
    def DATALAB_API_KEY() -> str:
        """API key for Datalab's hosted Surya OCR (https://www.datalab.to)."""
        return env_str("DATALAB_API_KEY", "")


class LoggingConfig:
    """Log level, destination and rotation policy."""

    @staticmethod
    def LOG_LEVEL() -> str:
        """Root logger level name."""
        return env_str("LOG_LEVEL", "INFO")

    @staticmethod
    def LOG_TO_FILE() -> bool:
        """Write logs to a rotating file in addition to stderr."""
        return env_bool("LOG_TO_FILE", True)

    @staticmethod
    def LOG_MAX_SIZE() -> int:
        """Size at which a log file is rotated, in bytes."""
        return env_int("LOG_MAX_SIZE", 10_485_760)

    @staticmethod
    def LOG_BACKUP_COUNT() -> int:
        """Rotated log files retained on disk."""
        return env_int("LOG_BACKUP_COUNT", 5)

    @staticmethod
    def REQUEST_LOGGING_ENABLED() -> bool:
        """Log one line per HTTP request with its duration."""
        return env_bool("REQUEST_LOGGING_ENABLED", True)

    LOG_DIR = DatabaseConfig.LOG_DIR


class URLConfig:
    """Web crawling limits."""

    @staticmethod
    def CRAWL_TIMEOUT() -> int:
        """Per-URL fetch timeout, in seconds."""
        return env_int("CRAWL_TIMEOUT", 30)

    @staticmethod
    def CRAWL_MAX_PAGES() -> int:
        """Maximum pages fetched per crawl."""
        return env_int("CRAWL_MAX_PAGES", 50)

    @staticmethod
    def CRAWL_MAX_CONTENT_LENGTH() -> int:
        """Largest accepted page body, in bytes."""
        return env_int("CRAWL_MAX_CONTENT_LENGTH", 10_485_760)


class ConfidenceConfig:
    """Weights of the answer-confidence signals (should sum to 1.0)."""

    @staticmethod
    def CONFIDENCE_SCORING_ENABLED() -> bool:
        """Compute confidence scores for generated answers."""
        return env_bool("CONFIDENCE_SCORING_ENABLED", True)

    @staticmethod
    def CONFIDENCE_CONTEXT_WEIGHT() -> float:
        """Weight of context alignment."""
        return env_float("CONFIDENCE_CONTEXT_WEIGHT", 0.35)

    @staticmethod
    def CONFIDENCE_LENGTH_WEIGHT() -> float:
        """Weight of response-length appropriateness."""
        return env_float("CONFIDENCE_LENGTH_WEIGHT", 0.20)

    @staticmethod
    def CONFIDENCE_COHERENCE_WEIGHT() -> float:
        """Weight of semantic coherence."""
        return env_float("CONFIDENCE_COHERENCE_WEIGHT", 0.25)

    @staticmethod
    def CONFIDENCE_CITATION_WEIGHT() -> float:
        """Weight of source citation."""
        return env_float("CONFIDENCE_CITATION_WEIGHT", 0.10)

    @staticmethod
    def CONFIDENCE_UNCERTAINTY_WEIGHT() -> float:
        """Weight of uncertainty-marker detection."""
        return env_float("CONFIDENCE_UNCERTAINTY_WEIGHT", 0.10)


class HealthConfig:
    """Thresholds used to classify overall service health."""

    @staticmethod
    def SERVICE_SUCCESS_RATE_THRESHOLD() -> float:
        """Success-rate percentage below which the service is 'degraded'."""
        return env_float("SERVICE_SUCCESS_RATE_THRESHOLD", 80.0)

    @staticmethod
    def SERVICE_MIN_REQUESTS_FOR_HEALTH() -> int:
        """Requests required before the success rate is meaningful."""
        return env_int("SERVICE_MIN_REQUESTS_FOR_HEALTH", 10)


class AuditConfig:
    """Durable per-turn chat audit trail (query, response, confidence, sources)."""

    @staticmethod
    def ENABLED() -> bool:
        """Record one audit entry per answered chat turn."""
        return env_bool("AUDIT_TRAIL_ENABLED", True)

    @staticmethod
    def LOG_PATH() -> str:
        """JSON-Lines file the audit trail is appended to."""
        return env_str("AUDIT_TRAIL_PATH", os.path.join(DatabaseConfig.LOG_DIR(), "audit_trail.jsonl"))


class Config:
    """Namespaced access point for every configuration group."""

    Database = DatabaseConfig
    LLM = LLMConfig
    File = FileConfig
    Server = ServerConfig
    RAG = RAGConfig
    Chat = ChatConfig
    OCR = OCRConfig
    Logging = LoggingConfig
    URL = URLConfig
    Confidence = ConfidenceConfig
    Health = HealthConfig
    Audit = AuditConfig

    @staticmethod
    def validate() -> bool:
        """
        Validate critical settings and create the directories the app writes to.

        Returns:
            True when an OpenAI API key is present, False otherwise. Directories
            are created either way so ingestion still works without a key.
        """
        from utils.file_operations.file_manager import FileManager

        directories = [
            DatabaseConfig.CHUNKS_DIR(),
            DatabaseConfig.VECTORS_DIR(),
            DatabaseConfig.TEMP_DIR(),
            os.path.dirname(DatabaseConfig.VECTOR_STORE_PATH()),
        ]
        for directory in directories:
            if directory:
                FileManager.ensure_directory_exists(directory)

        if not LLMConfig.OPENAI_API_KEY():
            logger.warning("OPENAI_API_KEY is not set; chat functionality will not work.")
            return False
        return True
