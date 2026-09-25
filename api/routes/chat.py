"""
Public chat API (v1): used by client frontends through their own server.

Every route needs ``X-API-Key``; visitor-scoped routes also need ``X-End-User-Id``.
"""

# Standard library imports
import logging
import uuid

# Third-party imports
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

# Local imports
from api.dependencies import get_container, require_chat_caller, require_client_key
from api.schemas.chat import (
    ChatAnswer,
    ChatRequest,
    ConversationHistory,
    ConversationMessage,
    FeedbackRequest,
    TranscriptionResponse,
    WidgetConfig,
)
from api.schemas.common import MessageResponse
from api.sse import STREAM_HEADERS, sse_stream
from api.container import AppContainer
from config.settings import Config
from models.caller import ChatCaller

router = APIRouter(tags=["Chat"])
logger = logging.getLogger(__name__)


@router.post("/chat/stream", summary="Ask a question; answer streamed as Server-Sent Events")
async def chat_stream(
    body: ChatRequest,
    caller: ChatCaller = Depends(require_chat_caller),
    container: AppContainer = Depends(get_container),
) -> StreamingResponse:
    """
    Stream the answer to one message.

    Events: ``meta`` (conversation_id, message_id), ``delta`` (text pieces),
    ``done`` (outcome, full text, citations, handoff_id) or ``error``.
    Quota and validation failures are returned as normal HTTP errors before
    the stream starts.
    """
    turn = await container.chat.prepare(caller, body.message, body.conversation_id, body.sources)
    return StreamingResponse(
        sse_stream(container.chat.stream(turn)), media_type="text/event-stream", headers=STREAM_HEADERS
    )


@router.post("/chat", response_model=ChatAnswer, summary="Ask a question; complete answer as JSON")
async def chat(
    body: ChatRequest,
    caller: ChatCaller = Depends(require_chat_caller),
    container: AppContainer = Depends(get_container),
) -> ChatAnswer:
    """Non-streaming counterpart of ``/chat/stream`` for server-to-server integrations."""
    turn = await container.chat.prepare(caller, body.message, body.conversation_id, body.sources)
    return ChatAnswer(**await container.chat.answer(turn))


@router.get("/conversations/{conversation_id}", response_model=ConversationHistory)
async def get_conversation(
    conversation_id: uuid.UUID,
    caller: ChatCaller = Depends(require_chat_caller),
    container: AppContainer = Depends(get_container),
) -> ConversationHistory:
    """The visitor's own conversation, to restore the widget after a page reload."""
    conversation = await container.conversations.visitor_conversation(conversation_id, caller.end_user_id)
    return ConversationHistory(
        id=conversation.id,
        status=conversation.status,
        messages=[
            ConversationMessage(
                id=message.id,
                role=message.role,
                content=message.content,
                outcome=message.outcome,
                citations=message.citations or [],
                created_at=message.created_at,
                feedback_rating=message.feedback.rating if message.feedback else None,
            )
            for message in conversation.messages
        ],
    )


@router.post("/feedback", response_model=MessageResponse)
async def submit_feedback(
    body: FeedbackRequest,
    caller: ChatCaller = Depends(require_chat_caller),
    container: AppContainer = Depends(get_container),
) -> MessageResponse:
    """Rate an assistant answer (thumbs up/down, optional comment)."""
    await container.conversations.submit_feedback(body.message_id, caller.end_user_id, body.rating, body.comment)
    return MessageResponse(message="Feedback recorded")


@router.get("/widget/config", response_model=WidgetConfig, dependencies=[Depends(require_client_key)])
async def widget_config(container: AppContainer = Depends(get_container)) -> WidgetConfig:
    """Title, welcome text, colour and suggested questions configured in the admin web."""
    values = container.settings.public_widget_config()
    return WidgetConfig(
        title=values["widget_title"],
        welcome_message=values["widget_welcome_message"],
        primary_color=values["widget_primary_color"],
        suggested_questions=values["widget_suggested_questions"],
    )


@router.post("/chat/transcribe", response_model=TranscriptionResponse)
async def transcribe(
    audio: UploadFile = File(...),
    caller: ChatCaller = Depends(require_chat_caller),
    container: AppContainer = Depends(get_container),
) -> TranscriptionResponse:
    """Transcribe a recorded voice question (needs ``OPENAI_API_KEY``)."""
    audio_bytes = await audio.read(Config.File.MAX_AUDIO_FILE_SIZE() + 1)
    if not audio_bytes:
        raise HTTPException(400, "Empty audio upload")
    if len(audio_bytes) > Config.File.MAX_AUDIO_FILE_SIZE():
        raise HTTPException(413, "Audio file too large")
    text = await container.transcription.transcribe(
        audio_bytes, audio.filename or "recording.webm", audio.content_type or "audio/webm"
    )
    return TranscriptionResponse(text=text)
