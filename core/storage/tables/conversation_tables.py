"""
Conversation tables: conversations, messages, feedback, handoffs and token usage.

Message content is stored after PII redaction (when enabled), so the admin
views never expose raw phone numbers or ID numbers typed by visitors.
"""

# Standard library imports
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

# Third-party imports
from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

# Local imports
from .base import Base, created_at_column, updated_at_column, utc_now, uuid_pk

CONVERSATION_STATUS_ACTIVE = "active"
CONVERSATION_STATUS_HANDOFF = "handoff_pending"
CONVERSATION_STATUS_CLOSED = "closed"

HANDOFF_STATUS_PENDING = "pending"
HANDOFF_STATUS_IN_PROGRESS = "in_progress"
HANDOFF_STATUS_RESOLVED = "resolved"


class Conversation(Base):
    """One chat session between an end user and the bot."""

    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_last_activity", "last_activity_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    api_key_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True
    )
    #: Opaque visitor id supplied by the frontend (never an email or phone).
    end_user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False, default="widget")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=CONVERSATION_STATUS_ACTIVE)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = created_at_column()
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )

    messages: Mapped[List["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Message.created_at",
    )


class Message(Base):
    """A single user or assistant message, with the turn's diagnostics."""

    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    #: How an assistant turn ended: answered / denied / handoff / blocked / error.
    outcome: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    cached: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    citations: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    guard_reason: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = created_at_column()

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    feedback: Mapped[Optional["Feedback"]] = relationship(
        back_populates="message", cascade="all, delete-orphan", passive_deletes=True, uselist=False
    )


class Feedback(Base):
    """An end user's thumbs-up/down (+ optional comment) on one assistant message."""

    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = uuid_pk()
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    #: +1 helpful, -1 not helpful.
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = created_at_column()

    message: Mapped[Message] = relationship(back_populates="feedback")


class HandoffRequest(Base):
    """A request to transfer a conversation to a human agent."""

    __tablename__ = "handoff_requests"

    id: Mapped[uuid.UUID] = uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    #: Why the bot handed off: ``no_knowledge`` or ``user_request``.
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=HANDOFF_STATUS_PENDING, index=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class TokenUsage(Base):
    """Tokens consumed by one LLM call (answer, query rewrite, intent, …)."""

    __tablename__ = "token_usage"
    __table_args__ = (Index("ix_token_usage_user_created", "end_user_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    end_user_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    purpose: Mapped[str] = mapped_column(String(24), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False, index=True
    )
