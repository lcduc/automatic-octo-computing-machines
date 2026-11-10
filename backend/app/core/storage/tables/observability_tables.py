"""
Observability tables: per-answer traces, daily metric rollups and alert state.

Traces hold what the pipeline did for one answer (ADM-05) and are purged
after their retention; the daily rollup keeps only counts and aggregates (no
personal data), so dashboards keep their history after the purge (OBS-03).
"""

# Standard library imports
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

# Third-party imports
from sqlalchemy import BigInteger, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

# Local imports
from .base import Base, created_at_column, updated_at_column


class MessageTrace(Base):
    """What the pipeline did to produce one assistant message."""

    __tablename__ = "message_traces"
    #: The retention purge deletes by age.
    __table_args__ = (Index("ix_message_traces_created_at", "created_at"),)

    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    route: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    intent: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    #: The standalone search query (PII-redacted like the message itself).
    rewritten_query: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    filters: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    chunks: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    tool_calls: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    prompt_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    steps_ms: Mapped[Dict[str, int]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = created_at_column()


class DailyMetrics(Base):
    """One local day's aggregates; recomputed while the day is recent, kept forever."""

    __tablename__ = "metrics_daily"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    turns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    conversations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    handoffs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    p50_latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    p95_latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    p95_first_token_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cost_micro_usd: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    #: ``{"outcomes": {...}, "cost_by_model": {...}, "cost_by_tier": {...}, "handoff_reasons": {...},
    #: "routes": {...}, "intents": {...}, "feedback": {...}, "ingestion_failures": n}``.
    breakdown: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = updated_at_column()


class AlertState(Base):
    """When an alert rule last fired, so a lasting problem is reported once per cool-down."""

    __tablename__ = "alert_states"

    rule: Mapped[str] = mapped_column(String(64), primary_key=True)
    firing: Mapped[bool] = mapped_column(nullable=False, default=False)
    last_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    #: The rule's own bookmark (e.g. the newest failed upload already reported).
    cursor: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = updated_at_column()
