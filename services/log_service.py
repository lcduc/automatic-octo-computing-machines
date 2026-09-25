"""
Reads the JSON application log for the admin web's log viewer.
"""

# Standard library imports
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)

#: Severity order used for the "at least this level" filter.
LEVEL_ORDER = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
#: Upper bound on entries returned by one query.
MAX_ENTRIES = 500


class LogService:
    """
    Filters recent entries of ``app.jsonl`` and its rotated copies, newest first.

    # ceiling: scans up to ~60 MB of rotated files per query; ship logs to Loki
    # or similar if the admin log view becomes slow or history must go further back.
    """

    def __init__(self, log_path: str, backup_count: int):
        """
        Args:
            log_path: Active JSON log file.
            backup_count: Rotated copies (``.1`` … ``.N``) to include.
        """
        self._log_path = log_path
        self._backup_count = backup_count

    def _files_newest_first(self) -> List[str]:
        """The active file followed by rotated copies that exist."""
        candidates = [self._log_path] + [f"{self._log_path}.{n}" for n in range(1, self._backup_count + 1)]
        return [path for path in candidates if os.path.exists(path)]

    def _entries_newest_first(self) -> Iterator[Dict[str, Any]]:
        """Parsed entries across files, most recent first; unparsable lines are skipped."""
        for path in self._files_newest_first():
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    lines = handle.readlines()
            except OSError:
                logger.exception("Could not read log file %s", path)
                continue
            for line in reversed(lines):
                try:
                    yield json.loads(line)
                except ValueError:
                    continue

    def query(
        self,
        min_level: str = "INFO",
        request_id: Optional[str] = None,
        contains: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """
        Matching entries, newest first.

        Args:
            min_level: Lowest severity included.
            request_id: Only entries of this request.
            contains: Case-insensitive substring of the message or logger name.
            since: Only entries at or after this (aware) time.
            limit: Maximum entries (capped at :data:`MAX_ENTRIES`).
        """
        threshold = LEVEL_ORDER.get(min_level.upper(), LEVEL_ORDER["INFO"])
        needle = contains.lower() if contains else None
        limit = max(1, min(limit, MAX_ENTRIES))
        matches: List[Dict[str, Any]] = []
        for entry in self._entries_newest_first():
            if since is not None:
                try:
                    if datetime.fromisoformat(entry.get("ts", "")) < since:
                        break
                except ValueError:
                    continue
            if LEVEL_ORDER.get(entry.get("level", ""), 0) < threshold:
                continue
            if request_id and entry.get("request_id") != request_id:
                continue
            if needle and needle not in entry.get("message", "").lower() and needle not in entry.get("logger", "").lower():
                continue
            matches.append(entry)
            if len(matches) >= limit:
                break
        return matches
