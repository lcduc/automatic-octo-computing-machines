"""
Worker entrypoint: parses queued uploads outside the API process and runs the
scheduled jobs (daily metrics rollup, alert checks).

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
from core.infrastructure.alert_notifier import AlertNotifier  # noqa: E402
from core.infrastructure.job_scheduler import JobScheduler, ScheduledJob  # noqa: E402
from core.document_processing.main_processor import MainDocumentProcessor  # noqa: E402
from core.retrieval.remote_models import embedding_service, model_server_client  # noqa: E402
from core.storage.database import Database  # noqa: E402
from core.storage.upload_store import UploadStore  # noqa: E402
from services.ingestion_service import IngestionService  # noqa: E402
from services.alert_monitor_service import AlertMonitorService  # noqa: E402
from services.ingestion_worker import IngestionWorker  # noqa: E402
from services.metrics_rollup_service import MetricsRollupService  # noqa: E402
from services.rate_limit_service import RateLimitService, TimeBuckets  # noqa: E402
from services.retention_service import RetentionService  # noqa: E402
from services.settings_service import SettingsService  # noqa: E402
from services.usage_service import UsageService  # noqa: E402
from utils.logging_setup import configure_logging  # noqa: E402

logger = logging.getLogger(__name__)

#: Worker logs live beside the API's, never in the same rotating file.
WORKER_LOG_SUBDIR = "worker"
#: Database connections the worker needs: one per slot, lease renewals, and a scheduled job with its lock.
WORKER_DB_POOL_SIZE = 6
#: Seconds between metric rollups (the current and previous day are recomputed each time).
ROLLUP_INTERVAL_SECONDS = 3600
#: Seconds between alert-rule checks.
ALERT_CHECK_INTERVAL_SECONDS = 300
#: Seconds between retention purges (RET-R1).
RETENTION_INTERVAL_SECONDS = 86400


def build_scheduler(database: Database) -> JobScheduler:
    """The worker's periodic jobs, reporting failures to the operator alert channel."""
    timezone = Config.Server.APP_TIMEZONE()
    settings = SettingsService(database)
    rate_limits = RateLimitService(database, TimeBuckets(timezone))
    usage = UsageService(database, rate_limits)
    monitor = AlertMonitorService(
        database, AlertNotifier.from_config(), settings, usage, Config.Paths.UPLOAD_DIR(),
        Config.Alerts.MONITOR_API_READY_URL(),
    )
    rollup = MetricsRollupService(database, timezone)
    jobs = [
        ScheduledJob("metrics_rollup", ROLLUP_INTERVAL_SECONDS, rollup.run),
        ScheduledJob("alert_checks", ALERT_CHECK_INTERVAL_SECONDS, monitor.check),
        ScheduledJob("retention_purge", RETENTION_INTERVAL_SECONDS, RetentionService(database, settings, rollup, rate_limits).purge),
    ]
    return JobScheduler(database, jobs, on_failure=monitor.job_failed, on_success=monitor.job_succeeded)


async def run_worker() -> None:
    """Connect, load the embedding model and process uploads until SIGTERM/SIGINT."""
    database = Database(Config.Database.DATABASE_URL(), WORKER_DB_POOL_SIZE)
    database.connect()
    try:
        if not await database.ping():
            raise RuntimeError("Cannot reach PostgreSQL; check the POSTGRES_* settings")
        # With MODEL_SERVER_URL the models stay in the model-server; nothing is loaded here.
        embedding = embedding_service(model_server_client())
        await asyncio.to_thread(embedding.get_embedder)
        ingestion = IngestionService(MainDocumentProcessor, embedding, Config.OCR.OCR_MAX_CONCURRENT_FILES())
        worker = IngestionWorker(
            database, ingestion, UploadStore(Config.Paths.UPLOAD_DIR()), Config.OCR.OCR_MAX_CONCURRENT_FILES()
        )
        os.makedirs(Config.Paths.UPLOAD_DIR(), exist_ok=True)
        worker_task = asyncio.create_task(worker.run())
        scheduler_task = asyncio.create_task(build_scheduler(database).run_forever())
        _cancel_on_signals(worker_task)
        try:
            await worker_task
        except asyncio.CancelledError:
            logger.info("Shutdown requested")
        finally:
            scheduler_task.cancel()
            await asyncio.gather(scheduler_task, return_exceptions=True)
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
