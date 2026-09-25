"""
Liveness and readiness probes (unauthenticated, no internal details exposed).
"""

# Third-party imports
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

# Local imports
from api.container import AppContainer
from api.dependencies import get_container

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("/live", summary="The process is up")
async def live() -> dict:
    """Always 200 while the server is running."""
    return {"status": "ok"}


@router.get("/ready", summary="Ready to answer chats")
async def ready(container: AppContainer = Depends(get_container)) -> JSONResponse:
    """200 when the database answers and services are built; 503 otherwise."""
    checks = {
        "database": await container.database.ping(),
        "chat_pipeline": container.pipeline is not None,
    }
    healthy = all(checks.values())
    return JSONResponse({"status": "ok" if healthy else "unavailable", "checks": checks}, status_code=200 if healthy else 503)
