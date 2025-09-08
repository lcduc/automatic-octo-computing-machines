"""
Cleanup API endpoint for manual data management and system maintenance.
Provides a single endpoint for cleaning up all temporary files, logs, and data directories.
"""

# Standard library imports
import logging
from typing import Dict, Any

# Third-party imports
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

# Local imports
from utils.cleanup import (
    cleanup_data_folders,
    cleanup_logs,
    cleanup_ocr_temp_files,
)
from config.file.file_config import FileConfig
from config.server.logging_config import LoggingConfig
from api.dependencies import get_vector_store
from core.storage.vector_store import VectorStore
from core.monitoring.file_watcher import auto_reload_manager
from models.responses import VectorRebuildResponse, StatusEnum
from config.rag.rag_config import RAGConfig

router = APIRouter()
logger = logging.getLogger(__name__)


class CleanupResponse(BaseModel):
    """Response model for cleanup operations."""
    success: bool = Field(..., description="Whether the cleanup operation was successful")
    message: str = Field(..., description="Description of the cleanup operation")
    details: Dict[str, Any] = Field(default_factory=dict, description="Additional cleanup details")


class AutoReloadControlRequest(BaseModel):
    action: str = Field(..., description="Action to perform: enable, disable, refresh")
    debounce_delay: float = Field(None, description="Set debounce delay in seconds (optional)")


class AutoReloadControlResponse(BaseModel):
    success: bool = Field(...)
    message: str = Field(...)
    details: Dict[str, Any] = Field(default_factory=dict)


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


@router.post("/auto-reload", response_model=AutoReloadControlResponse)
async def control_auto_reload(request: AutoReloadControlRequest):
    """
    Control the auto-reload system.
    
    Actions:
    - enable: Enable automatic reloading
    - disable: Disable automatic reloading  
    - refresh: Manually refresh caches
    """
    try:
        action = request.action.lower()
        
        if action == "enable":
            auto_reload_manager.enable_auto_reload()
            message = "Auto-reload enabled"
        elif action == "disable":
            auto_reload_manager.disable_auto_reload()
            message = "Auto-reload disabled"
        elif action == "refresh":
            auto_reload_manager.manual_refresh_cache()
            message = "Manual cache refresh triggered"
        else:
            return AutoReloadControlResponse(
                success=False,
                message=f"Invalid action: {action}. Valid actions: enable, disable, refresh",
                details={}
            )
        
        # Set debounce delay if provided
        if request.debounce_delay is not None:
            auto_reload_manager.set_debounce_delay(request.debounce_delay)
            message += f" (debounce delay set to {request.debounce_delay}s)"
        
        return AutoReloadControlResponse(
            success=True,
            message=message,
            details=auto_reload_manager.get_status()
        )
        
    except Exception as e:
        return AutoReloadControlResponse(
            success=False,
            message=f"Error controlling auto-reload: {str(e)}",
            details={}
        )


@router.post("/vectors/rebuild", response_model=VectorRebuildResponse)
async def rebuild_vectors(
    vector_store: VectorStore = Depends(get_vector_store)
):
    """
    Force rebuild the vector store from all current chunk files.
    
    This endpoint will:
    1. Load all documents from chunk files
    2. Create new embeddings for all documents
    3. Rebuild the vector store with updated vectors
    4. Save the updated vector store to disk
    """
    try:
        import time
        logger.info("🔄 Starting vector store rebuild via cleanup API...")
        start_time = time.time()
        
        # Rebuild the vector store from chunk files
        faiss_index, embeddings, documents = vector_store.rebuild_vector_store()
        
        # Calculate processing time
        processing_time = time.time() - start_time
        processing_time_str = f"{processing_time:.2f}s"
        
        # Prepare response details
        details = {
            "chunk_files_loaded": len(documents) if documents else 0,
            "embedding_model": RAGConfig.EMBEDDING_MODEL(),
            "vector_dimensions": embeddings.shape[1] if embeddings is not None and len(embeddings) > 0 else 0,
            "vector_store_type": "FAISS" if faiss_index is not None else "NumPy",
            "chunks_directory": FileConfig.CHUNKS_DIR(),
            "vectors_directory": FileConfig.VECTORS_DIR()
        }
        
        logger.info(f"✅ Vector store rebuild completed via cleanup API: {len(documents)} documents processed in {processing_time_str}")
        
        return VectorRebuildResponse(
            status=StatusEnum.SUCCESS,
            message="Vector store rebuilt successfully",
            documents_processed=len(documents) if documents else 0,
            vectors_created=len(embeddings) if embeddings is not None else 0,
            processing_time=processing_time_str,
            vector_store_path=FileConfig.VECTOR_STORE_PATH(),
            details=details
        )
        
    except Exception as e:
        logger.error(f"❌ Error during vector store rebuild: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to rebuild vector store: {str(e)}"
        )
