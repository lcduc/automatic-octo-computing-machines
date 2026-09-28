"""
Ingestion worker entrypoint: parses queued uploads outside the API process.

Wiring only. Run it next to the API with ``INGESTION_WORKER=external`` set for
the API (docker-compose does this), so Docling/OCR get their own CPU and
memory limits and a crash while parsing cannot take the API down::

    python worker.py
"""

# Standard library imports
import asyncio
import logging
import os
import signal

# Third-party imports
from dotenv import load_dotenv

# Load environment variables before importing any config-dependent module
load_dotenv()

from utils.asyncio_utils import setup_windows_asyncio  # noqa: E402

setup_windows_asyncio()

from config.settings import Config  # noqa: E402
from core.document_processing.main_processor import MainDocumentProcessor  # noqa: E402
from core.retrieval.embeddings import get_embedding_service  # noqa: E402
from core.storage.database import Database  # noqa: E402
from core.storage.upload_store import UploadStore  # noqa: E402
from services.ingestion_service import IngestionService  # noqa: E402
from services.ingestion_worker import IngestionWorker  # noqa: E402
from utils.logging_setup import configure_logging  # noqa: E402

logger = logging.getLogger(__name__)

#: Worker logs live beside the API's, never in the same rotating file.
WORKER_LOG_SUBDIR = "worker"
#: Database connections the worker needs: one per slot plus lease renewals.
WORKER_DB_POOL_SIZE = 4


async def run_worker() -> None:
    """Connect, load the embedding model and process uploads until SIGTERM/SIGINT."""
    database = Database(Config.Database.DATABASE_URL(), WORKER_DB_POOL_SIZE)
    database.connect()
    try:
        if not await database.ping():
            raise RuntimeError("Cannot reach PostgreSQL; check the POSTGRES_* settings")
        embedding = get_embedding_service()
        await asyncio.to_thread(embedding.get_embedder)
        ingestion = IngestionService(MainDocumentProcessor, embedding, Config.OCR.OCR_MAX_CONCURRENT_FILES())
        worker = IngestionWorker(
            database, ingestion, UploadStore(Config.Paths.UPLOAD_DIR()), Config.OCR.OCR_MAX_CONCURRENT_FILES()
        )
        worker_task = asyncio.create_task(worker.run())
        _cancel_on_signals(worker_task)
        try:
            await worker_task
        except asyncio.CancelledError:
            logger.info("Shutdown requested")
    finally:
        await database.close()


def _cancel_on_signals(task: asyncio.Task) -> None:
    """Cancel ``task`` on SIGTERM/SIGINT so the worker hands its current upload back."""
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(signum, task.cancel)
        except NotImplementedError:
            # Windows event loops lack signal handlers; Ctrl+C still cancels via asyncio.run.
            logger.debug("Signal handler for %s unavailable on this platform", signum)


def main() -> None:
    """Configure logging, validate settings and run the worker."""
    configure_logging(os.path.join(Config.Logging.LOG_DIR(), WORKER_LOG_SUBDIR))
    Config.validate()
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        logger.info("Ingestion worker interrupted")


if __name__ == "__main__":
    main()
