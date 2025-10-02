"""
Utilities package for shared helper functions and common operations.
Provides file handling, text processing, validation, and cleanup utilities.
"""

# Import all utilities for easy access and consistent usage
from .file_utils import FileUtils
from .text_utils import TextUtils
from .validation import ValidationUtils
from .cleanup import cleanup_data_folders, cleanup_logs

# Export all utility classes and functions for convenient access
__all__ = [
    "FileUtils",  # File and directory operations
    "TextUtils",  # Text processing and manipulation
    "ValidationUtils",  # Input validation and sanitization
    "cleanup_data_folders",  # Data directory cleanup
    "cleanup_logs",  # Log file cleanup
]
