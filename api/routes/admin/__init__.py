"""
Admin (management web) routes, mounted under ``/api/v1/admin``.
"""

# Third-party imports
from fastapi import APIRouter

# Local imports
from .auth import router as auth_router
from .configuration import router as configuration_router
from .conversations import router as conversations_router
from .knowledge import router as knowledge_router
from .monitoring import router as monitoring_router

router = APIRouter(prefix="/admin")
for child in (auth_router, knowledge_router, conversations_router, monitoring_router, configuration_router):
    router.include_router(child)
