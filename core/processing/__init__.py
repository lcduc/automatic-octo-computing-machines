"""
Core processing package for document handling and file management.
Provides processors for various file formats and document types.
"""

# Import all processors from the consolidated file for different document types
from .processors import (
    BaseProcessor,  # Abstract base for all processors
    TextProcessor,  # Plain text and markdown processing
    PDFProcessor,  # PDF document extraction with Docling
    DocumentProcessor,  # Word document processing
    SpreadsheetProcessor,  # Excel and CSV processing
    URLProcessor,  # Web content extraction
)

# Import file management and orchestration components
from .file_manager import FileManager
from .main_processor import MainDocumentProcessor

# Export all processing components for convenient access
__all__ = [
    "BaseProcessor",  # Base processor class
    "TextProcessor",  # Text file processor
    "PDFProcessor",  # PDF processor with Docling
    "DocumentProcessor",  # Word document processor
    "SpreadsheetProcessor",  # Spreadsheet processor
    "URLProcessor",  # URL content processor
    "FileManager",  # File management utilities
    "MainDocumentProcessor",  # Main orchestration processor
]
