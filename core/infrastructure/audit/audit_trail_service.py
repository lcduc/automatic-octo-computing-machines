"""
Durable, append-only record of every answered chat turn.

Nothing else in the codebase captures what the bot actually answered:
``RequestLoggingMiddleware`` only logs HTTP method/path/status/duration, not
the query, response, confidence or sources. This fills that gap with a
JSON-Lines file, one line per turn.
"""

# Standard library imports
import logging
import os
import threading
from typing import Optional

# Local imports
from config.settings import Config
from models.audit_entry import AuditEntry
from utils.file_operations.file_manager import FileManager

logger = logging.getLogger(__name__)


class AuditTrailService:
    """Appends :class:`AuditEntry` records to a JSON-Lines log file."""

    def __init__(self, log_path: Optional[str] = None):
        """
        Args:
            log_path: Override for the configured log file path, mainly for tests.
        """
        self._log_path = log_path or Config.Audit.LOG_PATH()
        self._lock = threading.Lock()

    def record(self, entry: AuditEntry) -> None:
        """
        Append one entry to the audit log.

        Never raises: a logging failure must not affect the chat response
        that triggered it, so any error here is caught and logged instead.

        Args:
            entry: The turn to record.
        """
        try:
            directory = os.path.dirname(self._log_path)
            if directory:
                FileManager.ensure_directory_exists(directory)
            line = entry.model_dump_json()
            with self._lock:
                with open(self._log_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception:
            logger.exception("Failed to write audit trail entry for query %s", entry.query_id)


_audit_trail_service: Optional[AuditTrailService] = None
_audit_trail_lock = threading.Lock()


def get_audit_trail_service() -> AuditTrailService:
    """Get the process-wide audit trail service."""
    global _audit_trail_service
    if _audit_trail_service is None:
        with _audit_trail_lock:
            if _audit_trail_service is None:
                _audit_trail_service = AuditTrailService()
    return _audit_trail_service
