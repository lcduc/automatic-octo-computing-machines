"""
Usage tables: time-bucketed rate-limit and spend counters, and LLM prices.

Counters live in PostgreSQL (not process memory) so limits hold across
restarts and several API processes; one ``INSERT … ON CONFLICT DO UPDATE``
per check keeps that a single round trip.
"""

# Standard library imports
from datetime import datetime
from decimal import Decimal
from typing import Optional

# Third-party imports
from sqlalchemy import BigInteger, DateTime, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

# Local imports
from .base import Base, updated_at_column

WINDOW_MINUTE = "minute"
WINDOW_HOUR = "hour"
WINDOW_DAY = "day"
WINDOW_MONTH = "month"
COUNTER_WINDOWS = (WINDOW_MINUTE, WINDOW_HOUR, WINDOW_DAY, WINDOW_MONTH)


class UsageCounter(Base):
    """Requests, tokens and cost of one scope (visitor, user, IP, key, everyone) in one time bucket."""

    __tablename__ = "usage_counters"
    __table_args__ = (Index("ix_usage_counters_bucket_start", "bucket_start"),)

    #: e.g. ``chat:visitor:<id>``, ``tokens:user:<id>``, ``http:ip:<hash>``, ``spend:all``.
    scope_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    window: Mapped[str] = mapped_column(String(8), primary_key=True)
    #: Start of the bucket (local-time aligned for days and months), stored in UTC.
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    requests: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    cost_micro_usd: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")


class ModelPrice(Base):
    """What one LLM costs, edited in the admin web (ADM-08); applied when a call is recorded."""

    __tablename__ = "model_prices"

    model: Mapped[str] = mapped_column(String(128), primary_key=True)
    input_usd_per_million: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    output_usd_per_million: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    updated_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = updated_at_column()
