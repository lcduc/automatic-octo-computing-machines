"""
Health check and system status endpoints for monitoring and diagnostics.
"""

# Standard library imports
import os
import time

# Third-party imports
import psutil
from fastapi import APIRouter

# Local imports
from setting import Config
from models.responses import HealthResponse, StatusEnum
from pydantic import BaseModel, Field

router = APIRouter()

# Track server start time for uptime calculation
_start_time = time.time()


@router.get("/", response_model=HealthResponse)
async def health_check():
    """
    Basic health check endpoint for load balancers and monitoring.
    Returns server status, version, and uptime information.
    """
    # Calculate uptime in human-readable format
    uptime_seconds = time.time() - _start_time
    uptime_str = f"{int(uptime_seconds // 3600)}h {int((uptime_seconds % 3600) // 60)}m {int(uptime_seconds % 60)}s"

    return HealthResponse(
        status=StatusEnum.SUCCESS,
        message="Enhanced RAG Chatbot API is running",
        version="2.0.0",
        uptime=uptime_str,
    )


class SystemStatusResponse(BaseModel):
    status: str = Field(...)
    version: str = Field(...)
    uptime_seconds: int = Field(...)
    system: dict = Field(...)
    configuration: dict = Field(...)


@router.get("/status", response_model=SystemStatusResponse)
async def detailed_status():
    """
    Comprehensive system status endpoint with resource usage metrics.
    Provides CPU, memory, disk usage and configuration details.
    """
    try:
        # Get system resource information
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return SystemStatusResponse(
            status="healthy",
            version="2.0.0",
            uptime_seconds=int(time.time() - _start_time),
            system={
                "cpu_percent": psutil.cpu_percent(interval=1),
                "memory": {
                    "total": memory.total,
                    "available": memory.available,
                    "percent": memory.percent,
                },
                "disk": {
                    "total": disk.total,
                    "free": disk.free,
                    "percent": (disk.used / disk.total) * 100,
                },
            },
            configuration={
                "host": Config.HOST(),
                "port": Config.PORT(),
                "debug": Config.DEBUG(),
                "openai_model": Config.OPENAI_MODEL(),
                "max_file_size": Config.MAX_FILE_SIZE(),
                "chunks_dir": Config.CHUNKS_DIR(),
                "vectors_dir": Config.VECTORS_DIR(),
                "temp_dir": Config.TEMP_DIR(),
            },
        )
    except Exception as e:
        return SystemStatusResponse(
            status="error",
            version="2.0.0",
            uptime_seconds=int(time.time() - _start_time),
            system={},
            configuration={},
        )
