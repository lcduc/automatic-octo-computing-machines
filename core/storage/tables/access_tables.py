"""
Access-control and runtime-configuration tables: API keys, admin users, settings.
"""

# Standard library imports
import uuid
from datetime import datetime
from typing import Any, List, Optional

# Third-party imports
from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

# Local imports
from .base import Base, created_at_column, updated_at_column, uuid_pk

#: Scope granting access to the public chat endpoints.
SCOPE_CHAT = "chat"

ROLE_OWNER = "owner"
ROLE_EDITOR = "editor"
ROLE_VIEWER = "viewer"
ADMIN_ROLES = (ROLE_OWNER, ROLE_EDITOR, ROLE_VIEWER)


class ApiKey(Base):
    """A client credential for the public chat API (one per embedding frontend)."""

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    #: First characters of the key, shown in the admin UI to tell keys apart.
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    #: SHA-256 of the full key; the key itself is shown once and never stored.
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    scopes: Mapped[List[str]] = mapped_column(JSONB, nullable=False, default=lambda: [SCOPE_CHAT])
    created_at: Mapped[datetime] = created_at_column()
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class AdminUser(Base):
    """A person allowed into the management web."""

    __tablename__ = "admin_users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    #: ``owner`` (everything), ``editor`` (knowledge + settings), ``viewer`` (read-only).
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=ROLE_VIEWER)
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = created_at_column()
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class AppSetting(Base):
    """A runtime setting editable from the admin web (e.g. the fallback mode)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = updated_at_column()
