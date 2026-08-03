"""
Cleanup API endpoint for manual data management and system maintenance.
Provides a single endpoint for cleaning up all temporary files, logs, and data directories.
"""

# Standard library imports
import logging
import time
from typing import Dict, Any

# Third-party imports
from fastapi import APIRouter, HTTPException, Depends, Body
from pydantic import BaseModel, Field

# Local imports
from utils.file_operations import (
    cleanup_data_folders,
    cleanup_logs,
)
from config.settings import Config
from core.storage.vector_stores import VectorStoreProvider, get_vector_store_provider
from core.ai_services.embeddings.embeddings import get_embedding_service
from core.retrieval.query_expansion.query_adapter import build_from_evals, save_query_adapter
from models.responses import VectorRebuildResponse, StatusEnum

router = APIRouter()
logger = logging.getLogger(__name__)


class CleanupResponse(BaseModel):
    """Response model for cleanup operations."""
    success: bool = Field(..., description="Whether the cleanup operation was successful")
    message: str = Field(..., description="Description of the cleanup operation")
    details: Dict[str, Any] = Field(default_factory=dict, description="Additional cleanup details")


# Auto-reload functionality removed


@router.post("/", response_model=CleanupResponse)
async def cleanup_all_data(
    provider: VectorStoreProvider = Depends(get_vector_store_provider),
):
    """
    Wipe chunks, vectors, temp files and logs — the entire knowledge base.

    Disabled by default (``DESTRUCTIVE_CLEANUP_ENABLED=False``): this endpoint
    has no confirmation step of its own, so leaving it reachable is a standing
    "delete everything" button. Set the env var to ``true`` for a maintenance
    window, then turn it back off.
    """
    if not Config.Server.DESTRUCTIVE_CLEANUP_ENABLED():
        logger.warning("Blocked call to disabled destructive cleanup endpoint")
        raise HTTPException(
            status_code=403,
            detail=(
                "This endpoint is disabled by default because it deletes the "
                "entire knowledge base with no confirmation. Set "
                "DESTRUCTIVE_CLEANUP_ENABLED=true in the environment to enable it."
            ),
        )
    try:
        logger.info("🧹 Starting comprehensive data cleanup via API...")

        cleanup_data_folders()
        cleanup_logs()

        # The on-disk corpus is gone; drop the in-memory copy too.
        provider.invalidate()

        logger.info(" Comprehensive data cleanup completed via API")

        return CleanupResponse(
            success=True,
            message="All data folders cleaned successfully",
            details={
                "cleaned_directories": [
                    Config.File.CHUNKS_DIR(),
                    Config.File.VECTORS_DIR(),
                    Config.File.TEMP_DIR(),
                    Config.Logging.LOG_DIR(),
                ],
                "operation": "comprehensive_cleanup"
            }
        )
    except Exception as e:
        logger.exception("Error during comprehensive cleanup")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to perform comprehensive cleanup: {str(e)}"
        )


@router.post("/vectors/rebuild", response_model=VectorRebuildResponse)
async def rebuild_vectors(
    provider: VectorStoreProvider = Depends(get_vector_store_provider),
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
        logger.info("🔄 Starting vector store rebuild via cleanup API...")
        start_time = time.time()

        # Rebuild the vector store from chunk files, then publish the new corpus
        faiss_index, embeddings, documents = provider.get_store().rebuild_vector_store()
        provider.invalidate()

        # Calculate processing time
        processing_time = time.time() - start_time
        processing_time_str = f"{processing_time:.2f}s"
        
        # Prepare response details
        details = {
            "chunk_files_loaded": len(documents) if documents else 0,
            "embedding_model": Config.RAG.EMBEDDING_MODEL(),
            "vector_dimensions": embeddings.shape[1] if embeddings is not None and len(embeddings) > 0 else 0,
            "vector_store_type": "FAISS" if faiss_index is not None else "NumPy",
            "chunks_directory": Config.File.CHUNKS_DIR(),
            "vectors_directory": Config.File.VECTORS_DIR()
        }
        
        logger.info(f" Vector store rebuild completed via cleanup API: {len(documents)} documents processed in {processing_time_str}")

        return VectorRebuildResponse(
            status=StatusEnum.SUCCESS,
            message="Vector store rebuilt successfully",
            documents_processed=len(documents) if documents else 0,
            vectors_created=len(embeddings) if embeddings is not None else 0,
            processing_time=processing_time_str,
            vector_store_path=Config.Database.VECTOR_STORE_PATH(),
            details=details
        )

    except Exception as e:
        logger.exception("Error during vector store rebuild")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to rebuild vector store: {str(e)}"
        )


@router.post("/query-adapter/update")
async def update_query_adapter(payload: Dict[str, Any] = Body(default={})):  # simple admin endpoint
    """
    Compute a query adapter from provided eval pairs and save to disk.
    Request body:
    {
      "queries": ["..."],
      "positives": ["..."],
      "lambda": 0.001
    }
    """
    try:
        queries = payload.get("queries", [])
        positives = payload.get("positives", [])
        lambda_reg = float(payload.get("lambda", 1e-3))

        if not queries or not positives or len(queries) != len(positives):
            raise HTTPException(status_code=400, detail="queries and positives must be non-empty and same length")

        embedder = get_embedding_service().get_embedder()
        adapter = build_from_evals(queries, positives, embedder, lambda_reg)
        path = Config.RAG.QUERY_ADAPTER_PATH()
        save_query_adapter(adapter, path)
        return {"success": True, "path": path, "dim": int(adapter.shape[0])}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error updating query adapter")
        raise HTTPException(status_code=500, detail=str(e))
