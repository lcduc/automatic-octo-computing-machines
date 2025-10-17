"""
Document Processing Configuration
Handles configuration for document processing, OCR, and preprocessing.
"""

from .docling_config import DoclingConfig
from .preprocessing_config import PreprocessingConfigManager, PreprocessingSettings

__all__ = [
    "DoclingConfig",
    "PreprocessingConfigManager", 
    "PreprocessingSettings",
]
