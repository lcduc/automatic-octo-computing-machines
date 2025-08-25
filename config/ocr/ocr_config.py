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
