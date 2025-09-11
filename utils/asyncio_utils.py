"""
Windows-specific asyncio utilities to prevent socket and event loop issues.
Handles ProactorEventLoop problems that cause WinError 10038.
"""

import asyncio
import logging
import sys
import warnings
from typing import Optional

logger = logging.getLogger(__name__)

def setup_windows_asyncio():
    """
    Setup Windows-specific asyncio configuration to prevent socket errors.
    This fixes WinError 10038 and other Windows asyncio issues.
    """
    if sys.platform == "win32":
        try:
            # Set the event loop policy to use SelectorEventLoop on Windows
            # This prevents ProactorEventLoop socket issues
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            logger.info("✅ Windows asyncio policy set to SelectorEventLoop")
        except Exception as e:
            logger.warning(f"⚠️ Could not set Windows asyncio policy: {e}")
            # Fallback: try to suppress the specific warnings
            warnings.filterwarnings("ignore", category=DeprecationWarning, module="asyncio")
            warnings.filterwarnings("ignore", message=".*ProactorBasePipeTransport.*")
    else:
        logger.debug("Non-Windows platform, skipping Windows asyncio setup")

def get_safe_event_loop() -> Optional[asyncio.AbstractEventLoop]:
    """
    Get a safe event loop that handles Windows-specific issues.
    Returns None if no event loop is running.
    """
    try:
        loop = asyncio.get_running_loop()
        return loop
    except RuntimeError:
        # No event loop running
        return None
    except Exception as e:
        logger.warning(f"⚠️ Error getting event loop: {e}")
        return None

def create_safe_task(coro, loop: Optional[asyncio.AbstractEventLoop] = None):
    """
    Create a task safely with proper error handling for Windows.
    """
    if loop is None:
        loop = get_safe_event_loop()
    
    if loop is None:
        logger.warning("⚠️ No event loop available, running coroutine directly")
        try:
            return asyncio.run(coro)
        except Exception as e:
            logger.error(f"❌ Error running coroutine directly: {e}")
            return None
    
    try:
        task = loop.create_task(coro)
        # Add error handling callback
        task.add_done_callback(lambda t: logger.error(f"❌ Task failed: {t.exception()}") if t.exception() else None)
        return task
    except Exception as e:
        logger.error(f"❌ Error creating task: {e}")
        return None

def safe_close_session(session):
    """
    Safely close a requests session to prevent socket leaks.
    """
    if session is not None:
        try:
            session.close()
            logger.debug("✅ Session closed successfully")
        except Exception as e:
            logger.warning(f"⚠️ Error closing session: {e}")

def is_session_closed(session):
    """
    Check if a requests session is closed.
    """
    if session is None:
        return True
    try:
        # Check if the session has a closed attribute
        if hasattr(session, 'closed'):
            return session.closed
        # If no closed attribute, check if the adapter pool is closed
        if hasattr(session, 'adapters'):
            for adapter in session.adapters.values():
                if hasattr(adapter, 'poolmanager') and hasattr(adapter.poolmanager, 'closed'):
                    return adapter.poolmanager.closed
        return False
    except Exception:
        return False

def setup_asyncio_logging():
    """
    Setup asyncio logging to suppress Windows-specific warnings.
    """
    # Suppress specific asyncio warnings that are common on Windows
    logging.getLogger('asyncio').setLevel(logging.WARNING)
    
    # Suppress ProactorBasePipeTransport warnings
    warnings.filterwarnings("ignore", message=".*ProactorBasePipeTransport.*")
    warnings.filterwarnings("ignore", message=".*_call_connection_lost.*")
    
    logger.info("✅ Asyncio logging configured for Windows compatibility")
