"""
Admin audit trail: records every admin write (and sign-in attempt) with its outcome.
"""

# Standard library imports
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Optional, Tuple

# Local imports
from core.storage.audit_repository import AuditRepository
from core.storage.database import Database
from core.storage.tables.audit_tables import AdminAuditEntry

logger = logging.getLogger(__name__)

#: Body keys whose values never reach the audit log.
SECRET_KEYS = frozenset({"password", "current_password", "new_password", "key", "access_token"})
REDACTED = "***"


def redact_secrets(value: Any) -> Any:
    """``value`` with every secret-looking key's value replaced, at any depth (pure)."""
    if isinstance(value, dict):
        return {k: REDACTED if k in SECRET_KEYS else redact_secrets(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value


@dataclass(frozen=True)
class AuditRecord:
    """Everything known about one audited request."""

    method: str
    path: str
    status_code: int
    actor_id: Optional[uuid.UUID]
    actor_email: Optional[str]
    actor_role: Optional[str]
    request_id: Optional[str]
    client_ip: Optional[str]
    request_body: Any
    response_body: Any


class AuditService:
    """Writes and lists audit entries."""

    def __init__(self, database: Database):
        """
        Args:
            database: Connected database.
        """
        self._database = database

    async def record(self, record: AuditRecord) -> None:
        """Store one entry; bodies are redacted here so no caller can forget to."""
        async with self._database.session() as session:
            AuditRepository(session).add(
                AdminAuditEntry(
                    actor_id=record.actor_id,
                    actor_email=record.actor_email,
                    actor_role=record.actor_role,
                    method=record.method,
                    path=record.path[:512],
                    status_code=record.status_code,
                    request_id=record.request_id,
                    client_ip=record.client_ip,
                    request_body=redact_secrets(record.request_body),
                    response_body=redact_secrets(record.response_body),
                )
            )
        logger.debug("Audited %s %s -> %d by %s", record.method, record.path, record.status_code, record.actor_email)

    async def list(
        self,
        actor: Optional[str],
        method: Optional[str],
        path_contains: Optional[str],
        since: Optional[datetime],
        limit: int,
        offset: int,
    ) -> Tuple[List[AdminAuditEntry], int]:
        """A page of entries, newest first, and the total matching the filters."""
        async with self._database.session() as session:
            return await AuditRepository(session).list(actor, method, path_contains, since, limit, offset)
