"""
The portable form of a knowledge base: sources, documents and chunk text, without embeddings.

Embeddings are left out on purpose: they belong to one embedding model, and the
importing server re-embeds the chunks with its own.
"""

# Standard library imports
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Literal, Optional

# Third-party imports
from pydantic import BaseModel, Field

#: Format version written to and required from a bundle file.
BUNDLE_VERSION = 1
#: Same rule as the admin API for a source's name.
SOURCE_NAME_PATTERN = r"^[A-Za-z0-9_\-]{1,64}$"


class BundleSource(BaseModel):
    """A source category and its retrieval settings."""

    name: str = Field(..., pattern=SOURCE_NAME_PATTERN)
    description: str = ""
    priority: float = 1.0
    enabled: bool = True


class BundleChunk(BaseModel):
    """One retrievable passage; its position is its index in the document's list."""

    content: str = Field(..., min_length=1)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    edited: bool = False


class BundleDocument(BaseModel):
    """A ready document with its chunks."""

    source: str = Field(..., pattern=SOURCE_NAME_PATTERN)
    title: str = Field(..., min_length=1, max_length=512)
    original_filename: Optional[str] = Field(None, max_length=512)
    file_type: str = Field(..., max_length=16)
    #: Identifies the document across servers; an import skips a hash the source already holds.
    content_hash: str = Field(..., min_length=1, max_length=64)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    chunking: Dict[str, Any] = Field(default_factory=dict)
    extracted_text: Optional[str] = None
    extraction_method: Optional[str] = Field(None, max_length=16)
    access_tier: str = Field("anonymous", max_length=16)
    language: Optional[str] = Field(None, max_length=8)
    version: Optional[str] = Field(None, max_length=32)
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    chunks: List[BundleChunk] = Field(..., min_length=1)


class KnowledgeBundle(BaseModel):
    """Everything ``export-knowledge`` writes and ``import-knowledge`` reads."""

    version: Literal[1] = BUNDLE_VERSION
    sources: List[BundleSource] = Field(default_factory=list)
    documents: List[BundleDocument] = Field(default_factory=list)


@dataclass(frozen=True)
class ImportResult:
    """What an import changed."""

    sources_created: int
    documents_imported: int
    documents_skipped: int
    chunks_imported: int
