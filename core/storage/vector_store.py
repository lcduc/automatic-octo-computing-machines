"""
Vector store for managing document embeddings and similarity search.
Provides persistent storage, batch operations, and efficient vector management.
"""

# Standard library imports
import logging
import os
import pickle
from typing import Any, Dict, List, Optional, Tuple

# Third-party imports
import numpy as np

# Local imports
from config.settings import Config
from ..retrieval.embeddings import get_embedder

logger = logging.getLogger(__name__)


class VectorStore:
    """
    Handles vector operations and embeddings storage with persistence.
    Manages document embeddings, metadata, and provides efficient storage operations.
    """

    def __init__(self, vector_store_path: Optional[str] = None):
        """
        Initialize vector store with configurable storage path.
        Sets up storage location and initializes data structures.
        """
        self.vector_store_path = vector_store_path or Config.Database.VECTOR_STORE_PATH()
        self.embeddings = None
        self.documents = None
        self.document_metadata = None
        logger.info(
            f" [VectorStore] Backend initialized: {self.__class__.__name__} at {self.vector_store_path}"
        )

    def load_vector_store(self) -> Tuple[Optional[Any], np.ndarray, List[str]]:
        """
        Load vector store from file or create new one if not found.
        Handles both new and legacy format compatibility for data migration.
        """
        logger.info(f"📂 [VectorStore] Loading from: {self.vector_store_path}")
        try:
            with open(self.vector_store_path, "rb") as f:
                data = pickle.load(f)
                if len(data) == 3:
                    # New format with metadata for enhanced tracking
                    self.embeddings, self.documents, self.document_metadata = data
                    logger.info(
                        f" Loaded vector store (new format): {len(self.documents)} documents, {len(self.embeddings)} embeddings"
                    )
                else:
                    # Old format compatibility for data migration
                    self.embeddings, self.documents = data
                    self.document_metadata = [
                        {"source": "legacy"} for _ in self.documents
                    ]
                    logger.info(
                        f" Loaded vector store (legacy format): {len(self.documents)} documents, {len(self.embeddings)} embeddings"
                    )

            logger.info(
                f" Vector store stats: {len(self.documents)} documents, embeddings shape: {self.embeddings.shape}"
            )
            return None, self.embeddings, self.documents

        except FileNotFoundError:
            logger.warning("📂 Vector store file not found, creating new one...")
            return self.rebuild_vector_store()
        except Exception as e:
            logger.error(f" [VectorStore Error] {e}")
            return self.rebuild_vector_store()

    def save_vector_store(self):
        """
        Save current vector store to file with comprehensive error handling.
        Creates directory structure and persists embeddings, documents, and metadata.
        """
        logger.info(f"💾 [VectorStore] Saving to: {self.vector_store_path}")
        try:
            from utils.file_manager import FileManager as FileUtils
            FileUtils.ensure_directory_exists(os.path.dirname(self.vector_store_path))
            with open(self.vector_store_path, "wb") as f:
                pickle.dump(
                    (self.embeddings, self.documents, self.document_metadata), f
                )
            doc_count = len(self.documents) if self.documents else 0
            emb_shape = self.embeddings.shape if self.embeddings is not None else "None"
            logger.info(
                f" Vector store saved: {doc_count} documents, embeddings shape: {emb_shape}"
            )
        except Exception as e:
            logger.error(f" [VectorStore Error] {e}")

    def create_embeddings(self, documents: List[str]) -> np.ndarray:
        """
        Create embeddings for a list of documents using configured embedder.
        Provides efficient batch embedding generation with progress logging.
        """
        logger.info(f"🔄 Creating embeddings for {len(documents)} documents...")
        embedder = get_embedder()
        embeddings = embedder.encode(documents, convert_to_numpy=True)
        logger.info(f" Created embeddings: shape {embeddings.shape}")  # type: ignore
        return embeddings  # type: ignore

    def rebuild_vector_store(self) -> Tuple[Optional[Any], np.ndarray, List[str]]:
        """
        Rebuild vector store from all chunk files with comprehensive metadata.
        Loads documents from storage, creates embeddings, and saves updated store.
        """
        logger.info("🔄 [VectorStore] Rebuilding from chunk files...")

        from core.storage.document_store import DocumentStore
        from core.storage.metadata_store import MetadataStore

        doc_store = DocumentStore()
        meta_store = MetadataStore()

        # Get all documents from chunk files for rebuilding
        all_documents = doc_store.load_documents_from_chunks()
        logger.info(f" Loaded {len(all_documents)} documents from chunk files")

        if not all_documents:
            logger.warning(" No documents found to create vector store")
            # Clear existing vector store files when rebuilding with empty data
            self._clear_vector_store_files()
            # Set instance variables to empty state
            self.embeddings = None
            self.documents = []
            self.document_metadata = []
            return None, np.array([]), []

        # Create embeddings for all documents
        embeddings = self.create_embeddings(all_documents)

        # Create metadata for each document from chunk files
        document_metadata = meta_store.create_metadata_from_chunks(all_documents)
        logger.info(f"📋 Created metadata for {len(document_metadata)} documents")

        # Save updated vector store with new data
        self.embeddings = embeddings
        self.documents = all_documents
        self.document_metadata = document_metadata

        self.save_vector_store()

        logger.info(
            f" [VectorStore] Rebuilt successfully: {len(all_documents)} documents"
        )
        return None, embeddings, all_documents

    def _clear_vector_store_files(self):
        """Clear vector store file when rebuilding with empty data."""
        try:
            # Clear instance variables
            self.embeddings = None
            self.documents = None
            self.document_metadata = None

            # Delete existing file
            if os.path.exists(self.vector_store_path):
                os.remove(self.vector_store_path)
                logger.info(f" Deleted {self.vector_store_path}")

            logger.info(" Cleared vector store file")
        except Exception as e:
            logger.error(f" Error clearing vector store file: {e}")

    def add_documents(
        self,
        documents: List[str],
        source_metadata: Dict[str, Any],
        rebuild_immediately: bool = True,
    ) -> bool:
        """
        Add new documents to the vector store with optional immediate rebuild.
        Handles document addition with metadata tracking and rebuild control.
        """
        try:
            # For file-based approach, chunks are already saved by DocumentProcessor
            # Only rebuild if explicitly requested (for backward compatibility)
            if rebuild_immediately:
                self.rebuild_vector_store()

            # Use consistent 'source_name' key for all sources
            source_name = source_metadata.get('source_name', 'unknown_source')
            logger.info("Added %d documents from %s", len(documents), source_name)
            return True

        except Exception:
            logger.exception("Error adding documents")
            return False

    def add_documents_batch(
        self, documents_list: List[Dict], rebuild_at_end: bool = True
    ) -> bool:
        """
        Add multiple document sets efficiently with single rebuild at the end.
        Optimizes performance by batching operations and minimizing rebuilds.
        """
        try:
            success_count = 0
            for doc_info in documents_list:
                # Add documents without rebuilding for efficiency
                success = self.add_documents(
                    doc_info["documents"],
                    doc_info["metadata"],
                    rebuild_immediately=False,
                )
                if success:
                    success_count += 1

            # Rebuild once at the end if requested for optimal performance
            if rebuild_at_end and success_count > 0:
                self.rebuild_vector_store()
                logger.info(
                    "Batch added %d document sets", len(documents_list)
                )

            return success_count > 0

        except Exception:
            logger.exception("Error in batch document addition")
            return False

    def get_embeddings(self) -> Optional[np.ndarray]:
        """
        Get current embeddings for similarity search operations.
        Returns numpy array of document embeddings.
        """
        return self.embeddings

    def get_documents(self) -> Optional[List[str]]:
        """
        Get current documents for content retrieval.
        Returns list of document content strings.
        """
        return self.documents

    def get_metadata(self) -> Optional[List[Dict[str, Any]]]:
        """
        Get current document metadata for source tracking.
        Returns list of metadata dictionaries for each document.
        """
        return self.document_metadata
