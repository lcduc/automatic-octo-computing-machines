"""
URL processing service for handling URL content extraction and processing.
Provides validation, concurrent processing, and batch operations for URL handling.
Uses the original URL processor since Docling doesn't support URLs.
"""

# Standard library imports
import logging
from typing import List, Dict, Any
import asyncio

# Local imports
from .base_service import BaseProcessingService
from models.responses import MultipleFileUploadResponse, URLProcessingResponse
from models.responses import StatusEnum

logger = logging.getLogger(__name__)


class URLService(BaseProcessingService):
    """
    Service for handling URL processing and content extraction with validation.
    Extends base processing service with URL-specific validation and batch processing.
    Uses the original URL processor for web content extraction.
    """

    async def process_url(self, url: str) -> URLProcessingResponse:
        """
        Process a single URL using the original URL processor for content extraction.
        
        Args:
            url: URL to process and extract content from
            
        Returns:
            URLProcessingResponse with processing results and metadata
        """
        try:
            # Validate the URL
            from utils.text_processing.validation import ValidationUtils
            validation = ValidationUtils.validate_url(url)
            if not validation["valid"]:
                raise ValueError(f"Invalid URL: {url} - {validation['error']}")
            
            # Process the URL using the document service
            result = await self.document_service._process_url_internal(url)
            
            if result["success"]:
                return URLProcessingResponse(
                    status=StatusEnum.SUCCESS,
                    message=f"Successfully processed URL: {url}",
                    url=url,
                    document_count=result["document_count"],
                    source_id=result["metadata"].get("source_id", ""),
                    metadata=result["metadata"],
                    processing_info={
                        "method": "url_processor",
                        "processing_time": "N/A",  # Could be enhanced with timing
                        "conversion_success": True
                    }
                )
            else:
                return URLProcessingResponse(
                    status=StatusEnum.ERROR,
                    message=f"Failed to process URL: {url}",
                    url=url,
                    document_count=0,
                    source_id="",
                    metadata={},
                    processing_info={
                        "method": "url_processor",
                        "error": result.get("error", "Unknown error"),
                        "conversion_success": False
                    }
                )
                
        except Exception as e:
            logger.error(f"Error processing URL {url}: {e}")
            return URLProcessingResponse(
                status=StatusEnum.ERROR,
                message=f"Error processing URL: {str(e)}",
                url=url,
                document_count=0,
                source_id="",
                metadata={},
                processing_info={
                    "method": "url_processor",
                    "error": str(e),
                    "conversion_success": False
                }
            )

    async def process_urls(self, urls: List[str]) -> MultipleFileUploadResponse:
        """
        Process multiple URLs with validation and concurrent processing.
        Validates URLs, processes them in batches, and returns comprehensive results.

        Args:
            urls: List of URLs to process and extract content from

        Returns:
            MultipleFileUploadResponse with processing results and metadata
        """
        return await self.process_items(urls, "URLs")

    async def _validate_and_prepare_items(self, urls: List[str]) -> List[str]:
        """
        Validate URLs and prepare them for processing with format checks.
        Filters out invalid URLs and ensures proper HTTP/HTTPS protocol usage.
        """
        from utils.text_processing.validation import ValidationUtils

        valid_urls = []
        for url in urls:
            if not url or not url.strip():
                continue  # Skip empty URLs
            cleaned_url = url.strip()
            validation = ValidationUtils.validate_url(cleaned_url)
            if validation["valid"]:
                valid_urls.append(cleaned_url)
            else:
                logger.warning(f"Invalid URL: {cleaned_url} ({validation['error']})")
        return valid_urls

    async def _process_items_concurrently(
        self, valid_urls: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Process URLs using batch processing for optimal performance.
        Uses document service batch processing to handle multiple URLs efficiently.
        """
        # Use batch processing from document service for efficiency
        batch_result = await self.document_service.process_multiple_urls(
            valid_urls, rebuild_at_end=True  # Rebuild vector store once at the end
        )

        # Convert batch results to individual URL results using base service method
        return self._convert_batch_results_to_file_results(
            batch_result, valid_urls, "URLs"
        )
