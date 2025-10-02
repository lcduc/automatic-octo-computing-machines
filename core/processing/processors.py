# Standard library imports
import io
import logging
import os
import re
import shutil
import tempfile
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urljoin, urlparse

# Third-party imports
import aiofiles
import pandas as pd
import PyPDF2
import requests
from bs4 import BeautifulSoup
from docx import Document

# Local imports
from config.file.file_config import FileConfig
from config.file.url_config import URLConfig
from core.processing.extractors import (
    PDFTextExtractor,
    DOCXTextExtractor,
    CSVTextExtractor,
    TXTTextExtractor,
    XLSXTextExtractor,
    URLTextExtractor,
    DOCLegacyTextExtractor,
)

logger = logging.getLogger(__name__)


class BaseProcessor(ABC):
    """Abstract base class for all document processors."""

    MAX_FILE_SIZE = FileConfig.MAX_FILE_SIZE()

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
        from config.file.file_config import FileConfig

        if overlap is None:
            overlap = FileConfig.CHUNK_OVERLAP()

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
    """Processor for PDF documents using Docling with embedded EasyOCR."""

    def __init__(self, extractor=None, enable_ocr: bool = True):
        super().__init__()
        self.extractor = extractor or PDFTextExtractor()
        self.enable_ocr = enable_ocr
        # Initialize Docling processor for PDF processing
        from .docling_processor import DoclingProcessor
        self.docling_processor = DoclingProcessor(enable_ocr=enable_ocr)

    async def process(
        self, content: bytes, filename: Optional[str] = None
    ) -> Tuple[List[str], Optional[float]]:
        self.validate_file_size(content)
        
        # Use Docling processor for PDF processing with embedded EasyOCR
        try:
            import time
            start_time = time.time()
            
            # Process with Docling (which handles OCR automatically)
            result = await self.docling_processor.process_document(
                content, 
                filename or "unknown.pdf",
                chunk_size=1000,
                overlap=0
            )
            
            processing_time = time.time() - start_time
            chunks = result.get("documents", [])
            
            logger.info(f"\u2705 Docling processed PDF: {len(chunks)} chunks in {processing_time:.2f} seconds")
            return chunks, processing_time
            
        except Exception as e:
            logger.warning(f"\u26a0\ufe0f Docling PDF processing failed: {e}")
            # Fallback to original extractor if Docling fails
            try:
                text = await self.extractor.extract(content, filename)
                if isinstance(text, list):
                    chunks = text
                else:
                    chunks = self.chunk_text(text)
                return chunks, None
            except Exception as fallback_error:
                logger.error(f"PDF processing completely failed: {fallback_error}")
                return [], None


class DocumentProcessor(BaseProcessor):
    """Processor for Word documents (.docx, .doc)."""

    def __init__(self, docx_extractor=None, doc_extractor=None):
        super().__init__()
        self.docx_extractor = docx_extractor or DOCXTextExtractor()
        self.doc_extractor = doc_extractor or DOCLegacyTextExtractor()

    async def process(
        self, content: bytes, filename: Optional[str] = None
    ) -> List[str]:
        self.validate_file_size(content)
        if (
            filename
            and filename.lower().endswith(".doc")
            and not filename.lower().endswith(".docx")
        ):
            text = await self.doc_extractor.extract(content, filename)
        else:
            text = await self.docx_extractor.extract(content, filename)

        # Handle case where extractor returns a list instead of string
        if isinstance(text, list):
            return text  # Already chunked
        return self.chunk_text(text)


class SpreadsheetProcessor(BaseProcessor):
    """Processor for spreadsheet files (.csv, .xlsx, .xls)."""

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
        elif file_ext in ["xlsx", "xls"]:
            sheet_texts = await self.xlsx_extractor.extract(content, filename)
            all_chunks = []
            for sheet_text in sheet_texts:
                # Handle case where extractor returns a list instead of string
                if isinstance(sheet_text, list):
                    all_chunks.extend(sheet_text)  # Already chunked
                else:
                    all_chunks.extend(self.chunk_text(sheet_text))
            return all_chunks
        else:
            raise ValueError(f"Unsupported spreadsheet format: {file_ext}")


