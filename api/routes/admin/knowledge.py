"""
Admin knowledge-base management: sources, documents (upload / typed) and chunks.
"""

# Standard library imports
import json
import uuid
from typing import List, Optional

# Third-party imports
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

# Local imports
from api.container import AppContainer
from api.dependencies import READ_ROLES, WRITE_ROLES, get_container, require_admin
from api.schemas.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, MessageResponse, Page, validate_metadata
from api.schemas.knowledge import (
    SOURCE_NAME_PATTERN,
    ChunkCreate,
    ChunkOut,
    ChunkUpdate,
    DocumentDetail,
    DocumentOut,
    DocumentUpdate,
    SourceCreate,
    SourceOut,
    SourceUpdate,
    TextDocumentCreate,
)
from config.settings import Config
from services.auth_service import AdminPrincipal

router = APIRouter(prefix="/knowledge", tags=["Admin: knowledge"])

read_access = Depends(require_admin(READ_ROLES))
write_access = require_admin(WRITE_ROLES)


# ---------------------------------------------------------------- sources


@router.get("/sources", response_model=List[SourceOut], dependencies=[read_access])
async def list_sources(container: AppContainer = Depends(get_container)) -> List[SourceOut]:
    """Every source with its document count."""
    return [
        SourceOut(**SourceOut.model_validate(source).model_dump(exclude={"document_count"}), document_count=count)
        for source, count in await container.knowledge.list_sources()
    ]


@router.post("/sources", response_model=SourceOut, status_code=201, dependencies=[Depends(write_access)])
async def create_source(body: SourceCreate, container: AppContainer = Depends(get_container)) -> SourceOut:
    """Create a source category (e.g. ``FAQ``, ``contracts``)."""
    source = await container.knowledge.create_source(body.name, body.description, body.priority, body.enabled)
    return SourceOut.model_validate(source)


@router.patch("/sources/{source_id}", response_model=SourceOut, dependencies=[Depends(write_access)])
async def update_source(source_id: int, body: SourceUpdate, container: AppContainer = Depends(get_container)) -> SourceOut:
    """Rename, re-describe, re-prioritize or enable/disable a source."""
    source = await container.knowledge.update_source(source_id, body.model_dump(exclude_unset=True))
    return SourceOut.model_validate(source)


@router.delete("/sources/{source_id}", response_model=MessageResponse, dependencies=[Depends(write_access)])
async def delete_source(source_id: int, container: AppContainer = Depends(get_container)) -> MessageResponse:
    """Delete an empty source."""
    await container.knowledge.delete_source(source_id)
    return MessageResponse(message="Source deleted")


# ---------------------------------------------------------------- documents


@router.get("/documents", response_model=Page[DocumentOut], dependencies=[read_access])
async def list_documents(
    source: Optional[str] = Query(None, pattern=SOURCE_NAME_PATTERN),
    status: Optional[str] = Query(None, pattern="^(processing|ready|failed)$"),
    search: Optional[str] = Query(None, max_length=200),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
    container: AppContainer = Depends(get_container),
) -> Page[DocumentOut]:
    """Documents newest first, filterable by source, status and title/filename."""
    documents, total = await container.knowledge.list_documents(source, status, search, limit, offset)
    return Page(items=[DocumentOut.from_document(d) for d in documents], total=total, limit=limit, offset=offset)


@router.post("/documents/upload", response_model=DocumentOut, status_code=202)
async def upload_document(
    file: UploadFile = File(...),
    source: str = Form(..., pattern=SOURCE_NAME_PATTERN),
    title: Optional[str] = Form(None, max_length=512),
    metadata: str = Form("{}", description="JSON object of document metadata"),
    principal: AdminPrincipal = Depends(write_access),
    container: AppContainer = Depends(get_container),
) -> DocumentOut:
    """
    Upload a file into a source. Parsing and embedding continue in the
    background; poll the document until its status is ``ready`` or ``failed``.
    """
    try:
        parsed_metadata = validate_metadata(json.loads(metadata))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, f"Invalid metadata: {exc}")
    content = await file.read(Config.File.MAX_FILE_SIZE() + 1)
    if len(content) > Config.File.MAX_FILE_SIZE():
        raise HTTPException(413, f"File too large; maximum is {Config.File.MAX_FILE_SIZE() // (1024 * 1024)}MB")
    document = await container.knowledge.upload_file(
        content, file.filename or "upload", source, title, parsed_metadata, principal.email
    )
    return DocumentOut.from_document(document)


@router.post("/documents/text", response_model=DocumentOut, status_code=201)
async def create_text_document(
    body: TextDocumentCreate,
    principal: AdminPrincipal = Depends(write_access),
    container: AppContainer = Depends(get_container),
) -> DocumentOut:
    """Create a document from typed text (searchable immediately)."""
    document = await container.knowledge.create_text_document(
        body.source, body.title, body.content, body.metadata, principal.email
    )
    return DocumentOut.from_document(document)


@router.get("/documents/{document_id}", response_model=DocumentDetail, dependencies=[read_access])
async def get_document(document_id: uuid.UUID, container: AppContainer = Depends(get_container)) -> DocumentDetail:
    """A document with all of its chunks."""
    return DocumentDetail.from_document(await container.knowledge.get_document(document_id))


@router.patch("/documents/{document_id}", response_model=DocumentDetail, dependencies=[Depends(write_access)])
async def update_document(
    document_id: uuid.UUID, body: DocumentUpdate, container: AppContainer = Depends(get_container)
) -> DocumentDetail:
    """Edit title, source, metadata or enabled flag."""
    document = await container.knowledge.update_document(document_id, body.model_dump(exclude_unset=True))
    return DocumentDetail.from_document(document)


@router.delete("/documents/{document_id}", response_model=MessageResponse, dependencies=[Depends(write_access)])
async def delete_document(document_id: uuid.UUID, container: AppContainer = Depends(get_container)) -> MessageResponse:
    """Delete a document and its chunks."""
    await container.knowledge.delete_document(document_id)
    return MessageResponse(message="Document deleted")


# ---------------------------------------------------------------- chunks


@router.post("/documents/{document_id}/chunks", response_model=ChunkOut, status_code=201, dependencies=[Depends(write_access)])
async def add_chunk(document_id: uuid.UUID, body: ChunkCreate, container: AppContainer = Depends(get_container)) -> ChunkOut:
    """Insert a chunk into a document."""
    chunk = await container.knowledge.add_chunk(document_id, body.content, body.metadata, body.position)
    return ChunkOut.model_validate(chunk)


@router.patch("/chunks/{chunk_id}", response_model=ChunkOut, dependencies=[Depends(write_access)])
async def update_chunk(chunk_id: uuid.UUID, body: ChunkUpdate, container: AppContainer = Depends(get_container)) -> ChunkOut:
    """Edit a chunk's text (re-embedded automatically) and/or metadata."""
    chunk = await container.knowledge.update_chunk(chunk_id, body.content, body.metadata)
    return ChunkOut.model_validate(chunk)


@router.delete("/chunks/{chunk_id}", response_model=MessageResponse, dependencies=[Depends(write_access)])
async def delete_chunk(chunk_id: uuid.UUID, container: AppContainer = Depends(get_container)) -> MessageResponse:
    """Remove a chunk."""
    await container.knowledge.delete_chunk(chunk_id)
    return MessageResponse(message="Chunk deleted")
