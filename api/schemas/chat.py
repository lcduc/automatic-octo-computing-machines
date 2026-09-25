"""
Public chat API contract (used by the embeddable widget through its server).
"""

# Standard library imports
import uuid
from datetime import datetime
from typing import List, Literal, Optional

# Third-party imports
from pydantic import BaseModel, Field, field_validator

# Local imports
from config.settings import Config
from .common import ApiModel

#: Source filters accepted per request.
MAX_SOURCE_FILTERS = 10
MAX_FEEDBACK_COMMENT = 1000


class ChatRequest(BaseModel):
    """One user message."""

    message: str = Field(..., min_length=1, max_length=Config.Chat.MAX_MESSAGE_LENGTH())
    conversation_id: Optional[uuid.UUID] = Field(
        None, description="Continue this conversation; omit to start a new one."
    )
    sources: Optional[List[str]] = Field(
        None, max_length=MAX_SOURCE_FILTERS, description="Only search these knowledge sources."
    )

    @field_validator("message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value


class Citation(BaseModel):
    """A knowledge document the answer is based on."""

    document_id: str
    chunk_id: str
    title: str
    source: str
    url: Optional[str] = None
    score: float


class ChatAnswer(BaseModel):
    """Complete answer of a non-streaming turn (same fields as the stream's ``done`` event)."""

    conversation_id: uuid.UUID
    message_id: uuid.UUID
    outcome: Literal["answered", "smalltalk", "denied", "handoff", "blocked", "error"]
    text: str
    citations: List[Citation]
    confidence: Optional[float] = None
    cached: bool = False
    handoff_id: Optional[uuid.UUID] = None


class FeedbackRequest(BaseModel):
    """A visitor's rating of one assistant message."""

    message_id: uuid.UUID
    rating: Literal[1, -1]
    comment: Optional[str] = Field(None, max_length=MAX_FEEDBACK_COMMENT)


class ConversationMessage(ApiModel):
    """A message as shown back to the visitor who wrote it."""

    id: uuid.UUID
    role: str
    content: str
    outcome: Optional[str] = None
    citations: List[Citation] = []
    created_at: datetime
    feedback_rating: Optional[int] = None


class ConversationHistory(BaseModel):
    """A visitor's conversation, for restoring the widget after a reload."""

    id: uuid.UUID
    status: str
    messages: List[ConversationMessage]


class WidgetConfig(BaseModel):
    """Public look-and-feel of the widget, set in the admin web."""

    title: str
    welcome_message: str
    primary_color: str
    suggested_questions: List[str]


class TranscriptionResponse(BaseModel):
    """Text transcribed from a voice message."""

    text: str
