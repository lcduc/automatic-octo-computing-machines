"""
Windows-specific OCR fix for PaddlePaddle conflicts.
This module provides workarounds for common Windows PaddlePaddle import issues.
"""

import os
import sys
import logging

logger = logging.getLogger(__name__)


def fix_windows_paddle_import():
    """
    Fix Windows PaddlePaddle import issues by clearing conflicting modules.
    This is a workaround for the common Windows PaddlePaddle conflict.
    """
    try:
        # Clear any existing PaddlePaddle modules from memory
        modules_to_remove = [mod for mod in sys.modules.keys() if mod.startswith('paddle')]
        for mod in modules_to_remove:
            if mod in sys.modules:
                del sys.modules[mod]
        
        # Clear any CUDA-related modules that might conflict
        cuda_modules = [mod for mod in sys.modules.keys() if 'cuda' in mod.lower() and 'paddle' in mod.lower()]
        for mod in cuda_modules:
            if mod in sys.modules:
                del sys.modules[mod]
        
        logger.info("🧹 Cleared conflicting PaddlePaddle modules from memory")
        return True
        
    except Exception as e:
        logger.warning(f"⚠️ Failed to clear PaddlePaddle modules: {e}")
        return False


def safe_import_paddleocr():
    """
    Safely import PaddleOCR with Windows-specific workarounds.
    """
    try:
        # First attempt - normal import
        from paddleocr import PaddleOCR
        return PaddleOCR, True
    except Exception as e:
        logger.warning(f"⚠️ First PaddleOCR import failed: {e}")
        
        # Second attempt - with module clearing
        if fix_windows_paddle_import():
            try:
                from paddleocr import PaddleOCR
                return PaddleOCR, True
            except Exception as e2:
                logger.error(f"❌ PaddleOCR import failed after cleanup: {e2}")
                return None, False
        else:
            return None, False


def safe_import_vietocr():
    """
    Safely import VietOCR with Windows-specific workarounds.
    """
    try:
        from vietocr.tool.predictor import Predictor
        from vietocr.tool.config import Cfg
        return Predictor, Cfg, True
    except Exception as e:
        logger.warning(f"⚠️ VietOCR import failed: {e}")
        return None, None, False


def is_windows():
    """Check if running on Windows."""
    return os.name == 'nt' or sys.platform.startswith('win')


def get_ocr_availability():
    """
    Check OCR availability with Windows-specific fixes.
    Returns tuple: (paddleocr_available, vietocr_available, overall_available)
    """
    if not is_windows():
        # Non-Windows systems - normal import
        try:
            from paddleocr import PaddleOCR
            from vietocr.tool.predictor import Predictor
            from vietocr.tool.config import Cfg
            return True, True, True
        except ImportError:
            return False, False, False
    
    # Windows-specific handling
    paddleocr_available = False
    vietocr_available = False
    
    # Try PaddleOCR
    try:
        PaddleOCR, paddleocr_available = safe_import_paddleocr()
    except Exception as e:
        logger.error(f"❌ PaddleOCR not available: {e}")
    
    # Try VietOCR
    try:
        Predictor, Cfg, vietocr_available = safe_import_vietocr()
    except Exception as e:
        logger.error(f"❌ VietOCR not available: {e}")
    
    overall_available = paddleocr_available or vietocr_available
    
    logger.info(f"🔍 OCR Availability - PaddleOCR: {paddleocr_available}, VietOCR: {vietocr_available}, Overall: {overall_available}")
    
    return paddleocr_available, vietocr_available, overall_available
