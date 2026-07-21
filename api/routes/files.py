"""
File upload and URL processing endpoints for knowledge base ingestion.
"""

# Standard library imports
import logging
from typing import List

# Third-party imports
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from pydantic import BaseModel, Field, validator

# Local imports
from api.dependencies import get_upload_service, get_url_service
from services import UploadService, URLService
from models.responses import MultipleFileUploadResponse

router = APIRouter()
logger = logging.getLogger(__name__)


class URLProcessRequest(BaseModel):
    """Request model for URL processing with validation."""

    urls: List[str] = Field(..., description="List of URLs to process")

    @validator("urls")
    def check_urls_not_empty(cls, v):
        if not v or len(v) < 1:
            raise ValueError("At least one URL must be provided")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "urls": ["https://example.com/page1", "https://example.com/page2"]
            }
        }


@router.post("/upload", response_model=MultipleFileUploadResponse)
async def upload_files(
    files: List[UploadFile] = File(...),
    id: str = Form(...),
    upload_service: UploadService = Depends(get_upload_service),
):
    """
    Batch file upload endpoint for knowledge base ingestion.
    Supports multiple file formats: PDF, DOCX, TXT, CSV, XLSX, XLS.
    Applies file size limits and batch processing constraints.
    """
    normalized_id = id.strip().upper()
    if not normalized_id:
        raise HTTPException(status_code=422, detail="id must not be blank")
    return await upload_service.process_file_uploads(files, normalized_id)


@router.post("/url", response_model=MultipleFileUploadResponse)
async def process_urls(
    request: URLProcessRequest, url_service: URLService = Depends(get_url_service)
):
    """
    URL processing endpoint for web content ingestion.
    Extracts and processes content from multiple URLs in a single request.
    Applies crawling limits and content size constraints.
    """
    return await url_service.process_urls(request.urls)
