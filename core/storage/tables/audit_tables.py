"""
Append-only audit trail of admin changes (who did what, when, with which result).
"""

# Standard library imports
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

# Third-party imports
from sqlalchemy import DDL, Index, Integer, String, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

# Local imports
from models.retention_policy import MIN_AUDIT_RETENTION_DAYS
from .base import Base, created_at_column, uuid_pk

#: Rejects every UPDATE, and every DELETE except the retention purge of entries
#: older than ``MIN_AUDIT_RETENTION_DAYS``, so no one, the application included,
#: can rewrite recent history.
IMMUTABLE_FUNCTION_DDL = f"""
CREATE OR REPLACE FUNCTION admin_audit_log_immutable() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' AND OLD.created_at < now() - interval '{MIN_AUDIT_RETENTION_DAYS} days' THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'admin_audit_log is append-only';
END;
$$ LANGUAGE plpgsql
"""
IMMUTABLE_TRIGGER_DDL = """
CREATE TRIGGER admin_audit_log_no_change
BEFORE UPDATE OR DELETE ON admin_audit_log
FOR EACH ROW EXECUTE FUNCTION admin_audit_log_immutable()
"""


class AdminAuditEntry(Base):
    """One admin write request (or sign-in attempt) and its outcome."""

    __tablename__ = "admin_audit_log"
    __table_args__ = (
        Index("ix_admin_audit_log_created_at", "created_at"),
        Index("ix_admin_audit_log_actor_email", "actor_email"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    created_at: Mapped[datetime] = created_at_column()
    #: No foreign key: entries must outlive the admin account they describe.
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True)
    #: For sign-in attempts, the e-mail that was submitted.
    actor_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    actor_role: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    client_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    #: The requested change, secrets redacted (``None`` for bodiless requests).
    request_body: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    #: The resulting state as returned to the admin, secrets redacted.
    response_body: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)


# Also created by ``Base.metadata.create_all`` (tests), not only by the migration.
event.listen(AdminAuditEntry.__table__, "after_create", DDL(IMMUTABLE_FUNCTION_DDL))
event.listen(AdminAuditEntry.__table__, "after_create", DDL(IMMUTABLE_TRIGGER_DDL))
