"""
Chat endpoint - RAG-powered conversation API with optional history support.
"""

# Standard library imports
import logging
from typing import AsyncGenerator, Dict, List, Optional

# Third-party imports
from fastapi import APIRouter, Body, Depends
from fastapi.responses import StreamingResponse

# Local imports
from api.dependencies import get_chat_service
from config.settings import Config
from models.responses import BatchChatRequest, BatchChatResponse, ChatRequest
from services import ChatService

router = APIRouter()
logger = logging.getLogger(__name__)

#: Headers that keep SSE streams from being buffered by proxies.
STREAM_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


def _resolve_history(client_history: Optional[List[Dict[str, str]]]) -> Optional[List[Dict[str, str]]]:
    """
    Decide what conversation history (if any) this turn should use.

    There is no server-side session store — the caller is expected to resend
    its own running history each turn (as the bundled Streamlit frontend
    does). This only enforces the on/off switch; the length cap itself is
    applied downstream in ``ChatService`` via ``MAX_HISTORY_TURNS`` so it
    stays in one place.

    Args:
        client_history: History supplied in the request body, if any.

    Returns:
        The history to use, or ``None`` when history is disabled entirely.
    """
    if not Config.Chat.ENABLE_HISTORY():
        return None
    return client_history or []


@router.post("/")
async def chat(
    request: ChatRequest = Body(...),
    chat_service: ChatService = Depends(get_chat_service),
) -> StreamingResponse:
    """
    Answer a query, streaming the generated tokens back to the caller.

    Args:
        request: Body carrying the user query and optional conversation history.
        chat_service: Injected RAG chat service.

    Returns:
        A ``text/event-stream`` response of answer tokens. Failures are streamed
        as a single ``[ERROR] ...`` token rather than raising, so an
        already-started response is never truncated without explanation.
    """

    async def token_generator() -> AsyncGenerator[str, None]:
        try:
            async for token in chat_service.stream_chat_with_memory(
                request.query, custom_history=_resolve_history(request.history)
            ):
                yield token
        except Exception as exc:
            logger.exception("Error while streaming chat response")
            yield f"[ERROR] {exc}"

    return StreamingResponse(
        token_generator(),
        media_type="text/event-stream",
        headers=STREAM_HEADERS,
    )


@router.post("/batch", response_model=BatchChatResponse)
async def chat_batch(
    request: BatchChatRequest = Body(...),
    chat_service: ChatService = Depends(get_chat_service),
) -> BatchChatResponse:
    """
    Answer several independent queries concurrently.

    Each query is retrieved, generated and cached independently — there is no
    shared conversation history between them and no streaming (the full batch
    returns as one JSON response once every query has finished). Useful for
    bulk QA, running an eval set, or precomputing answers to a FAQ list.

    Args:
        request: Body carrying the list of queries (capped at
            ``CHAT_BATCH_MAX_QUERIES``).
        chat_service: Injected RAG chat service.

    Returns:
        One result per input query, in the original order. A failure on one
        query does not affect the others.
    """
    results = await chat_service.batch_chat(request.queries)
    return BatchChatResponse(results=results)
