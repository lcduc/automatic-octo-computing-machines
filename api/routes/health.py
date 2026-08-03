"""
Health check and system status endpoints for monitoring and diagnostics.
"""

# Standard library imports
import logging
import time

# Third-party imports
import psutil
from fastapi import APIRouter
from pydantic import BaseModel, Field

# Local imports
from config.settings import Config
from core.infrastructure.caching.cache_service import get_cache_service
from core.storage.vector_stores import get_vector_store_provider
from models.responses import HealthResponse, StatusEnum
from utils.performance import get_performance_monitor

router = APIRouter()
logger = logging.getLogger(__name__)

#: API version reported by the health endpoints.
API_VERSION = "2.0.0"

#: Filesystem root inspected for disk usage; Windows resolves this to the drive.
DISK_USAGE_PATH = "/"

# Track server start time for uptime calculation
_start_time = time.time()


def _uptime_seconds() -> float:
    """Seconds elapsed since this worker started."""
    return time.time() - _start_time


@router.get("/", response_model=HealthResponse)
async def health_check():
    """
    Basic health check endpoint for load balancers and monitoring.
    Returns server status, version, and uptime information.
    """
    uptime = _uptime_seconds()
    uptime_str = (
        f"{int(uptime // 3600)}h {int((uptime % 3600) // 60)}m {int(uptime % 60)}s"
    )
    return HealthResponse(
        status=StatusEnum.SUCCESS,
        message="Enhanced RAG Chatbot API is running",
        version=API_VERSION,
        uptime=uptime_str,
    )


class SystemStatusResponse(BaseModel):
    """Resource usage and effective configuration for the running worker."""

    status: str = Field(..., description="Overall status of the worker")
    version: str = Field(..., description="API version")
    uptime_seconds: int = Field(..., description="Seconds since worker start")
    system: dict = Field(..., description="CPU, memory and disk usage")
    configuration: dict = Field(..., description="Effective runtime configuration")


@router.get("/status", response_model=SystemStatusResponse)
async def detailed_status():
    """
    Comprehensive system status endpoint with resource usage metrics.

    CPU is sampled without blocking (percentage since the previous sample), so
    this endpoint stays safe to poll from a load balancer.
    """
    try:
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(DISK_USAGE_PATH)
        return SystemStatusResponse(
            status="healthy",
            version=API_VERSION,
            uptime_seconds=int(_uptime_seconds()),
            system={
                "cpu_percent": psutil.cpu_percent(interval=None),
                "memory": {
                    "total": memory.total,
                    "available": memory.available,
                    "percent": memory.percent,
                },
                "disk": {
                    "total": disk.total,
                    "free": disk.free,
                    "percent": (disk.used / disk.total) * 100 if disk.total else 0,
                },
            },
            configuration={
                "host": Config.Server.HOST(),
                "port": Config.Server.PORT(),
                "debug": Config.Server.DEBUG(),
                "openai_model": Config.LLM.OPENAI_MODEL(),
                "embedding_model": Config.LLM.EMBEDDING_MODEL(),
                "reranker_model": Config.RAG.RERANKER_MODEL(),
                "max_file_size": Config.File.MAX_FILE_SIZE(),
                "chunks_dir": Config.Database.CHUNKS_DIR(),
                "vectors_dir": Config.Database.VECTORS_DIR(),
                "temp_dir": Config.Database.TEMP_DIR(),
                "knowledge_base_loaded": get_vector_store_provider().is_loaded,
            },
        )
    except Exception:
        logger.exception("Failed to collect system status")
        return SystemStatusResponse(
            status="error",
            version=API_VERSION,
            uptime_seconds=int(_uptime_seconds()),
            system={},
            configuration={},
        )


@router.get("/performance")
async def performance_metrics():
    """
    Get detailed performance metrics for the chatbot.
    Returns response times, cache hit rates, and system resource usage.
    """
    try:
        monitor = get_performance_monitor()
        return {
            "status": "success",
            "health_status": monitor.get_health_status(),
            "performance_metrics": monitor.get_performance_stats(),
            "timestamp": time.time(),
        }
    except Exception as exc:
        logger.exception("Failed to collect performance metrics")
        return {"status": "error", "error": str(exc), "timestamp": time.time()}


@router.get("/cache-stats")
async def cache_statistics():
    """
    Get cache statistics for the smart cache and the knowledge base.

    Reads the shared singletons directly rather than depending on the chat
    service, so monitoring never triggers model loading.
    """
    try:
        return {
            "status": "success",
            "cache_statistics": {
                "smart_cache": get_cache_service().get_stats(),
                "vector_store_cache": {
                    "loaded": get_vector_store_provider().is_loaded,
                },
                "performance_metrics": get_performance_monitor().get_performance_stats(),
            },
            "timestamp": time.time(),
        }
    except Exception as exc:
        logger.exception("Failed to collect cache statistics")
        return {"status": "error", "error": str(exc), "timestamp": time.time()}
