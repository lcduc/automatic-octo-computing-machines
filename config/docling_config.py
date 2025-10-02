import os


class DoclingConfig:
    """Configuration for Docling document processing with embedded EasyOCR optimized for Vietnamese."""
    
    # Docling OCR Configuration
    @staticmethod
    def DOCLING_OCR_ENABLED():
        return os.getenv("DOCLING_OCR_ENABLED", "true").lower() == "true"

    @staticmethod
    def DOCLING_OCR_LANGS():
        """Get OCR languages as a list. Vietnamese first for better recognition."""
        langs_str = os.getenv("DOCLING_OCR_LANGS", "vi,en")
        return [lang.strip() for lang in langs_str.split(",") if lang.strip()]

    @staticmethod
    def DOCLING_OCR_DPI():
        """Get OCR DPI setting. Balanced 300 DPI for good quality vs memory usage."""
        return int(os.getenv("DOCLING_OCR_DPI", "300"))

    @staticmethod
    def DOCLING_OCR_GPU():
        """Check if GPU should be used for OCR processing."""
        return os.getenv("DOCLING_OCR_GPU", "true").lower() == "true"

    @staticmethod
    def DOCLING_OCR_TIMEOUT_SEC():
        """Get OCR processing timeout in seconds. Balanced timeout."""
        return int(os.getenv("DOCLING_OCR_TIMEOUT_SEC", "300"))

    @staticmethod
    def DOCLING_OCR_SUBPROCESS():
        """Check if OCR should run in subprocess for better memory management."""
        return os.getenv("DOCLING_OCR_SUBPROCESS", "true").lower() == "true"

    # Memory-efficient Vietnamese OCR optimizations
    @staticmethod
    def DOCLING_OCR_CONFIDENCE_THRESHOLD():
        """Minimum confidence threshold for Vietnamese text recognition."""
        return float(os.getenv("DOCLING_OCR_CONFIDENCE_THRESHOLD", "0.6"))

    @staticmethod
    def DOCLING_OCR_PREPROCESSING():
        """Enable lightweight preprocessing for Vietnamese documents."""
        return os.getenv("DOCLING_OCR_PREPROCESSING", "auto").lower()

    @staticmethod
    def DOCLING_OCR_DESKEW():
        """Enable automatic deskewing only when needed."""
        return os.getenv("DOCLING_OCR_DESKEW", "auto").lower()

    @staticmethod
    def DOCLING_OCR_DENOISE():
        """Enable lightweight denoising."""
        return os.getenv("DOCLING_OCR_DENOISE", "false").lower() == "true"

    @staticmethod
    def DOCLING_OCR_CONTRAST_ENHANCE():
        """Enable minimal contrast enhancement for diacritics."""
        return os.getenv("DOCLING_OCR_CONTRAST_ENHANCE", "auto").lower()

    @staticmethod
    def DOCLING_OCR_BATCH_SIZE():
        """Batch size optimized for memory usage."""
        return int(os.getenv("DOCLING_OCR_BATCH_SIZE", "2"))

    @staticmethod
    def DOCLING_OCR_MODEL_STORAGE():
        """Directory for storing EasyOCR models."""
        return os.getenv("DOCLING_OCR_MODEL_STORAGE", "./models/easyocr")

    @staticmethod
    def DOCLING_OCR_PARAGRAPH_MODE():
        """Enable paragraph-aware text extraction."""
        return os.getenv("DOCLING_OCR_PARAGRAPH_MODE", "true").lower() == "true"

    @staticmethod
    def DOCLING_OCR_MEMORY_LIMIT_MB():
        """Memory limit for OCR processing in MB."""
        return int(os.getenv("DOCLING_OCR_MEMORY_LIMIT_MB", "1024"))

    @staticmethod
    def DOCLING_OCR_QUALITY_MODE():
        """OCR quality mode: 'fast', 'balanced', 'quality'."""
        return os.getenv("DOCLING_OCR_QUALITY_MODE", "balanced").lower()

    @staticmethod
    def DOCLING_OCR_AUTO_OPTIMIZE():
        """Auto-optimize settings based on document characteristics."""
        return os.getenv("DOCLING_OCR_AUTO_OPTIMIZE", "true").lower() == "true"

