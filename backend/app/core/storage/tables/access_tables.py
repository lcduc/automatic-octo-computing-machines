"""
Access-control and runtime-configuration tables: API keys, admin users, settings.
"""

# Standard library imports
import uuid
from datetime import datetime
from typing import Any, List, Optional

# Third-party imports
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

# Local imports
from .base import Base, created_at_column, updated_at_column, uuid_pk

#: Scope granting access to the public chat endpoints.
SCOPE_CHAT = "chat"
#: Add, change and delete knowledge (sources, documents, chunks) through the admin API.
SCOPE_DOCUMENTS_WRITE = "documents:write"
#: Read conversations, feedback and handoffs through the admin API (e.g. exports).
SCOPE_CONVERSATIONS_READ = "conversations:read"
#: Read everything else an admin viewer can see (knowledge lists, usage, system status).
SCOPE_ADMIN_READ = "admin:read"
API_KEY_SCOPES = (SCOPE_CHAT, SCOPE_DOCUMENTS_WRITE, SCOPE_CONVERSATIONS_READ, SCOPE_ADMIN_READ)
#: Requests per minute a key may make unless set otherwise.
DEFAULT_API_KEY_RATE_LIMIT = 60

ROLE_OWNER = "owner"
ROLE_EDITOR = "editor"
ROLE_VIEWER = "viewer"
ROLE_SUPPORT_AGENT = "support_agent"
ADMIN_ROLES = (ROLE_OWNER, ROLE_EDITOR, ROLE_VIEWER, ROLE_SUPPORT_AGENT)


class ApiKey(Base):
    """
    A server-to-server credential (the client's backend, CI, automation).

    Never used by a browser: our own chat widget authenticates with its
    generated service token instead.
    """

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
    #: The key stops working after this moment (``None`` = no expiry).
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    rate_limit_per_minute: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_API_KEY_RATE_LIMIT, server_default=str(DEFAULT_API_KEY_RATE_LIMIT)
    )
    #: The key this one replaced (rotation keeps both usable until the old one expires).
    rotated_from_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True
    )


class AdminUser(Base):
    """A person allowed into the management web."""

    __tablename__ = "admin_users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    #: ``owner`` (everything), ``editor`` (knowledge + settings), ``support_agent``
    #: (reads everything, works handoffs), ``viewer`` (read-only).
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


class HostTokenUse(Base):
    """
    Binds a host token (its ``jti``) to the first visitor that presented it.

    The widget reuses its token for every call until it expires, so a ``jti``
    is not single-use; instead a token presented by any *other* visitor is a
    replay (e.g. copied into another browser) and is refused.
    """

    __tablename__ = "host_token_uses"

    jti: Mapped[str] = mapped_column(String(128), primary_key=True)
    visitor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    #: The token's ``exp``; expired rows are purged.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
