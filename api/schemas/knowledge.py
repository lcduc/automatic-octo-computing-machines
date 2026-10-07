"""
Admin knowledge-base contract: sources, documents and chunks.
"""

# Standard library imports
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional

# Third-party imports
from pydantic import BaseModel, Field, field_validator

# Local imports
from core.document_processing.chunking import MAX_CHUNK_CHARS
from .chunking import AutoChunking, ChunkingConfig
from .common import ApiModel, validate_metadata

SOURCE_NAME_PATTERN = r"^[A-Za-z0-9_\-]{1,64}$"
#: Largest hand-written document accepted, in characters.
MAX_TEXT_DOCUMENT_LENGTH = 200_000
MAX_CHUNK_LENGTH = MAX_CHUNK_CHARS
#: Allowed range of a source's retrieval priority multiplier.
MIN_PRIORITY = 0.1
MAX_PRIORITY = 5.0
#: Longest reason a reviewer can attach to a decision.
MAX_REVIEW_NOTE_LENGTH = 1000


class SourceOut(ApiModel):
    """A knowledge source with its document count."""

    id: int
    name: str
    description: str
    priority: float
    enabled: bool
    document_count: int = 0


class SourceCreate(BaseModel):
    """New source category."""

    name: str = Field(..., pattern=SOURCE_NAME_PATTERN)
    description: str = Field("", max_length=500)
    priority: float = Field(1.0, ge=MIN_PRIORITY, le=MAX_PRIORITY)
    enabled: bool = True


class SourceUpdate(BaseModel):
    """Partial source update."""

    name: Optional[str] = Field(None, pattern=SOURCE_NAME_PATTERN)
    description: Optional[str] = Field(None, max_length=500)
    priority: Optional[float] = Field(None, ge=MIN_PRIORITY, le=MAX_PRIORITY)
    enabled: Optional[bool] = None


class ChunkOut(ApiModel):
    """One chunk of a document."""

    id: uuid.UUID
    position: int
    content: str
    metadata: Dict[str, Any] = Field(validation_alias="extra_metadata")
    #: Written or changed by an admin (re-chunking asks before discarding it).
    edited: bool = False
    updated_at: datetime


class DocumentOut(ApiModel):
    """A document without its chunks."""

    id: uuid.UUID
    title: str
    source: str
    original_filename: Optional[str] = None
    file_type: str
    status: str
    error: Optional[str] = None
    enabled: bool
    #: ``pending``, ``approved`` or ``rejected``; the assistant answers only from approved documents.
    review_status: str
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_note: Optional[str] = None
    chunk_count: int
    metadata: Dict[str, Any]
    #: Chunking strategy and parameters in use (``{}`` = auto).
    chunking: Dict[str, Any] = {}
    #: Whether the extracted text is stored, i.e. preview and re-chunk are available.
    can_rechunk: bool = False
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    access_tier: str = "anonymous"
    language: Optional[str] = None
    version: Optional[str] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    supersedes_id: Optional[uuid.UUID] = None

    @classmethod
    def from_document(cls, document) -> "DocumentOut":
        """Build from a ``KnowledgeDocument`` with its source loaded."""
        return cls(
            id=document.id,
            title=document.title,
            source=document.source.name,
            original_filename=document.original_filename,
            file_type=document.file_type,
            status=document.status,
            error=document.error,
            enabled=document.enabled,
            review_status=document.review_status,
            reviewed_by=document.reviewed_by,
            reviewed_at=document.reviewed_at,
            review_note=document.review_note,
            chunk_count=document.chunk_count,
            metadata=document.extra_metadata or {},
            chunking=document.chunking or {},
            can_rechunk=document.extraction_method is not None,
            created_by=document.created_by,
            created_at=document.created_at,
            updated_at=document.updated_at,
            access_tier=document.access_tier,
            language=document.language,
            version=document.version,
            effective_from=document.effective_from,
            effective_to=document.effective_to,
            supersedes_id=document.supersedes_id,
        )


class DocumentDetail(DocumentOut):
    """A document with its ordered chunks."""

    chunks: List[ChunkOut]

    @classmethod
    def from_document(cls, document) -> "DocumentDetail":
        """Build from a ``KnowledgeDocument`` with source and chunks loaded."""
        base = DocumentOut.from_document(document).model_dump()
        return cls(**base, chunks=[ChunkOut.model_validate(chunk) for chunk in document.chunks])


class _MetadataModel(BaseModel):
    """Mixin validating a ``metadata`` field."""

    @field_validator("metadata", check_fields=False)
    @classmethod
    def _check_metadata(cls, value):
        return validate_metadata(value) if value is not None else value


class TextDocumentCreate(_MetadataModel):
    """A document typed in the admin web (e.g. one FAQ entry)."""

    source: str = Field(..., pattern=SOURCE_NAME_PATTERN)
    title: str = Field(..., min_length=1, max_length=512)
    content: str = Field(..., min_length=1, max_length=MAX_TEXT_DOCUMENT_LENGTH)
    metadata: Dict[str, Any] = {}
    chunking: ChunkingConfig = AutoChunking()


class DocumentUpdate(_MetadataModel):
    """Partial document update."""

    title: Optional[str] = Field(None, min_length=1, max_length=512)
    source: Optional[str] = Field(None, pattern=SOURCE_NAME_PATTERN)
    metadata: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None
    #: ``anonymous`` or one of the host's tiers (HOST_TIERS).
    access_tier: Optional[str] = Field(None, min_length=1, max_length=16)
    language: Optional[Literal["vi", "en", "mixed"]] = None
    version: Optional[str] = Field(None, max_length=32)
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    #: The earlier version this document replaces; its validity ends the day before this one starts.
    supersedes_id: Optional[uuid.UUID] = None


class ReviewDecision(BaseModel):
    """A reviewer's verdict on a pending document."""

    approve: bool
    note: Optional[str] = Field(None, max_length=MAX_REVIEW_NOTE_LENGTH)


class ReviewCounts(BaseModel):
    """Documents per review status."""

    pending: int
    approved: int
    rejected: int


class CitingAnswer(BaseModel):
    """An answer that cited a document."""

    id: uuid.UUID
    conversation_id: uuid.UUID
    content: str
    created_at: datetime


class ChunkCreate(_MetadataModel):
    """A new chunk inserted into a document."""

    content: str = Field(..., min_length=1, max_length=MAX_CHUNK_LENGTH)
    metadata: Dict[str, Any] = {}
    position: Optional[int] = Field(None, ge=0, description="Insert before this position; append when omitted.")


class ChunkUpdate(_MetadataModel):
    """Edit of a chunk's text and/or metadata."""

    content: Optional[str] = Field(None, min_length=1, max_length=MAX_CHUNK_LENGTH)
    metadata: Optional[Dict[str, Any]] = None


class ImportResultOut(BaseModel):
    """What a knowledge import changed."""

    sources_created: int
    documents_imported: int
    documents_skipped: int
    chunks_imported: int
