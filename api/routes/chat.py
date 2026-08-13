"""
Chat endpoint - RAG-powered conversation API with optional history support.
"""

# Standard library imports
import logging
from typing import AsyncGenerator, Dict, List, Optional

# Third-party imports
from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

# Local imports
from api.dependencies import get_chat_service
from config.settings import Config
from models.responses import (
    BatchChatRequest,
    BatchChatResponse,
    ChatRequest,
    StatusEnum,
    TranscriptionResponse,
)
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


@router.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe(
    audio: UploadFile = File(...),
    chat_service: ChatService = Depends(get_chat_service),
) -> TranscriptionResponse:
    """
    Transcribe a recorded audio clip to text so it can be sent as a chat query.

    Args:
        audio: Recorded voice query (wav/mp3/m4a/webm/...), capped at
            ``MAX_AUDIO_FILE_SIZE``.
        chat_service: Injected RAG chat service.

    Returns:
        The transcribed text, wrapped in the standard response envelope.
    """
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio upload.")
    if len(audio_bytes) > Config.File.MAX_AUDIO_FILE_SIZE():
        raise HTTPException(
            status_code=400,
            detail=(
                f"Audio file too large. Maximum "
                f"{Config.File.MAX_AUDIO_FILE_SIZE() / (1024 * 1024):.1f}MB allowed."
            ),
        )

    try:
        text = await chat_service.transcribe_audio(
            audio_bytes,
            audio.filename or "recording.wav",
            audio.content_type or "audio/wav",
        )
    except RuntimeError:
        logger.exception("Audio transcription unavailable")
        raise HTTPException(
            status_code=503, detail="Chat service is currently unavailable"
        )
    except Exception:
        logger.exception("Audio transcription failed")
        raise HTTPException(
            status_code=500,
            detail="Transcription failed. See server logs for details.",
        )

    return TranscriptionResponse(status=StatusEnum.SUCCESS, text=text)
