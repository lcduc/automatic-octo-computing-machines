"""
Vector management API endpoints for vector store operations.
Provides endpoints for rebuilding vectors, managing embeddings, and vector store maintenance.
"""

# Standard library imports
import logging
import time
from typing import Dict, Any

# Third-party imports
from fastapi import APIRouter, HTTPException, Depends

# Local imports
from api.dependencies import get_vector_store
from core.storage.vector_store import VectorStore
from models.responses import VectorRebuildResponse, StatusEnum
from config.file.file_config import FileConfig
from config.rag.rag_config import RAGConfig

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/rebuild", response_model=VectorRebuildResponse)
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
    
    Use this endpoint when you want to refresh the vector store
    with the latest chunk data or after making changes to the
    embedding model or chunk processing.
    """
    try:
        logger.info("🔄 Starting vector store rebuild via API...")
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
        
        logger.info(f"✅ Vector store rebuild completed via API: {len(documents)} documents processed in {processing_time_str}")
        
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


@router.get("/status")
async def vector_status(
    vector_store: VectorStore = Depends(get_vector_store)
):
    """
    Get the current status of the vector store.
    
    Returns information about:
    - Number of documents in the vector store
    - Vector store file path and existence
    - Embedding model configuration
    - Last modified time of vector store
    """
    try:
        import os
        from pathlib import Path
        
        vector_store_path = FileConfig.VECTOR_STORE_PATH()
        vector_store_exists = os.path.exists(vector_store_path)
        
        # Get file stats if it exists
        file_stats = {}
        if vector_store_exists:
            stat = os.stat(vector_store_path)
            file_stats = {
                "file_size_bytes": stat.st_size,
                "last_modified": stat.st_mtime,
                "created": stat.st_ctime
            }
        
        # Try to load vector store to get document count
        try:
            faiss_index, embeddings, documents = vector_store.load_vector_store()
            document_count = len(documents) if documents else 0
            vector_count = len(embeddings) if embeddings is not None else 0
        except Exception:
            document_count = 0
            vector_count = 0
        
        return {
            "status": StatusEnum.SUCCESS,
            "message": "Vector store status retrieved successfully",
            "vector_store_exists": vector_store_exists,
            "vector_store_path": vector_store_path,
            "document_count": document_count,
            "vector_count": vector_count,
            "embedding_model": RAGConfig.EMBEDDING_MODEL(),
            "chunks_directory": FileConfig.CHUNKS_DIR(),
            "vectors_directory": FileConfig.VECTORS_DIR(),
            "file_stats": file_stats
        }
        
    except Exception as e:
        logger.error(f"❌ Error getting vector store status: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get vector store status: {str(e)}"
        )

