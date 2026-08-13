"""
Model status endpoints for monitoring preloaded ML models.
"""

import logging
import time
from fastapi import APIRouter
from utils.model_preloader import get_model_preloader

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/models")
async def get_model_status():
    """
    Get status of preloaded ML models.
    """
    try:
        preloader = get_model_preloader()
        status = preloader.get_status()

        return {
            "status": "success",
            "model_status": status,
            "timestamp": time.time()
        }
    except Exception:
        logger.exception("Failed to read model preloader status")
        return {
            "status": "error",
            "error": "Failed to read model status. See server logs for details.",
            "timestamp": time.time()
        }
