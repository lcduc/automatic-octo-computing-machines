"""
Document processing service for orchestrating file and URL processing operations.
Provides batch processing capabilities with efficient vector store management.
Uses Docling for basic document processing.
"""

# Standard library imports
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, List
import time

# Local imports
from core.processing import MainDocumentProcessor, FileManager, URLProcessor
from core.storage import vector_store

logger = logging.getLogger(__name__)


class DocumentService:
    """
    Service for document processing orchestration with batch capabilities.
    Handles file processing, URL extraction, and vector store management.
    Uses Docling for basic document conversion.
    """

    def __init__(self, processor=None, file_manager=None, enable_ocr: bool = None, llm_client=None, llm_model: str = None):
        """
        Initialize document service with processing components.
        - PDFs: Automatically use OCR
        - Other formats: Use normal Docling extraction
        
        Args:
            processor: Main document processor instance
            file_manager: File manager instance
            enable_ocr: Deprecated - OCR is now automatic for PDFs
            llm_client: OpenAI client for enhanced processing
            llm_model: LLM model to use for enhanced processing
        """
        self.file_manager = file_manager if file_manager is not None else FileManager()
        self.processor = (
            processor
            if processor is not None
            else MainDocumentProcessor(
                file_manager=self.file_manager,
                enable_ocr=False,  # OCR is now automatic based on file type
                llm_client=llm_client,
                llm_model=llm_model
            )
        )
        
        # Restore original URL processor since Docling doesn't support URLs
        from core.processing.processors import PDFProcessor, DocumentProcessor
        self.url_processor = URLProcessor(
            file_manager=self.file_manager,
            pdf_processor=PDFProcessor(),
            doc_processor=DocumentProcessor(),
        )
        
        # OCR concurrency control - configurable to prevent memory issues
        from config.docling_config import DoclingConfig
        max_concurrent_files = DoclingConfig.OCR_MAX_CONCURRENT_FILES()
        self._ocr_semaphore = asyncio.Semaphore(max_concurrent_files)
        logger.info(f"OCR concurrency control: max {max_concurrent_files} concurrent PDF files")

    async def _process_with_ocr_control(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        """
        Process a single file with OCR concurrency control to prevent memory exhaustion.
        Uses semaphore to limit concurrent OCR operations and aggressive memory management.
        """
        async with self._ocr_semaphore:
            logger.info(f"🔒 [DocumentService] Acquired OCR slot for {filename}")
            try:
                # Clear memory before processing
                await self._aggressive_memory_cleanup()
                
                # Process the file
                result = await self.processor.process_file(file_content, filename)
                
                # Clear memory after OCR processing
                await self._aggressive_memory_cleanup()
                
                logger.info(f"🔓 [DocumentService] Released OCR slot for {filename}")
                return result
            except Exception as e:
                logger.error(f"❌ [DocumentService] OCR processing failed for {filename}: {e}")
                # Clear memory even on failure
                await self._aggressive_memory_cleanup()
                raise

    async def _aggressive_memory_cleanup(self):
        """Perform aggressive memory cleanup to prevent memory exhaustion."""
        try:
            import gc
            import torch
            
            # Clear Python garbage collection
            gc.collect()
            
            # Clear PyTorch GPU cache if available
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
            
            # Force garbage collection multiple times
            for _ in range(3):
                gc.collect()
            
            # Clear any potential caches in the processor
            if hasattr(self.processor, 'docling_processor'):
                self.processor.docling_processor._clear_memory_caches()
            
            # Small delay to allow memory to be freed
            await asyncio.sleep(0.1)
            
        except Exception as e:
            logger.debug(f"Memory cleanup warning: {e}")

    def _create_url_metadata(self, url: str, document_count: int) -> Dict[str, Any]:
        """
        Create metadata for URL processing with unique source identification.
        Generates structured metadata for tracking URL processing results.
        """
        return {
            "source_type": "url",
            "source_name": url,
            "processed_at": datetime.now().isoformat(),
            "document_count": document_count,
            "source_id": f"url_{url.replace('://', '_').replace('/', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        }

    async def _process_url_internal(self, url: str) -> Dict[str, Any]:
        """
        Internal URL processing logic using the original URL processor.
        Extracts content from URLs and returns structured results with error handling.
        """
        try:
            # Use the original URL processor since Docling doesn't support URLs
            result = await self.url_processor.extract_from_url(url, extract_links=False)
            documents = result["documents"]
            metadata = result["metadata"]

            return {
                "success": True,
                "documents": documents,
                "metadata": metadata,
                "document_count": len(documents),
            }
        except Exception as e:
            logger.error(f"❌ [DocumentService Error] {str(e)} (url={url})")
            return {
                "success": False,
                "error": str(e),
                "documents": [],
                "metadata": {},
                "document_count": 0,
            }

    async def process_multiple_documents(
        self, file_data_list: List[tuple], rebuild_at_end: bool = True
    ) -> Dict[str, Any]:
        """
        Process multiple documents efficiently with batch vector store update.
        Optimizes performance by processing files in memory and updating vector store once.

        Args:
            file_data_list: List of (file_content, filename) tuples
            rebuild_at_end: Whether to rebuild vector store once at the end

        Returns:
            Dict containing batch processing results with success/failure metrics
        """
        start_time = time.time()
        logger.info(
            f"📥 [DocumentService] Received {len(file_data_list)} files for batch processing"
        )
        logger.info(f"🔄 Vector store rebuild at end: {rebuild_at_end}")

        results = []
        successful_documents = []
        successful_count = 0
        failed_count = 0
        total_documents = 0

        # Process files with OCR concurrency control
        async def process_single_file(file_data: tuple) -> Dict[str, Any]:
            """Process a single file with OCR concurrency control."""
            file_content, filename = file_data
            logger.debug(f"🔗 [DocumentService] Processing file: {filename}")
            try:
                # Use OCR concurrency control for PDFs, direct processing for others
                if filename.lower().endswith('.pdf'):
                    result = await self._process_with_ocr_control(file_content, filename)
                else:
                    result = await self.processor.process_file(file_content, filename)
                
                doc_count = len(result["documents"])
                ocr_time = result["metadata"].get("ocr_time")
                logger.info(
                    f"✅ [DocumentService] Successfully processed {filename}: {doc_count} chunks"
                )
                # Log document previews for debugging
                for j, doc in enumerate(result["documents"][:3]):  # Show first 3 chunks
                    preview = doc[:100].replace("\n", " ").replace("\r", " ")
                    logger.debug(f"  Chunk {j+1}: {preview}...")
                
                return {
                    "filename": filename,
                    "success": True,
                    "document_count": doc_count,
                    "metadata": result["metadata"],
                    "process_time": ocr_time,
                    "result": result
                }
            except Exception as e:
                logger.error(f"❌ [DocumentService Error] {str(e)} (file={filename})")
                return {
                    "filename": filename,
                    "success": False,
                    "error": str(e),
                    "document_count": 0,
                    "metadata": {},
                    "process_time": None,
                    "result": None
                }
        
        # Process all files concurrently with OCR control
        logger.info(f"🚀 [DocumentService] Processing {len(file_data_list)} files with OCR concurrency control")
        tasks = [process_single_file(file_data) for file_data in file_data_list]
        file_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        for i, file_result in enumerate(file_results):
            if isinstance(file_result, Exception):
                # Handle exceptions from gather
                filename = file_data_list[i][1] if i < len(file_data_list) else "unknown"
                logger.error(f"❌ [DocumentService] Exception processing {filename}: {file_result}")
                results.append({
                    "filename": filename,
                    "success": False,
                    "error": str(file_result),
                    "document_count": 0,
                    "metadata": {},
                    "process_time": None,
                })
                failed_count += 1
            else:
                # Handle normal results
                if file_result["success"]:
                    successful_documents.append({
                        "documents": file_result["result"]["documents"], 
                        "metadata": file_result["result"]["metadata"]
                    })
                    successful_count += 1
                    total_documents += file_result["document_count"]
                
                results.append(file_result)
                if not file_result["success"]:
                    failed_count += 1

        # Batch update vector store for efficiency
        logger.info(
            f"🔄 [DocumentService] Updating vector store with {len(successful_documents)} documents"
        )
        vector_store_success = self._batch_update_vector_store(
            successful_documents, rebuild_at_end
        )

        if vector_store_success:
            logger.info(
                f"✅ Vector store updated successfully with {total_documents} total document chunks"
            )
        else:
            logger.warning("⚠️ Vector store update failed or was skipped")

        response = self._create_batch_response(
            len(file_data_list),
            successful_count,
            failed_count,
            total_documents,
            vector_store_success,
            results,
        )
        response["process_time"] = time.time() - start_time
        return response

    def _batch_update_vector_store(
        self, successful_documents: List[Dict], rebuild_at_end: bool
    ) -> bool:
        """
        Handle batch vector store updates for efficiency.
        Updates vector store once with all successful documents to avoid repeated rebuilds.
        """
        if successful_documents and rebuild_at_end:
            return vector_store.add_documents_batch(
                successful_documents, rebuild_at_end=True
            )
        return False

    def _create_batch_response(
        self,
        total_files: int,
        successful_files: int,
        failed_files: int,
        total_documents: int,
        vector_store_updated: bool,
        results: List,
    ) -> Dict[str, Any]:
        """
        Create standardized batch processing response with comprehensive metrics.
        Provides consistent response format for batch operations.
        """
        return {
            "total_files": total_files,
            "successful_files": successful_files,
            "failed_files": failed_files,
            "total_documents": total_documents,
            "vector_store_updated": vector_store_updated,
            "results": results,
        }

    async def process_multiple_urls(
        self, urls: List[str], rebuild_at_end: bool = True
    ) -> Dict[str, Any]:
        """
        Process multiple URLs concurrently with batch vector store update.
        Optimizes performance by processing URLs in parallel and updating vector store once.

        Args:
            urls: List of URLs to process
            rebuild_at_end: Whether to rebuild vector store once at the end

        Returns:
            Dict containing batch processing results with success/failure metrics
        """

        async def _process_url_for_batch(url: str) -> Dict[str, Any]:
            """
            Process a single URL and return result formatted for batch processing.
            Wraps internal URL processing with standardized result format.
            """
            result = await self._process_url_internal(url)

            return {
                "filename": url,
                "success": result["success"],
                "document_count": result["document_count"],
                "metadata": result["metadata"],
                "documents": result["documents"],
                "error": result.get("error"),
            }

        # 🚀 Process all URLs concurrently for optimal performance (with concurrency limit)
        logger.info(f"🔄 Processing {len(urls)} URLs concurrently...")
        
        # Limit concurrent URL processing to prevent connection overload
        max_concurrent_urls = min(5, len(urls))  # Process max 5 URLs at once
        semaphore = asyncio.Semaphore(max_concurrent_urls)
        
        async def process_url_with_semaphore(url):
            async with semaphore:
                return await _process_url_for_batch(url)
        
        processing_tasks = [process_url_with_semaphore(url) for url in urls]
        url_results = await asyncio.gather(*processing_tasks)

        # Collect results and prepare for batch vector store update
        results = []
        successful_documents = []
        successful_count = 0
        failed_count = 0
        total_documents = 0

        for url_result in url_results:
            if url_result["success"]:
                successful_documents.append(
                    {
                        "documents": url_result["documents"],
                        "metadata": url_result["metadata"],
                    }
                )
                successful_count += 1
                total_documents += url_result["document_count"]
            else:
                failed_count += 1

            # Add to results (without documents to avoid duplication)
            results.append(
                {
                    "filename": url_result["filename"],
                    "success": url_result["success"],
                    "document_count": url_result["document_count"],
                    "metadata": url_result["metadata"],
                    "error": url_result.get("error"),
                }
            )

        # Batch update vector store once at the end
        vector_store_success = False
        if successful_documents and rebuild_at_end:
            logger.info(
                f"🔄 [DocumentService] Batch updating vector store with {len(successful_documents)} successful URLs..."
            )
            vector_store_success = self._batch_update_vector_store(
                successful_documents, rebuild_at_end
            )

        logger.info(
            f"✅ URL processing complete: {successful_count} successful, {failed_count} failed"
        )

        return self._create_batch_response(
            len(urls),
            successful_count,
            failed_count,
            total_documents,
            vector_store_success,
            results,
        )

    def get_supported_extensions(self) -> List[str]:
        """Get list of supported file extensions."""
        return self.processor.get_supported_extensions()

    def is_supported_file(self, filename: str) -> bool:
        """Check if file type is supported."""
        return self.processor.is_supported_file(filename)
    
    def close(self):
        """Close all resources to prevent socket leaks."""
        if hasattr(self, 'url_processor') and self.url_processor:
            self.url_processor.close()
    
    def __del__(self):
        """Destructor to ensure resources are cleaned up."""
        self.close()