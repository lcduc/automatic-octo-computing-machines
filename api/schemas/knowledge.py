"""
Admin knowledge-base contract: sources, documents and chunks.
"""

# Standard library imports
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

# Third-party imports
from pydantic import BaseModel, Field, field_validator

# Local imports
from .common import ApiModel, validate_metadata

SOURCE_NAME_PATTERN = r"^[A-Za-z0-9_\-]{1,64}$"
#: Largest hand-written document accepted, in characters.
MAX_TEXT_DOCUMENT_LENGTH = 200_000
MAX_CHUNK_LENGTH = 20_000
#: Allowed range of a source's retrieval priority multiplier.
MIN_PRIORITY = 0.1
MAX_PRIORITY = 5.0


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
    chunk_count: int
    metadata: Dict[str, Any]
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

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
            chunk_count=document.chunk_count,
            metadata=document.extra_metadata or {},
            created_by=document.created_by,
            created_at=document.created_at,
            updated_at=document.updated_at,
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


class DocumentUpdate(_MetadataModel):
    """Partial document update."""

    title: Optional[str] = Field(None, min_length=1, max_length=512)
    source: Optional[str] = Field(None, pattern=SOURCE_NAME_PATTERN)
    metadata: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None


class ChunkCreate(_MetadataModel):
    """A new chunk inserted into a document."""

    content: str = Field(..., min_length=1, max_length=MAX_CHUNK_LENGTH)
    metadata: Dict[str, Any] = {}
    position: Optional[int] = Field(None, ge=0, description="Insert before this position; append when omitted.")


class ChunkUpdate(_MetadataModel):
    """Edit of a chunk's text and/or metadata."""

    content: Optional[str] = Field(None, min_length=1, max_length=MAX_CHUNK_LENGTH)
    metadata: Optional[Dict[str, Any]] = None
