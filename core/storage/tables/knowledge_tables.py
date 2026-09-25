"""
Knowledge base tables: sources, documents and their embedded chunks.

A *source* is a category of knowledge ("FAQ", "contracts", "web_data", …) that
admins manage as a unit (enable/disable, retrieval priority). A *document* is
one uploaded file or hand-written entry inside a source; its *chunks* are the
retrievable passages, each carrying its own embedding.
"""

# Standard library imports
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

# Third-party imports
from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

# Local imports
from .base import Base, created_at_column, updated_at_column, uuid_pk

#: Lifecycle of a document's ingestion.
DOCUMENT_STATUS_PROCESSING = "processing"
DOCUMENT_STATUS_READY = "ready"
DOCUMENT_STATUS_FAILED = "failed"


class KnowledgeSource(Base):
    """A named category of knowledge, e.g. ``FAQ`` or ``contracts``."""

    __tablename__ = "knowledge_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: Multiplier applied to this source's retrieval scores (1.0 = neutral).
    priority: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    documents: Mapped[List["KnowledgeDocument"]] = relationship(back_populates="source")


class KnowledgeDocument(Base):
    """One file or hand-written entry, split into retrievable chunks."""

    __tablename__ = "knowledge_documents"
    __table_args__ = (Index("ix_knowledge_documents_source_status", "source_id", "status"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    original_filename: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    file_type: Mapped[str] = mapped_column(String(16), nullable=False, default="text")
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    #: Free-form, admin-editable metadata (url, effective_date, tags, …).
    extra_metadata: Mapped[Dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=DOCUMENT_STATUS_PROCESSING)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    source: Mapped[KnowledgeSource] = relationship(back_populates="documents")
    chunks: Mapped[List["KnowledgeChunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="KnowledgeChunk.position",
    )


class KnowledgeChunk(Base):
    """A retrievable passage of a document, with its embedding."""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (Index("ix_knowledge_chunks_document_position", "document_id", "position"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False
    )
    #: 0-based order within the document; neighbours are used for context expansion.
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    #: Chunk-level metadata overriding the document's (e.g. a page number, a question).
    extra_metadata: Mapped[Dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    #: Dimension-less so switching EMBEDDING_MODEL only requires a re-embed, not a migration.
    embedding: Mapped[Optional[List[float]]] = mapped_column(Vector(), nullable=True)
    embedding_model: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    document: Mapped[KnowledgeDocument] = relationship(back_populates="chunks")
