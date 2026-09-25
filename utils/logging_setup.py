"""
Centralized logging configuration.

``main.py`` calls :func:`configure_logging` once at start-up; every module
then uses a plain ``logging.getLogger(__name__)``. Two destinations:

* the console, human-readable, for whoever watches the terminal;
* ``<LOG_DIR>/app.jsonl``, one JSON object per line, rotated by size, which
  the admin web's log viewer reads.

Every record carries the current request id and passes through PII
redaction first, so personal data typed by visitors never reaches disk.
"""

# Standard library imports
import json
import logging
import logging.handlers
import os
from datetime import datetime, timezone
from typing import Optional

# Local imports
from config.settings import Config
from .request_context import current_request_id

#: Name of the JSON log file inside ``LOG_DIR`` (rotated copies get ``.1``, ``.2``…).
JSON_LOG_FILENAME = "app.jsonl"
#: Size at which the JSON log rotates.
LOG_MAX_BYTES = 10 * 1024 * 1024
#: Rotated JSON log files kept.
LOG_BACKUP_COUNT = 5
CONSOLE_FORMAT = "%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s"
#: Chatty third-party loggers capped at WARNING.
NOISY_LOGGERS = ("httpx", "httpcore", "urllib3", "sentence_transformers", "transformers", "asyncio")


class ContextFilter(logging.Filter):
    """Adds ``request_id`` and optionally redacts personal data in the message."""

    def __init__(self, redactor=None):
        """
        Args:
            redactor: Object with ``redact(text).text``; ``None`` disables redaction.
        """
        super().__init__()
        self._redactor = redactor

    def filter(self, record: logging.LogRecord) -> bool:
        """Enrich the record; never drops it."""
        record.request_id = current_request_id() or "-"
        if self._redactor is not None:
            message = record.getMessage()
            redacted = self._redactor.redact(message).text
            if redacted != message:
                record.msg, record.args = redacted, None
        return True


class JsonFormatter(logging.Formatter):
    """Serializes a record as one JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        """Render ``record`` with timestamp, level, logger, message and request id."""
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def json_log_path(log_dir: Optional[str] = None) -> str:
    """Absolute path of the active JSON log file."""
    return os.path.join(log_dir or Config.Logging.LOG_DIR(), JSON_LOG_FILENAME)


def configure_logging(log_dir: Optional[str] = None) -> str:
    """
    Configure the root logger for the process.

    Args:
        log_dir: Directory for the JSON log; defaults to ``LOG_DIR``.

    Returns:
        Path of the JSON log file.
    """
    from core.guardrails.pii_redactor import PiiRedactor

    path = json_log_path(log_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    context_filter = ContextFilter(PiiRedactor() if Config.Security.PII_REDACTION_ENABLED() else None)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(CONSOLE_FORMAT))
    console.addFilter(context_filter)

    json_file = logging.handlers.RotatingFileHandler(
        path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
    )
    json_file.setFormatter(JsonFormatter())
    json_file.addFilter(context_filter)

    logging.basicConfig(
        level=getattr(logging, Config.Logging.LOG_LEVEL().upper(), logging.INFO),
        handlers=[console, json_file],
        force=True,
    )
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    return path
