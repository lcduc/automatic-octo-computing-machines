"""
Utilities package for shared helper functions and common operations.
"""

from .cleanup import cleanup_data_folders, cleanup_logs
from .file_manager import FileManager
from .text_utils import TextUtils
from .validation import ValidationUtils
from .monitor import PerformanceMonitor, get_performance_monitor, log_performance_summary
from .background_tasks import BackgroundTaskManager, start_background_tasks, stop_background_tasks, get_background_manager
from .model_preloader import ModelPreloader, get_model_preloader, preload_all_models
from .asyncio_utils import setup_windows_asyncio, setup_asyncio_logging
from .uvicorn_config import configure_uvicorn_for_windows, get_uvicorn_config, get_uvicorn_ssl_config
from .logging_setup import configure_logging
from .log_utils import LogManager

# Legacy aliases for backward compatibility
FileUtils = FileManager

# Export all utility classes and functions for convenient access
__all__ = [
    # File operations
    "FileManager", "FileUtils",  # File and directory operations
    "cleanup_data_folders", "cleanup_logs",  # Data directory cleanup

    # Text processing
    "TextUtils",  # Text processing and manipulation
    "ValidationUtils",  # Input validation and sanitization

    # Performance
    "PerformanceMonitor", "get_performance_monitor", "log_performance_summary",
    "BackgroundTaskManager", "start_background_tasks", "stop_background_tasks", "get_background_manager",
    "ModelPreloader", "get_model_preloader", "preload_all_models",

    # System
    "setup_windows_asyncio", "setup_asyncio_logging",
    "configure_uvicorn_for_windows", "get_uvicorn_config", "get_uvicorn_ssl_config",
    "configure_logging", "LogManager"
]
