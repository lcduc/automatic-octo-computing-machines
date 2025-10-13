import os
from pathlib import Path


class DoclingConfig:
    """Configuration for Docling document processing with simple OCR support."""
    
    # Basic Docling Configuration
    @staticmethod
    def DOCLING_OCR_ENABLED():
        return os.getenv("DOCLING_OCR_ENABLED", "false").lower() == "true"

    @staticmethod
    def TESSERACT_CMD():
        """Get Tesseract command path. Defaults to common Windows installation."""
        return os.getenv("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    
    @staticmethod
    def TESSERACT_CMD_EXISTS():
        """Check if Tesseract command exists and is accessible."""
        tesseract_path = DoclingConfig.TESSERACT_CMD()
        return Path(tesseract_path).exists() if tesseract_path else False
    
    
    @staticmethod
    def TESSERACT_TESSDATA_DIR():
        """Get Tesseract tessdata directory. Points to project tessdata folder."""
        return os.getenv("TESSERACT_TESSDATA_DIR", str(Path(__file__).parent.parent / "tessdata"))
    
    @staticmethod
    def VIETNAMESE_TRAINEDDATA_PATH():
        """Get path to Vietnamese traineddata file in the project."""
        tessdata_dir = DoclingConfig.TESSERACT_TESSDATA_DIR()
        return Path(tessdata_dir) / "vie.traineddata"
    
    # OCR Options Configuration
    @staticmethod
    def OCR_FORCE_FULL_PAGE():
        """Whether to force full page OCR processing."""
        return os.getenv("OCR_FORCE_FULL_PAGE", "true").lower() == "true"
    
    @staticmethod
    def OCR_FORCE_ALL_PDFS():
        """Whether to force OCR on all PDFs, even those with existing text content."""
        return os.getenv("OCR_FORCE_ALL_PDFS", "false").lower() == "true"
    
    @staticmethod
    def OCR_DO_TABLE_STRUCTURE():
        """Whether to enable table structure detection."""
        return os.getenv("OCR_DO_TABLE_STRUCTURE", "true").lower() == "true"
    
    @staticmethod
    def OCR_DO_CELL_MATCHING():
        """Whether to enable cell matching in tables."""
        return os.getenv("OCR_DO_CELL_MATCHING", "true").lower() == "true"
    
    # Memory Optimization Configuration
    @staticmethod
    def OCR_PAGE_BY_PAGE():
        """Whether to use page-by-page processing for memory efficiency."""
        return os.getenv("OCR_PAGE_BY_PAGE", "true").lower() == "true"

    @staticmethod
    def OCR_DISABLE_TABLE_STRUCTURE():
        """Whether to disable table structure detection for memory efficiency."""
        return os.getenv("OCR_DISABLE_TABLE_STRUCTURE", "false").lower() == "true"

    @staticmethod
    def OCR_LOWER_RESOLUTION():
        """Whether to use lower resolution processing for memory efficiency."""
        return os.getenv("OCR_LOWER_RESOLUTION", "true").lower() == "true"

    @staticmethod
    def OCR_CONCURRENT_PAGES():
        """Number of pages to process concurrently within each PDF."""
        return int(os.getenv("OCR_CONCURRENT_PAGES", "3"))

    @staticmethod
    def OCR_MAX_CONCURRENT_FILES():
        """Maximum number of PDF files that can be processed concurrently."""
        return int(os.getenv("OCR_MAX_CONCURRENT_FILES", "1"))