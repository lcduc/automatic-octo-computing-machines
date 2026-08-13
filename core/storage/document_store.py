"""
Document store for managing document chunks and source-based operations.
Provides persistent storage, retrieval, and management of document chunks by source.
"""

# Standard library imports
import logging
from pathlib import Path
from typing import List

# Local imports
from config.settings import Config

logger = logging.getLogger(__name__)


class DocumentStore:
    """
    Handles document storage and retrieval from chunk files with source management.
    Provides operations for loading, counting, and managing documents by source.
    """

    def __init__(self):
        """
        Initialize document store with chunks directory from configuration.
        Sets up storage location for document chunks.
        """
        self.chunks_dir = Path(Config.File.CHUNKS_DIR())

    def load_documents_from_chunks(self) -> List[str]:
        """
        Load all documents from chunk files across all sources.
        Recursively reads chunk files and returns list of document content.
        """
        all_documents = []

        if not self.chunks_dir.exists():
            return all_documents

        logger.info("Loading chunks from %s", self.chunks_dir)

        # Find all chunk directories for different sources
        # Ensure deterministic ordering of sources
        for chunk_subdir in sorted(self.chunks_dir.iterdir(), key=lambda p: p.name.lower()):
            if chunk_subdir.is_dir():
                logger.debug("Processing chunk source %s", chunk_subdir.name)

                # Load all chunk files in this directory with sorted order
                chunk_files = sorted(chunk_subdir.glob("chunk_*.txt"), key=lambda p: p.name)
                for chunk_file in chunk_files:
                    try:
                        with open(chunk_file, "r", encoding="utf-8") as f:
                            content = f.read().strip()
                            if content:
                                all_documents.append(content)
                    except Exception:
                        logger.exception("Error reading chunk file %s", chunk_file)

        logger.info("Loaded %d chunks from files", len(all_documents))
        return all_documents

    def get_document_sources(self) -> List[str]:
        """
        Get list of all document sources (directories in chunks).
        Returns sorted list of source names for document management.
        """
        sources = []

        if not self.chunks_dir.exists():
            return sources

        # Collect all directory names as source identifiers
        for chunk_subdir in self.chunks_dir.iterdir():
            if chunk_subdir.is_dir():
                sources.append(chunk_subdir.name)

        return sorted(sources)

    def get_documents_by_source(self, source_name: str) -> List[str]:
        """
        Get all documents from a specific source with error handling.
        Loads and returns document chunks for a given source name.

        Args:
            source_name: Name of the source directory to load documents from

        Returns:
            List of document content strings from the specified source
        """
        documents = []
        source_dir = self.chunks_dir / source_name

        if not source_dir.exists():
            return documents

        # Load chunk files from specific source directory
        chunk_files = sorted(source_dir.glob("chunk_*.txt"))
        for chunk_file in chunk_files:
            try:
                with open(chunk_file, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        documents.append(content)
            except Exception:
                logger.exception("Error reading chunk file %s", chunk_file)

        return documents

    def count_documents_by_source(self) -> dict:
        """
        Count documents for each source for analytics and monitoring.
        Returns dictionary mapping source names to document counts.
        """
        counts = {}

        if not self.chunks_dir.exists():
            return counts

        # Count chunk files in each source directory
        for chunk_subdir in self.chunks_dir.iterdir():
            if chunk_subdir.is_dir():
                chunk_files = list(chunk_subdir.glob("chunk_*.txt"))
                counts[chunk_subdir.name] = len(chunk_files)

        return counts

    def delete_source_documents(self, source_name: str) -> bool:
        """
        Delete all documents from a specific source with error handling.
        Removes entire source directory and all its chunk files.

        Args:
            source_name: Name of the source directory to delete

        Returns:
            True if deletion was successful, False otherwise
        """
        try:
            source_dir = self.chunks_dir / source_name
            if source_dir.exists():
                from utils.file_manager import FileManager as FileUtils

                if FileUtils.safe_delete_directory(str(source_dir)):
                    logger.info("Deleted documents for source: %s", source_name)
                    return True
                else:
                    logger.error(
                        "Error deleting source %s: directory could not be deleted",
                        source_name,
                    )
                    return False
            return False
        except Exception:
            logger.exception("Error deleting source %s", source_name)
            return False
