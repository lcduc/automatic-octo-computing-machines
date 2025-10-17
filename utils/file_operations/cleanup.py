"""
Cleanup utilities for managing temporary files and data directories.
Provides comprehensive cleanup functions for logs and data folders.
"""

# Standard library imports
import logging
from pathlib import Path

# Local imports
from config.settings import Config
from .file_manager import FileManager

logger = logging.getLogger(__name__)




def cleanup_data_folders():
    """
    Clean up all data folders when server stops to prevent disk space accumulation.
    Removes temporary files, chunks, vectors, and logs while preserving directory structure.
    """
    logger.info("🧹 Cleaning up data folders...")


    # List of directories to clean up for comprehensive maintenance
    cleanup_dirs = [
        Config.Database.CHUNKS_DIR(),
        Config.Database.VECTORS_DIR(),
        Config.Database.TEMP_DIR(),
        Config.Logging.LOG_DIR(),
    ]

    cleaned_count = 0
    for dir_path in cleanup_dirs:
        try:
            if FileManager.directory_exists(dir_path):
                # Use FileManager for consistent cleanup operations
                count = FileManager.clean_directory_contents(
                    dir_path, keep_directory=True
                )
                cleaned_count += count
                logger.info(f" Cleaned: {dir_path} ({count} items)")
            else:
                logger.warning(f" Directory not found: {dir_path}")
        except Exception as e:
            logger.error(f" Error cleaning {dir_path}: {e}")

    logger.info(
        f"🧹 Cleanup completed! Removed {cleaned_count} items from data folders."
    )


def cleanup_logs():
    """
    Clean up log files specifically to prevent log accumulation.
    Removes old log files while preserving the logs directory structure.
    """
    logger.info("🧹 Cleaning up log files...")

    try:
        if FileUtils.directory_exists(LoggingConfig.LOG_DIR()):
            count = FileUtils.clean_directory_contents(
                LoggingConfig.LOG_DIR(), keep_directory=True
            )
            logger.info(
                f" Cleaned logs directory: {LoggingConfig.LOG_DIR()} ({count} files)"
            )
            return count
        else:
            logger.warning(f" Logs directory not found: {LoggingConfig.LOG_DIR()}")
            return 0
    except Exception as e:
        logger.error(f" Error cleaning logs: {e}")
        return 0


def cleanup_specific_directory(directory_path: str) -> int:
    """
    Clean up a specific directory with error handling.

    Args:
        directory_path: Path to the directory to clean

    Returns:
        Number of items cleaned from the directory
    """
    try:
        return FileUtils.clean_directory_contents(directory_path, keep_directory=True)
    except Exception as e:
        logger.error(f" Error cleaning {directory_path}: {e}")
        return 0


def cleanup_empty_directories(root_directory: str) -> int:
    """
    Remove empty directories recursively to maintain clean directory structure.
    Walks from bottom up to handle nested empty directories properly.

    Args:
        root_directory: Root directory to search for empty directories

    Returns:
        Number of empty directories removed
    """
    try:
        path = Path(root_directory)
        if not path.exists():
            return 0

        cleaned_count = 0

        # Walk from bottom up to handle nested empty directories correctly
        for dir_path in sorted(
            path.rglob("*"), key=lambda p: len(p.parts), reverse=True
        ):
            if dir_path.is_dir() and dir_path != path:
                try:
                    # Check if directory is empty before removal
                    if not any(dir_path.iterdir()):
                        if FileUtils.safe_delete_directory(str(dir_path)):
                            cleaned_count += 1
                except Exception as e:
                    logger.warning(
                        f" Could not remove empty directory {dir_path}: {e}"
                    )

        return cleaned_count

    except Exception as e:
        logger.error(f" Error cleaning empty directories in {root_directory}: {e}")
        return 0
