# Standard library imports
import logging
from pathlib import Path

# Local imports
from config.file.file_config import FileConfig
from utils import TextUtils, cleanup_ocr_temp_files

logger = logging.getLogger(__name__)


def setup_temp_directory() -> str:
    """Setup temporary directory for OCR processing."""
    from utils.file_utils import FileUtils
    temp_dir = FileUtils.ensure_directory_exists(FileConfig.TEMP_DIR())
    return str(temp_dir)
