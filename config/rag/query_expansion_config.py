import os


class VietnamesePreprocessingConfig:
    """Configuration for Vietnamese text preprocessing."""

    @staticmethod
    def VIETNAMESE_PREPROCESSING_ENABLED():
        """Enable or disable Vietnamese preprocessing."""
        return os.getenv("VIETNAMESE_PREPROCESSING_ENABLED", "True").lower() == "true"

    @staticmethod
    def CLEAN_SPECIAL_CHARS():
        """Enable or disable special character cleaning."""
        return os.getenv("CLEAN_SPECIAL_CHARS", "True").lower() == "true"

    @staticmethod
    def EXTRACT_CONTENT_WORDS():
        """Enable or disable content word extraction."""
        return os.getenv("EXTRACT_CONTENT_WORDS", "True").lower() == "true"
