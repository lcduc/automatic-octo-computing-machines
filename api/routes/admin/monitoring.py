"""
Admin monitoring: usage statistics, the live usage feed, logs and system status.
"""

# Standard library imports
import asyncio
import time
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional

# Third-party imports
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

# Local imports
from api.container import AppContainer
from api.dependencies import READ_ROLES, WRITE_ROLES, get_container, require_admin
from api.schemas.admin import LogEntry, SystemStatus
from api.schemas.common import MessageResponse
from api.sse import STREAM_HEADERS, sse_stream
from config.settings import Config

router = APIRouter(tags=["Admin: monitoring"])
read_access = Depends(require_admin(READ_ROLES))

APP_VERSION = "3.0.0"
MAX_SUMMARY_DAYS = 90


@router.get("/usage/summary", dependencies=[read_access])
async def usage_summary(
    days: int = Query(7, ge=1, le=MAX_SUMMARY_DAYS), container: AppContainer = Depends(get_container)
) -> Dict[str, Any]:
    """Tokens per day and model, per purpose, answer outcomes, feedback and latency."""
    return await container.usage.summary(days)


@router.get("/usage/live", dependencies=[read_access], summary="Live feed of chat turns and handoffs (SSE)")
async def usage_live(container: AppContainer = Depends(get_container)) -> StreamingResponse:
    """Streams a ``turn`` event after every answered message and a ``handoff`` event per new request."""

    async def events() -> AsyncIterator[Dict[str, Any]]:
        queue = container.usage.subscribe()
        try:
            yield {"type": "hello", "ts": time.time()}
            while True:
                yield await queue.get()
        finally:
            container.usage.unsubscribe(queue)

    return StreamingResponse(sse_stream(events()), media_type="text/event-stream", headers=STREAM_HEADERS)


@router.get("/logs", response_model=List[LogEntry], dependencies=[read_access])
async def logs(
    level: str = Query("INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$"),
    request_id: Optional[str] = Query(None, max_length=64),
    contains: Optional[str] = Query(None, max_length=200),
    since: Optional[datetime] = None,
    limit: int = Query(200, ge=1, le=500),
    container: AppContainer = Depends(get_container),
) -> List[LogEntry]:
    """Recent application log entries, newest first (personal data already redacted)."""
    entries = await asyncio.to_thread(container.logs.query, level, request_id, contains, since, limit)
    return [LogEntry(**entry) for entry in entries]


@router.get("/system", response_model=SystemStatus, dependencies=[read_access])
async def system_status(container: AppContainer = Depends(get_container)) -> SystemStatus:
    """Health, index size, models and cache statistics."""
    snapshot = container.index.snapshot
    return SystemStatus(
        version=APP_VERSION,
        uptime_seconds=round(time.time() - container.started_at, 1),
        database=await container.database.ping(),
        knowledge_index_version=snapshot.version,
        indexed_chunks=len(snapshot.chunks),
        indexed_sources={name: int(len(indices)) for name, indices in snapshot.source_indices.items()},
        llm_provider=Config.LLM.LLM_PROVIDER(),
        llm_model=Config.LLM.ACTIVE_MODEL(),
        embedding_model=Config.LLM.EMBEDDING_MODEL(),
        reranker_loaded=container.reranker is not None,
        cache=container.pipeline.cache.get_stats(),
        fallback_mode=container.settings.all()["fallback_mode"],
    )


@router.post("/system/cache/clear", response_model=MessageResponse, dependencies=[Depends(require_admin(WRITE_ROLES))])
async def clear_cache(container: AppContainer = Depends(get_container)) -> MessageResponse:
    """Drop every cached answer."""
    removed = container.pipeline.cache.clear()
    return MessageResponse(message=f"Cleared {removed} cached answers")


@router.post("/system/reindex", response_model=MessageResponse, dependencies=[Depends(require_admin(WRITE_ROLES))])
async def reindex(container: AppContainer = Depends(get_container)) -> MessageResponse:
    """Rebuild the in-memory search index from the database."""
    snapshot = await container.index.refresh()
    return MessageResponse(message=f"Index rebuilt: {len(snapshot.chunks)} chunks")
