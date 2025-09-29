import os


class OCRConfig:
    @staticmethod
    def OCR_ENABLED():
        return os.getenv("OCR_ENABLED", "true").lower() == "true"

    @staticmethod
    def OCR_MAX_WORKERS():
        return int(os.getenv("OCR_MAX_WORKERS", "2"))

    @staticmethod
    def OCR_DESKEW():
        return os.getenv("OCR_DESKEW", "false").lower() == "true"

    @staticmethod
    def OCR_GRAYSCALE():
        return os.getenv("OCR_GRAYSCALE", "false").lower() == "true"

    @staticmethod
    def OCR_BINARIZE():
        return os.getenv("OCR_BINARIZE", "false").lower() == "true"

    @staticmethod
    def OCR_BINARIZE_ADAPTIVE():
        return os.getenv("OCR_BINARIZE_ADAPTIVE", "false").lower() == "true"

    @staticmethod
    def OCR_RESIZE():
        return os.getenv("OCR_RESIZE", "false").lower() == "true"

    @staticmethod
    def OCR_RESIZE_HEIGHT():
        return int(os.getenv("OCR_RESIZE_HEIGHT", "32"))

    @staticmethod
    def OCR_CONTRAST_ENHANCE():
        return os.getenv("OCR_CONTRAST_ENHANCE", "false").lower() == "true"

    @staticmethod
    def OCR_SHARPEN():
        return os.getenv("OCR_SHARPEN", "false").lower() == "true"

    @staticmethod
    def OCR_DENOISE():
        return os.getenv("OCR_DENOISE", "false").lower() == "true"

    # Docling OCR Configuration
    @staticmethod
    def DOCLING_OCR_ENABLED():
        return os.getenv("DOCLING_OCR_ENABLED", "true").lower() == "true"

    @staticmethod
    def DOCLING_OCR_LANGS():
        """Get OCR languages as a list. Defaults to Vietnamese and English."""
        langs_str = os.getenv("DOCLING_OCR_LANGS", "vi,en")
        return [lang.strip() for lang in langs_str.split(",") if lang.strip()]

    @staticmethod
    def DOCLING_OCR_DPI():
        """Get OCR DPI setting. Higher DPI for better quality but slower processing."""
        return int(os.getenv("DOCLING_OCR_DPI", "300"))

    @staticmethod
    def DOCLING_OCR_GPU():
        """Check if GPU should be used for OCR processing."""
        return os.getenv("DOCLING_OCR_GPU", "true").lower() == "true"

    @staticmethod
    def DOCLING_OCR_TIMEOUT_SEC():
        """Get OCR processing timeout in seconds. 0 means no timeout."""
        return int(os.getenv("DOCLING_OCR_TIMEOUT_SEC", "300"))

    @staticmethod
    def DOCLING_OCR_SUBPROCESS():
        """Check if OCR should run in subprocess for better memory management."""
        return os.getenv("DOCLING_OCR_SUBPROCESS", "true").lower() == "true"
