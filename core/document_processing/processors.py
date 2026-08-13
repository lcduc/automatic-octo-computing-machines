# Standard library imports
import logging
from abc import ABC, abstractmethod
from typing import List, Optional

# Local imports
from config.settings import Config
from .extractors import (
    PDFTextExtractor,
    DOCXTextExtractor,
    CSVTextExtractor,
    TXTTextExtractor,
    XLSXTextExtractor,
)

logger = logging.getLogger(__name__)


class BaseProcessor(ABC):
    """Abstract base class for all document processors."""

    MAX_FILE_SIZE = Config.File.MAX_FILE_SIZE()

    @abstractmethod
    async def process(
        self, content: bytes, filename: Optional[str] = None
    ) -> List[str]:
        """Process content and return text chunks."""
        pass

    @classmethod
    def validate_file_size(cls, content: bytes) -> None:
        """Validate file size against maximum allowed."""
        if len(content) > cls.MAX_FILE_SIZE:
            raise ValueError(
                f"File too large. Maximum size: {cls.MAX_FILE_SIZE / (1024*1024):.1f}MB"
            )

    @staticmethod
    def chunk_text(
        text: str, chunk_size: int = 1000, overlap: int = None, language: str = "vi"
    ) -> List[str]:
        """
        Hybrid chunking: group full sentences into chunks up to chunk_size, with overlap at sentence boundaries.
        Delegates to TextUtils.chunk_text for unified chunking logic.
        """
        from utils.text_utils import TextUtils
        from config.settings import Config

        if overlap is None:
            overlap = Config.File.CHUNK_OVERLAP()

        return TextUtils.chunk_text(
            text, chunk_size=chunk_size, overlap=overlap, language=language
        )


class TextProcessor(BaseProcessor):
    """Processor for plain text files (.txt)."""

    def __init__(self, extractor=None):
        super().__init__()
        self.extractor = extractor or TXTTextExtractor()

    async def process(
        self, content: bytes, filename: Optional[str] = None
    ) -> List[str]:
        self.validate_file_size(content)
        text = await self.extractor.extract(content, filename)
        # Handle case where extractor returns a list instead of string
        if isinstance(text, list):
            return text  # Already chunked
        return self.chunk_text(text)


class PDFProcessor(BaseProcessor):
    """
    Direct PDF text-layer extraction via PyPDF2.

    This is the fallback used when Docling declines or fails on a PDF, so it
    deliberately does *not* call Docling itself \u2014 ``MainDocumentProcessor``
    already tried that first, and re-invoking it here would repeat expensive
    conversion work. Note that a scanned PDF with no text layer yields nothing
    here: OCR only happens on Docling's path.
    """

    def __init__(self, extractor=None):
        super().__init__()
        self.extractor = extractor or PDFTextExtractor()

    async def process(
        self, content: bytes, filename: Optional[str] = None
    ) -> List[str]:
        self.validate_file_size(content)
        text = await self.extractor.extract(content, filename)
        # Handle case where extractor returns a list instead of string
        if isinstance(text, list):
            return text  # Already chunked
        return self.chunk_text(text)


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

    async def process(
        self, content: bytes, filename: Optional[str] = None
    ) -> List[str]:
        self.validate_file_size(content)
        text = await self.docx_extractor.extract(content, filename)

        # Handle case where extractor returns a list instead of string
        if isinstance(text, list):
            return text  # Already chunked
        return self.chunk_text(text)


class SpreadsheetProcessor(BaseProcessor):
    """Processor for spreadsheet files (.csv, .xlsx)."""

    def __init__(self, extractor=None, xlsx_extractor=None):
        super().__init__()
        self.extractor = extractor or CSVTextExtractor()
        self.xlsx_extractor = xlsx_extractor or XLSXTextExtractor()

    async def process(
        self, content: bytes, filename: Optional[str] = None
    ) -> List[str]:
        self.validate_file_size(content)
        file_ext = filename.lower().split(".")[-1] if filename else "csv"
        if file_ext == "csv":
            text = await self.extractor.extract(content, filename)
            # Handle case where extractor returns a list instead of string
            if isinstance(text, list):
                return text  # Already chunked
            return self.chunk_text(text)
        elif file_ext == "xlsx":
            sheet_texts = await self.xlsx_extractor.extract(content, filename)
            # XLSXTextExtractor already returns properly chunked content (one chunk per sheet)
            # No need to re-chunk as it's already structured correctly
            return sheet_texts
        else:
            raise ValueError(f"Unsupported spreadsheet format: {file_ext}")

