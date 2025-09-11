"""
Custom uvicorn configuration for Windows to prevent asyncio connection errors.
"""

import asyncio
import sys
import logging

logger = logging.getLogger(__name__)

def configure_uvicorn_for_windows():
    """
    Configure uvicorn to use SelectorEventLoop on Windows to prevent connection errors.
    This should be called before starting uvicorn.
    """
    if sys.platform == "win32":
        try:
            # Force SelectorEventLoop policy
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            logger.info("✅ Uvicorn configured for Windows with SelectorEventLoop")
            return True
        except Exception as e:
            logger.warning(f"⚠️ Could not configure uvicorn for Windows: {e}")
            return False
    return True

def get_uvicorn_config():
    """
    Get uvicorn configuration optimized for Windows.
    """
    config = {
        "loop": "asyncio",
        "http": "httptools",
        "ws": "websockets",
    }
    
    if sys.platform == "win32":
        # Use SelectorEventLoop on Windows
        config["loop"] = "asyncio"
        logger.info("✅ Uvicorn config optimized for Windows")
    
    return config
