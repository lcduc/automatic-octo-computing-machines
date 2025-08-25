"""
OCR (Optical Character Recognition) package for document processing.
Provides text extraction from images and scanned documents with GPU acceleration.
"""

# Import main OCR components for text extraction
from .ocr_engine import OCREngine
from utils import cleanup_ocr_temp_files

# Export all OCR components and utilities
__all__ = ["OCREngine", "cleanup_ocr_temp_files"]  # Main OCR processing engine
