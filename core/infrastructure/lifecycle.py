"""
Application start-up and shutdown orchestration.

Keeps ``main.py`` limited to wiring: everything that has to happen before the
first request (model preloading, warm-ups, background workers) and on the way
out lives here.
"""

# Standard library imports
import logging
import os

# Third-party imports
import httpx

# Local imports
from config.settings import Config

logger = logging.getLogger(__name__)


class ApplicationLifecycle:
    """
    Runs the ordered start-up and shutdown steps for the API process.

    Every step is best-effort: a warm-up failure is logged and the server still
    starts, because a cold model is slower but not broken.
    """

    #: Debian/Ubuntu CA bundle used for the outbound reachability probe.
    LINUX_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"
    #: Seconds allowed for the outbound OpenAI reachability probe.
    PROBE_TIMEOUT_SECONDS = 5
    #: Inbound-TLS variables that must not leak into outbound trust resolution.
    INBOUND_TLS_ENV_VARS = ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")

    async def startup(self) -> None:
        """Preload models, warm caches and start background workers."""
        self._check_worker_count()
        await self._preload_models()
        await self._start_background_tasks()
        self._warm_embeddings()
        self._warm_vector_store()
        self._probe_openai()
        logger.info("Chatbot started successfully")

    def _check_worker_count(self) -> None:
        """
        Warn if configured for multiple Uvicorn workers.

        Each worker process loads its own copy of the embedding and reranker
        models onto the GPU; on a single GPU this multiplies memory use and
        can exhaust it. This only warns — it doesn't change behaviour — because
        a CPU-only deployment can safely use more workers.
        """
        workers = Config.Server.UVICORN_WORKERS()
        if workers > 1:
            logger.warning(
                "UVICORN_WORKERS=%d: each worker loads its own copy of the "
                "embedding + reranker models. On a single GPU this can exhaust "
                "its memory. Prefer 1 worker and let RETRIEVAL_MAX_CONCURRENCY "
                "(currently %d) bound concurrent GPU use instead.",
                workers,
                Config.RAG.RETRIEVAL_MAX_CONCURRENCY(),
            )

    async def shutdown(self) -> None:
        """Stop background workers and release pooled resources."""
        await self._stop_background_tasks()
        self._persist_cache()
        self._close_services()
        logger.info("Chatbot shutdown complete")

    # ------------------------------------------------------------------
    # Start-up steps
    # ------------------------------------------------------------------

    async def _preload_models(self) -> None:
        """Load embedding, reranker and vector store into memory."""
        try:
            from utils.model_preloader import preload_all_models

            logger.info("Preloading all ML models...")
            await preload_all_models()
            logger.info("All models preloaded successfully")
        except Exception:
            logger.exception("Model preloading failed; first request will be slower")

    async def _start_background_tasks(self) -> None:
        """Start the periodic metrics/cleanup workers."""
        try:
            from utils.background_tasks import start_background_tasks

            await start_background_tasks()
            logger.info("Background tasks started")
        except Exception:
            logger.exception("Background tasks failed to start")

    def _warm_embeddings(self) -> None:
        """Run a tiny encode so the model's execution graph is initialized."""
        try:
            from core.retrieval.embeddings import get_embedding_service

            embedder = get_embedding_service().get_embedder()
            embedder.encode(["warmup"], convert_to_numpy=True, show_progress_bar=False)
            logger.info("Embedding model warmed up")
        except Exception:
            logger.exception("Embedding warm-up skipped")

    def _warm_vector_store(self) -> None:
        """Ensure the shared vector store payload is resident before traffic."""
        try:
            from core.storage import get_vector_store_provider

            if get_vector_store_provider().get_data() is not None:
                logger.info("Vector store loaded successfully")
            else:
                logger.warning("Vector store unavailable at start-up")
        except Exception:
            logger.exception("Vector store warm-up skipped")

    def _probe_openai(self) -> None:
        """
        Verify outbound reachability of the OpenAI API.

        Any 2xx-4xx status means the network path and TLS handshake work; only
        connection-level failures are worth warning about.
        """
        try:
            # A self-signed inbound server certificate must not override the
            # trust store used for outbound calls.
            for variable in self.INBOUND_TLS_ENV_VARS:
                os.environ.pop(variable, None)

            api_key = Config.LLM.OPENAI_API_KEY()
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            verify = self.LINUX_CA_BUNDLE if os.path.exists(self.LINUX_CA_BUNDLE) else True

            with httpx.Client(timeout=self.PROBE_TIMEOUT_SECONDS, verify=verify) as client:
                response = client.get("https://api.openai.com/v1/models", headers=headers)

            if 200 <= response.status_code < 500:
                logger.info("OpenAI reachable (status %s)", response.status_code)
            else:
                logger.warning(
                    "OpenAI returned unexpected status %s during warm-up",
                    response.status_code,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            logger.warning(
                "OpenAI warm-up network issue (%s); continuing without blocking",
                type(exc).__name__,
            )
        except Exception:
            logger.exception("OpenAI warm-up failed (non-fatal)")

    # ------------------------------------------------------------------
    # Shutdown steps
    # ------------------------------------------------------------------

    async def _stop_background_tasks(self) -> None:
        """Stop the periodic workers started during start-up."""
        try:
            from utils.background_tasks import stop_background_tasks

            await stop_background_tasks()
            logger.info("Background tasks stopped")
        except Exception:
            logger.exception("Error stopping background tasks")

    def _persist_cache(self) -> None:
        """Flush the smart cache to disk so warm answers survive a restart."""
        try:
            from core.infrastructure.cache_service import get_cache_service

            get_cache_service().cleanup_on_shutdown()
        except Exception:
            logger.exception("Error persisting cache on shutdown")

    def _close_services(self) -> None:
        """Close pooled HTTP clients owned by the shared services."""
        try:
            from api.dependencies import get_service_container

            get_service_container().shutdown()
        except Exception:
            logger.exception("Error closing shared services")


class StartupBanner:
    """Renders the human-readable start-up summary printed to the console."""

    def __init__(self, protocol: str, display_host: str, workers: int):
        """
        Args:
            protocol: ``http`` or ``https`` depending on the TLS configuration.
            display_host: Host shown to the operator (``0.0.0.0`` → ``localhost``).
            workers: Number of Uvicorn workers in this deployment.
        """
        self._protocol = protocol
        self._display_host = display_host
        self._workers = workers

    def render(self) -> str:
        """Build the banner text."""
        base_url = f"{self._protocol}://{self._display_host}:{Config.Server.PORT()}"
        separator = "=" * 60
        lines = [
            separator,
            "Chatbot",
            separator,
            f"Server:          {base_url}",
            f"Health Check:    {base_url}/",
            f"API Docs:        {base_url}/docs",
            f"OpenAI Model:    {Config.LLM.OPENAI_MODEL()}",
            f"Embedding Model: {Config.LLM.EMBEDDING_MODEL()}",
            f"Reranker Model:  {Config.RAG.RERANKER_MODEL()}",
            f"Data Directory:  {Config.Database.CHUNKS_DIR()}",
            f"Uvicorn Workers: {self._workers}",
            separator,
        ]
        if not Config.LLM.OPENAI_API_KEY():
            lines.append("WARNING: OPENAI_API_KEY is not configured — chat will not work.")
        else:
            lines.append("Configuration validated successfully.")
        lines.append(separator)
        return "\n".join(lines)
