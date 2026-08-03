"""
Centralized logging configuration.

``main.py`` calls :func:`configure_logging` once at start-up; every module then
uses a plain ``logging.getLogger(__name__)``.
"""

# Standard library imports
import logging
import logging.handlers
import os
from datetime import datetime
from typing import List, Optional

# Local imports
from config.settings import Config

#: Format shared by console and file handlers.
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def configure_logging(log_dir: Optional[str] = None) -> Optional[str]:
    """
    Configure the root logger for the process.

    A rotating file handler is added when ``LOG_TO_FILE`` is enabled, bounded by
    ``LOG_MAX_SIZE`` and ``LOG_BACKUP_COUNT`` so long-running deployments cannot
    fill the disk.

    Args:
        log_dir: Directory for log files; defaults to the configured ``LOG_DIR``.

    Returns:
        Path of the active log file, or ``None`` when file logging is disabled.
    """
    handlers: List[logging.Handler] = []
    log_filepath: Optional[str] = None

    if Config.Logging.LOG_TO_FILE():
        target_dir = log_dir or Config.Logging.LOG_DIR()
        os.makedirs(target_dir, exist_ok=True)
        log_filename = f"chatbot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        log_filepath = os.path.join(target_dir, log_filename)
        handlers.append(
            logging.handlers.RotatingFileHandler(
                log_filepath,
                maxBytes=Config.Logging.LOG_MAX_SIZE(),
                backupCount=Config.Logging.LOG_BACKUP_COUNT(),
                encoding="utf-8",
            )
        )

    handlers.append(logging.StreamHandler())

    logging.basicConfig(
        level=getattr(logging, Config.Logging.LOG_LEVEL().upper(), logging.INFO),
        format=LOG_FORMAT,
        handlers=handlers,
        force=True,
    )
    return log_filepath
