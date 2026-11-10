"""
Knowledge settings: upload limits and chunking, retrieval and ranking, OCR, and the embedding router.

Read through :class:`app.config.settings.Config` (``Config.File``, ``Config.RAG``, ``Config.OCR``,
``Config.Routing``).
"""

# Standard library imports
from typing import List

# Local imports
from .env import env_bool, env_float, env_int, env_list, env_str
from .llm_settings import LLMConfig


class FileConfig:
    """Upload limits and chunking parameters."""

    @staticmethod
    def MAX_FILE_SIZE() -> int:
        """Largest accepted single upload, in bytes."""
        return env_int("MAX_FILE_SIZE", 52_428_800)

    @staticmethod
    def MAX_PDF_PAGES() -> int:
        """
        Most pages accepted in one uploaded PDF. A long scan occupies the single
        ingestion worker for a long time (OCR costs seconds per page), so it is
        refused up front instead.
        """
        return env_int("MAX_PDF_PAGES", 300)

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
        Minimum reranker score a chunk needs to count as a match: a floor, not the answerability test.

        A turn with no chunk above it takes the fallback path (deny / hand
        off) without calling the LLM. Without reranker scores (reranking off
        or failed) ``SEMANTIC_THRESHOLD`` gates instead. Whether the documents
        actually answer is decided by the model (the ``[NO_ANSWER]`` marker), because
        scores of answerable and on-topic-unanswerable questions overlap.

        0.03 (2026-10-01, ``bge-reranker-v2-m3``): calibrated on ``golden_colloquial_dev.json``
        (best 0.032, between the highest off-topic score 0.022 and the lowest answerable 0.042) and
        checked on ``golden_colloquial_holdout.json``. The earlier 0.3 came from questions that
        restate an FAQ title and refused real, colloquial questions that scored 0.01 to 0.2.
        Re-run ``python -m scripts.eval.rag`` on both sets after any model or document change.
        """
        return env_float("SIMILARITY_THRESHOLD", 0.03)

    @staticmethod
    def SEMANTIC_THRESHOLD() -> float:
        """
        Minimum cosine similarity a chunk needs when no reranker scored it.

        Cosine scores sit on a model-specific scale (E5 puts nearly every pair
        in 0.7-1.0), so this is calibrated per ``EMBEDDING_MODEL``, separately
        from the reranker's ``SIMILARITY_THRESHOLD``.
        """
        return env_float("SEMANTIC_THRESHOLD", 0.85)

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
        """Neighbour chunks of the same document pulled in on each side of the best hit (0 disables)."""
        return env_int("CONTEXT_EXPANSION_RADIUS", 1)

    @staticmethod
    def RERANKER_MODEL() -> str:
        """
        Cross-encoder model used for reranking.

        Defaults to a multilingual model because the corpus and queries are a
        mix of English and Vietnamese; Apache-2.0 and no remote code (the
        earlier Jina v2 default is CC-BY-NC, not usable commercially).
        """
        return env_str("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")

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
    def OCR_MAX_IMAGE_SIDE() -> int:
        """
        Longest side, in pixels, of a page image sent to OCR. Visual tokens (and so
        GPU activation memory) grow with resolution, so oversized pages are scaled down.
        """
        return max(256, env_int("OCR_MAX_IMAGE_SIDE", 2048))

    @staticmethod
    def OCR_MAX_CONCURRENT_FILES() -> int:
        """Files processed (parsed/OCR'd) in parallel across the process."""
        return env_int("OCR_MAX_CONCURRENT_FILES", 1)

    @staticmethod
    def OCR_CPU_THREADS() -> int:
        """
        CPU threads local parsing may use (Docling layout models, PP-OCRv6),
        split across ``OCR_CONCURRENT_PAGES``; keeps the rest free for the API.
        """
        return max(1, env_int("OCR_CPU_THREADS", 2))

    @staticmethod
    def INGESTION_WORKER() -> str:
        """
        Where uploads are parsed: ``embedded`` (inside the API process, for local
        runs) or ``external`` (a separate ``worker.py`` process/container).
        """
        return env_str("INGESTION_WORKER", "embedded").lower()

    @staticmethod
    def OCR_PROVIDER() -> str:
        """``auto`` (local, GPU/CPU auto-detected) or ``datalab`` (needs ``DATALAB_API_KEY``)."""
        return env_str("OCR_PROVIDER", "auto")

    @staticmethod
    def DATALAB_API_KEY() -> str:
        """API key for Datalab's hosted Surya OCR (https://www.datalab.to)."""
        return env_str("DATALAB_API_KEY", "")


class RoutingConfig:
    """Embedding router: how confident a message must look like a route before it skips retrieval."""

    @staticmethod
    def ROUTE_THRESHOLD(route: str, default: float) -> float:
        """
        Minimum cosine similarity to a route's examples (``ROUTE_<NAME>_THRESHOLD``).

        Cosine scores sit on the embedding model's scale (E5: nearly every pair in 0.7-1.0), so
        the defaults in ``EmbeddingRouter`` are calibrated per ``EMBEDDING_MODEL`` with
        ``python -m scripts.eval.router``.
        """
        return env_float(f"ROUTE_{route.upper()}_THRESHOLD", default)

    @staticmethod
    def ROUTE_MARGIN() -> float:
        """How far the best route must lead the runner-up for the router to act on it."""
        return env_float("ROUTE_MARGIN", 0.01)

    @staticmethod
    def OFF_TOPIC_LEAD() -> float:
        """
        How much closer to the off-topic examples than to the on-topic ones a message must be for
        an empty retrieval to refuse it as off topic instead of handing it to staff.
        """
        return env_float("ROUTE_OFF_TOPIC_LEAD", 0.02)

    @staticmethod
    def OFF_TOPIC_MAX_RERANK() -> float:
        """
        Best reranker score below which a message that found nothing is "unrelated to everything we know".

        Off-topic messages score at most about 0.0006 against the demo knowledge base (some 0.004 to 0.02),
        on-topic ones the base cannot answer at least 0.0027; this sits in the gap.
        """
        return env_float("ROUTE_OFF_TOPIC_MAX_RERANK", 0.001)

    @staticmethod
    def OFF_TOPIC_MIN_LEAD() -> float:
        """A message clearly closer to the on-topic examples (lead below this) is never refused as off topic."""
        return env_float("ROUTE_OFF_TOPIC_MIN_LEAD", -0.02)
