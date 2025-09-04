"""
Cleanup API endpoint for manual data management and system maintenance.
Provides a single endpoint for cleaning up all temporary files, logs, and data directories.
"""

# Standard library imports
import logging
from typing import Dict, Any

# Third-party imports
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

# Local imports
from utils.cleanup import (
    cleanup_data_folders,
    cleanup_logs,
    cleanup_ocr_temp_files,
)
from config.file.file_config import FileConfig
from config.server.logging_config import LoggingConfig

router = APIRouter()
logger = logging.getLogger(__name__)


class CleanupResponse(BaseModel):
    """Response model for cleanup operations."""
    success: bool = Field(..., description="Whether the cleanup operation was successful")
    message: str = Field(..., description="Description of the cleanup operation")
    details: Dict[str, Any] = Field(default_factory=dict, description="Additional cleanup details")


@router.post("/", response_model=CleanupResponse)
async def cleanup_all_data():
    """
    Clean up all data folders including chunks, vectors, temp files, and logs.
    This is a comprehensive cleanup that removes all processed data.
    """
    try:
        logger.info("🧹 Starting comprehensive data cleanup via API...")
        
        # Clean up OCR temp files first
        cleanup_ocr_temp_files()
        
        # Clean up all data folders
        cleanup_data_folders()
        
        # Clean up logs
        cleanup_logs()
        
        logger.info("✅ Comprehensive data cleanup completed via API")
        
        return CleanupResponse(
            success=True,
            message="All data folders cleaned successfully",
            details={
                "cleaned_directories": [
                    FileConfig.CHUNKS_DIR(),
                    FileConfig.VECTORS_DIR(),
                    FileConfig.TEMP_DIR(),
                    LoggingConfig.LOG_DIR(),
                ],
                "operation": "comprehensive_cleanup"
            }
        )
    except Exception as e:
        logger.error(f"❌ Error during comprehensive cleanup: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to perform comprehensive cleanup: {str(e)}"
        )
