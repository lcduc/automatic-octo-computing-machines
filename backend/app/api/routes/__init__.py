"""
API routers: health probes at the root, everything else versioned under ``/api/v1``.
"""

# Third-party imports
from fastapi import APIRouter

# Local imports
from .admin import router as admin_router
from .chat import router as chat_router
from .health import router as health_router

#: Current API version prefix; breaking changes go to ``/api/v2``.
API_V1_PREFIX = "/api/v1"

api_v1_router = APIRouter(prefix=API_V1_PREFIX)
api_v1_router.include_router(chat_router)
api_v1_router.include_router(admin_router)

__all__ = ["api_v1_router", "health_router"]
