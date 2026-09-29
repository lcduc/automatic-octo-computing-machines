"""
Model-server entrypoint: the one process on the box that holds the GPU models.

Wiring only. Loads the embedding model, the reranker and the OCR engine once,
keeps them resident, and serves them to api and ingestion-worker over the
internal Docker network (``MODEL_SERVER_URL=http://model-server:8600``)::

    python model_server.py
"""

# Standard library imports
import logging
import os

# Third-party imports
import uvicorn
from dotenv import load_dotenv

# Load environment variables before importing any config-dependent module
load_dotenv()

from config.model_server_settings import ModelServerConfig  # noqa: E402
from config.settings import Config  # noqa: E402
from core.infrastructure.model_server.app import create_model_server_app  # noqa: E402
from core.infrastructure.model_server.model_host import ModelHost  # noqa: E402
from core.infrastructure.model_server.scheduler import PriorityScheduler  # noqa: E402
from utils.logging_setup import configure_logging  # noqa: E402

logger = logging.getLogger(__name__)

#: Model-server logs live beside the API's, never in the same rotating file.
MODEL_SERVER_LOG_SUBDIR = "model-server"


def main() -> None:
    """Configure logging and serve the models (a single process owns the GPU)."""
    configure_logging(os.path.join(Config.Logging.LOG_DIR(), MODEL_SERVER_LOG_SUBDIR))
    if not ModelServerConfig.MODEL_SERVER_TOKEN():
        logger.critical("MODEL_SERVER_TOKEN is not set; every request would be refused")
        raise SystemExit(1)
    scheduler = PriorityScheduler(ModelServerConfig.MODEL_SERVER_SLOTS(), ModelServerConfig.MODEL_SERVER_INGESTION_SLOTS())
    app = create_model_server_app(ModelHost(), scheduler, ModelServerConfig.MODEL_SERVER_TOKEN())
    uvicorn.run(app, host="0.0.0.0", port=ModelServerConfig.MODEL_SERVER_PORT(), workers=1, log_config=None)


if __name__ == "__main__":
    main()
