"""
Evaluation cases collected from real conversations (ADM-12).

A case keeps a PII-redacted question, the expected answer and the documents
that should support it, with no link back to the conversation, so retention
purges and data-subject deletions never need to touch it.
"""

# Standard library imports
import uuid
from datetime import datetime
from typing import List, Optional

# Third-party imports
from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

# Local imports
from .base import Base, created_at_column, uuid_pk


class EvalCase(Base):
    """One golden question with its expected answer and sources."""

    __tablename__ = "eval_cases"

    id: Mapped[uuid.UUID] = uuid_pk()
    question: Mapped[str] = mapped_column(Text, nullable=False)
    expected_answer: Mapped[str] = mapped_column(Text, nullable=False)
    #: Knowledge sources (folders) and documents the answer should cite.
    expected_sources: Mapped[List[str]] = mapped_column(JSONB, nullable=False, default=list)
    document_ids: Mapped[List[str]] = mapped_column(JSONB, nullable=False, default=list)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = created_at_column()
