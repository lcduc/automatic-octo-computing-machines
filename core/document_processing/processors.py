# Standard library imports
import logging
from abc import ABC, abstractmethod
from typing import Optional

# Local imports
from config.settings import Config
from .extractors import (
    Extraction,
    PDFTextExtractor,
    DOCXTextExtractor,
    CSVTextExtractor,
    TXTTextExtractor,
    XLSXTextExtractor,
)

logger = logging.getLogger(__name__)


class BaseProcessor(ABC):
    """Abstract base class for the local fallback document processors."""

    MAX_FILE_SIZE = Config.File.MAX_FILE_SIZE()

    @abstractmethod
    async def process(self, content: bytes, filename: Optional[str] = None) -> Extraction:
        """Process content into text chunks plus the full extracted text."""

    @classmethod
    def validate_file_size(cls, content: bytes) -> None:
        """Validate file size against maximum allowed."""
        if len(content) > cls.MAX_FILE_SIZE:
            raise ValueError(
                f"File too large. Maximum size: {cls.MAX_FILE_SIZE / (1024*1024):.1f}MB"
            )


class TextProcessor(BaseProcessor):
    """Processor for plain text files (.txt)."""

    def __init__(self, extractor=None):
        super().__init__()
        self.extractor = extractor or TXTTextExtractor()

    async def process(self, content: bytes, filename: Optional[str] = None) -> Extraction:
        self.validate_file_size(content)
        return await self.extractor.extract(content, filename)


class PDFProcessor(BaseProcessor):
    """
    Direct PDF text-layer extraction via pypdf.

    This is the fallback used when Docling declines or fails on a PDF, so it
    deliberately does *not* call Docling itself — ``MainDocumentProcessor``
    already tried that first, and re-invoking it here would repeat expensive
    conversion work. Note that a scanned PDF with no text layer yields nothing
    here: OCR only happens on Docling's path.
    """

    def __init__(self, extractor=None):
        super().__init__()
        self.extractor = extractor or PDFTextExtractor()

    async def process(self, content: bytes, filename: Optional[str] = None) -> Extraction:
        self.validate_file_size(content)
        return await self.extractor.extract(content, filename)


class DocumentProcessor(BaseProcessor):
    """
    Processor for Word documents (.docx).

    Legacy ``.doc`` is not handled: reading that binary format needs
    ``unstructured``/``langchain_community``, which this project does not
    depend on. ``.doc`` is excluded from ``ALLOWED_EXTENSIONS`` accordingly.
    """

    def __init__(self, docx_extractor=None):
        super().__init__()
        self.docx_extractor = docx_extractor or DOCXTextExtractor()

    async def process(self, content: bytes, filename: Optional[str] = None) -> Extraction:
        self.validate_file_size(content)
        return await self.docx_extractor.extract(content, filename)


class SpreadsheetProcessor(BaseProcessor):
    """Processor for spreadsheet files (.csv, .xlsx)."""

    def __init__(self, extractor=None, xlsx_extractor=None):
        super().__init__()
        self.extractor = extractor or CSVTextExtractor()
        self.xlsx_extractor = xlsx_extractor or XLSXTextExtractor()

    async def process(self, content: bytes, filename: Optional[str] = None) -> Extraction:
        self.validate_file_size(content)
        file_ext = filename.lower().split(".")[-1] if filename else "csv"
        if file_ext == "csv":
            return await self.extractor.extract(content, filename)
        elif file_ext == "xlsx":
            # One chunk per sheet: the sheet is already the right unit.
            return await self.xlsx_extractor.extract(content, filename)
        else:
            raise ValueError(f"Unsupported spreadsheet format: {file_ext}")
