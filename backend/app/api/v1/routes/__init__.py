"""
Version 1 routers, mounted under ``/api/v1``. Health probes are unversioned (``app.api.health``).
"""

# Third-party imports
from fastapi import APIRouter

# Local imports
from .admin import router as admin_router
from .chat import router as chat_router

#: Current API version prefix; breaking changes go to ``/api/v2``.
API_V1_PREFIX = "/api/v1"

api_v1_router = APIRouter(prefix=API_V1_PREFIX)
api_v1_router.include_router(chat_router)
api_v1_router.include_router(admin_router)

__all__ = ["api_v1_router"]