class URLProcessor(BaseProcessor):
    """Processor for URLs."""

    def __init__(
        self, extractor=None, file_manager=None, pdf_processor=None, doc_processor=None
    ):
        super().__init__()
        self.extractor = extractor or URLTextExtractor()
        self.file_manager = file_manager
        self.pdf_processor = pdf_processor
        self.doc_processor = doc_processor

        # HTTP session and configuration
        self.session = None
        self.timeout = URLConfig.CRAWL_TIMEOUT()
        self.max_content_length = URLConfig.CRAWL_MAX_CONTENT_LENGTH()
    
    def _get_session(self):
        """Get or create a requests session with proper configuration."""
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update(
                {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
                }
            )
        return self.session
    
    def close(self):
        """Close the HTTP session to prevent socket leaks."""
        if self.session is not None:
            try:
                self.session.close()
            except Exception as e:
                logger.warning(f"Warning: Error closing HTTP session: {e}")
            finally:
                self.session = None
    
    def __del__(self):
        """Destructor to ensure session is closed."""
        self.close()

    async def process(self, url: str, extract_links: bool = False) -> List[str]:
        """Process URL content and return text chunks."""
        try:
            parsed_url = urlparse(url)
            if not parsed_url.scheme or not parsed_url.netloc:
                raise ValueError("Invalid URL format")

            documents = []
            main_content = await self._extract_single_page(url)
            documents.extend(main_content["documents"])

            if extract_links and main_content.get("links"):
                for link_url in main_content["links"][:5]:
                    try:
                        time.sleep(1)
                        linked_content = await self._extract_single_page(link_url)
                        documents.extend(linked_content["documents"])
                    except Exception as e:
                        logger.warning(
                            f"Warning: Could not extract from linked URL {link_url}: {e}"
                        )
                        continue

            return documents

        except Exception as e:
            raise ValueError(f"Error extracting content from URL {url}: {str(e)}")

    async def extract_from_url(
        self, url: str, extract_links: bool = False
    ) -> Dict[str, Any]:
        """Extract content from a URL with metadata."""
        try:
            documents = await self.process(url, extract_links)

            # Use FileManager for chunk saving if available
            chunks_dir = None
            if self.file_manager:
                # Create a safe filename from URL
                parsed_url = urlparse(url)
                safe_filename = (
                    f"{parsed_url.netloc}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                )
                chunks_dir = await self.file_manager.save_chunks_to_files(
                    documents, safe_filename
                )

            return {
                "documents": documents,
                "metadata": {
                    "source_type": "url",
                    "source_name": url,
                    "main_url": url,
                    "processed_at": datetime.now().isoformat(),
                    "document_count": len(documents),
                    "extract_links": extract_links,
                    "chunks_directory": chunks_dir,
                    "source_id": f"url_{urlparse(url).netloc}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                },
            }

        except Exception as e:
            raise ValueError(f"Error extracting content from URL {url}: {str(e)}")

    async def _extract_single_page(self, url: str) -> Dict[str, Any]:
        """Extract content from a single page or file."""
        try:
            session = self._get_session()
            response = session.get(url, timeout=self.timeout)
            response.raise_for_status()

            if len(response.content) > self.max_content_length:
                raise ValueError(f"Content too large: {len(response.content)} bytes")

            content_type = response.headers.get("content-type", "").lower()
            if "application/pdf" in content_type or url.lower().endswith(".pdf"):
                return await self._extract_pdf_from_url(url, response.content)
            elif any(
                doc_type in content_type
                for doc_type in ["application/msword", "application/vnd.openxmlformats"]
            ) or url.lower().endswith((".doc", ".docx")):
                return await self._extract_document_from_url(url, response.content)

            response.encoding = response.apparent_encoding or "utf-8"
            soup = BeautifulSoup(response.text, "html.parser")

            for script in soup(["script", "style", "nav", "footer", "header"]):
                script.decompose()

            main_content = self._find_main_content(soup)

            if main_content:
                raw_text = self._extract_structured_text(main_content)
                documents = self._chunk_web_content(raw_text)
            else:
                documents = []

            links = []
            for link in soup.find_all("a", href=True):
                href = link["href"]
                absolute_url = urljoin(url, href)
                if self._is_valid_link(absolute_url, url):
                    links.append(absolute_url)

            return {"documents": documents, "links": list(set(links))}

        except requests.RequestException as e:
            raise ValueError(f"Network error accessing {url}: {str(e)}")
        except Exception as e:
            raise ValueError(f"Error parsing content from {url}: {str(e)}")

    async def _extract_pdf_from_url(self, url: str, content: bytes) -> Dict[str, Any]:
        """Extract content from a PDF file downloaded from URL."""
        try:
            # Use injected processor or create new one
            pdf_processor = self.pdf_processor or PDFProcessor()
            documents = await pdf_processor.process(content)
            documents = [f"PDF from URL ({url}): {doc}" for doc in documents]
            return {"documents": documents, "links": []}
        except Exception as e:
            raise ValueError(f"Error processing PDF from {url}: {str(e)}")

    async def _extract_document_from_url(
        self, url: str, content: bytes
    ) -> Dict[str, Any]:
        """Extract content from a document file downloaded from URL."""
        try:
            # Use injected processor or create new one
            doc_processor = self.doc_processor or DocumentProcessor()
            documents = await doc_processor.process(content, url.split("/")[-1])
            documents = [f"Document from URL ({url}): {doc}" for doc in documents]
            return {"documents": documents, "links": []}
        except Exception as e:
            raise ValueError(f"Error processing document from {url}: {str(e)}")

    def _extract_structured_text(self, main_content: BeautifulSoup) -> str:
        """Extract text content in a structured way."""
        text_parts = []
        processed_elements = set()
        seen_content = set()

        for heading in main_content.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            if heading in processed_elements:
                continue

            heading_text = heading.get_text(strip=True)
            if not heading_text or len(heading_text) < 3:
                continue

            normalized_heading = re.sub(r"\s+", " ", heading_text.lower())
            if normalized_heading in seen_content:
                processed_elements.add(heading)
                continue

            section_parts = [heading_text]
            seen_content.add(normalized_heading)
            processed_elements.add(heading)

            current_level = int(heading.name[1])
            next_elem = heading.find_next_sibling()

            while next_elem:
                if next_elem.name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                    next_level = int(next_elem.name[1])
                    if next_level <= current_level:
                        break

                if next_elem.name in ["p", "div", "li", "blockquote"]:
                    elem_text = next_elem.get_text(strip=True)
                    if elem_text and len(elem_text) > 15:
                        elem_text = re.sub(r"\s+", " ", elem_text)
                        normalized_text = elem_text.lower()
                        if normalized_text not in seen_content:
                            section_parts.append(elem_text)
                            seen_content.add(normalized_text)
                        processed_elements.add(next_elem)

                next_elem = next_elem.find_next_sibling()

            if len(section_parts) > 1:
                section_text = " ".join(section_parts)
                text_parts.append(section_text)

        for element in main_content.find_all(["p", "div", "li", "blockquote"]):
            if element in processed_elements:
                continue

            text = element.get_text(strip=True)
            if text and len(text) > 15:
                text = re.sub(r"\s+", " ", text)
                normalized_text = text.lower()
                if normalized_text not in seen_content:
                    text_parts.append(text)
                    seen_content.add(normalized_text)

        return "\n\n".join(text_parts)

    def _chunk_web_content(self, text: str) -> List[str]:
        """Apply intelligent chunking to web content."""
        if not text or len(text.strip()) < URLConfig.URL_MIN_CHUNK_SIZE():
            return []
        return self.chunk_text(
            text, URLConfig.URL_CHUNK_SIZE(), URLConfig.URL_CHUNK_OVERLAP()
        )

    def _find_main_content(self, soup: BeautifulSoup) -> Optional[BeautifulSoup]:
        """Try to identify the main content area of the page."""
        main_selectors = [
            "main",
            '[role="main"]',
            ".main-content",
            ".content",
            ".post-content",
            ".entry-content",
            ".article-content",
            "#main",
            "#content",
            ".container .content",
        ]

        for selector in main_selectors:
            main_content = soup.select_one(selector)
            if main_content:
                return main_content  # type: ignore

        return soup.find("body") or soup  # type: ignore

    def _is_valid_link(self, link_url: str, base_url: str) -> bool:
        """Check if a link is valid for extraction."""
        try:
            parsed_link = urlparse(link_url)
            parsed_base = urlparse(base_url)

            if parsed_link.scheme not in ["http", "https"]:
                return False

            skip_extensions = {
                ".xls",
                ".xlsx",
                ".zip",
                ".rar",
                ".jpg",
                ".jpeg",
                ".png",
                ".gif",
                ".mp4",
                ".mp3",
                ".avi",
            }
            if any(parsed_link.path.lower().endswith(ext) for ext in skip_extensions):
                return False

            if parsed_link.netloc != parsed_base.netloc:
                return False

            return True

        except Exception:
            return False
