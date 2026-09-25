"""
Admin (management web) contract: accounts, API keys, settings, conversations,
feedback, handoffs, usage, logs and system status.
"""

# Standard library imports
import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

# Third-party imports
from pydantic import BaseModel, Field

# Local imports
from .chat import Citation
from .common import ApiModel

AdminRole = Literal["owner", "editor", "viewer"]
#: Deliberately loose e-mail shape check (accounts are created by owners, not self-service).
EMAIL_PATTERN = r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$"
MAX_CANNED_MESSAGE = 2000
MAX_INSTRUCTIONS = 4000
MAX_SUGGESTED_QUESTIONS = 6


# ---------------------------------------------------------------- accounts


class LoginRequest(BaseModel):
    """Admin credentials."""

    email: str = Field(..., pattern=EMAIL_PATTERN, max_length=320)
    password: str = Field(..., min_length=1, max_length=256)


class AdminOut(ApiModel):
    """An admin account."""

    id: uuid.UUID
    email: str
    role: str
    disabled: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None


class TokenResponse(BaseModel):
    """A new admin session."""

    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    admin: AdminOut


class AdminCreate(BaseModel):
    """New admin account (owner only)."""

    email: str = Field(..., pattern=EMAIL_PATTERN, max_length=320)
    password: str = Field(..., min_length=10, max_length=256)
    role: AdminRole = "viewer"


class AdminUpdate(BaseModel):
    """Role or enabled-state change (owner only)."""

    role: Optional[AdminRole] = None
    disabled: Optional[bool] = None


class PasswordChange(BaseModel):
    """Change of one's own password."""

    current_password: str = Field(..., min_length=1, max_length=256)
    new_password: str = Field(..., min_length=10, max_length=256)


# ---------------------------------------------------------------- API keys


class ApiKeyOut(ApiModel):
    """An API key without its secret."""

    id: uuid.UUID
    name: str
    key_prefix: str
    scopes: List[str]
    created_at: datetime
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None


class ApiKeyCreate(BaseModel):
    """New API key for a frontend."""

    name: str = Field(..., min_length=1, max_length=128)


class ApiKeyCreated(ApiKeyOut):
    """A freshly issued key; ``key`` is shown this one time only."""

    key: str


# ---------------------------------------------------------------- settings


class SettingsUpdate(BaseModel):
    """Runtime chat and widget settings; omitted fields are unchanged."""

    fallback_mode: Optional[Literal["deny", "handoff"]] = None
    deny_message: Optional[str] = Field(None, min_length=1, max_length=MAX_CANNED_MESSAGE)
    handoff_message: Optional[str] = Field(None, min_length=1, max_length=MAX_CANNED_MESSAGE)
    guard_block_message: Optional[str] = Field(None, min_length=1, max_length=MAX_CANNED_MESSAGE)
    greeting_message: Optional[str] = Field(None, min_length=1, max_length=MAX_CANNED_MESSAGE)
    thanks_message: Optional[str] = Field(None, min_length=1, max_length=MAX_CANNED_MESSAGE)
    assistant_instructions: Optional[str] = Field(None, max_length=MAX_INSTRUCTIONS)
    widget_title: Optional[str] = Field(None, min_length=1, max_length=80)
    widget_welcome_message: Optional[str] = Field(None, max_length=500)
    widget_primary_color: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    widget_suggested_questions: Optional[List[str]] = Field(None, max_length=MAX_SUGGESTED_QUESTIONS)


# ---------------------------------------------------------------- conversations


class ConversationSummary(ApiModel):
    """A conversation in the admin list."""

    id: uuid.UUID
    end_user_id: str
    channel: str
    status: str
    message_count: int
    created_at: datetime
    last_activity_at: datetime


class FeedbackOut(BaseModel):
    """A rating attached to a message."""

    rating: int
    comment: Optional[str] = None


class AdminMessage(BaseModel):
    """A message with its full diagnostics."""

    id: uuid.UUID
    role: str
    content: str
    outcome: Optional[str] = None
    citations: List[Citation] = []
    confidence: Optional[float] = None
    model: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: Optional[int] = None
    cached: bool = False
    guard_reason: Optional[str] = None
    request_id: Optional[str] = None
    created_at: datetime
    feedback: Optional[FeedbackOut] = None

    @classmethod
    def from_message(cls, message) -> "AdminMessage":
        """Build from a ``Message`` with its feedback loaded."""
        feedback = message.feedback
        return cls(
            id=message.id,
            role=message.role,
            content=message.content,
            outcome=message.outcome,
            citations=message.citations or [],
            confidence=message.confidence,
            model=message.model,
            prompt_tokens=message.prompt_tokens,
            completion_tokens=message.completion_tokens,
            latency_ms=message.latency_ms,
            cached=message.cached,
            guard_reason=message.guard_reason,
            request_id=message.request_id,
            created_at=message.created_at,
            feedback=FeedbackOut(rating=feedback.rating, comment=feedback.comment) if feedback else None,
        )


class ConversationDetail(ConversationSummary):
    """A conversation with every message."""

    messages: List[AdminMessage]


class FeedbackItem(BaseModel):
    """One entry of the feedback inbox."""

    id: uuid.UUID
    rating: int
    comment: Optional[str] = None
    created_at: datetime
    message_id: uuid.UUID
    conversation_id: uuid.UUID
    question: Optional[str] = None
    answer: str
    outcome: Optional[str] = None


# ---------------------------------------------------------------- handoffs


class HandoffOut(ApiModel):
    """A transfer-to-human request."""

    id: uuid.UUID
    conversation_id: uuid.UUID
    message_id: Optional[uuid.UUID] = None
    reason: str
    status: str
    note: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class HandoffUpdate(BaseModel):
    """Status change of a handoff request."""

    status: Literal["pending", "in_progress", "resolved"]
    note: Optional[str] = Field(None, max_length=2000)


# ---------------------------------------------------------------- observability


class LogEntry(BaseModel):
    """One application log record."""

    ts: str
    level: str
    logger: str
    message: str
    request_id: str = "-"
    exception: Optional[str] = None


class SystemStatus(BaseModel):
    """Runtime health and configuration overview."""

    version: str
    uptime_seconds: float
    database: bool
    knowledge_index_version: int
    indexed_chunks: int
    indexed_sources: Dict[str, int]
    llm_provider: str
    llm_model: str
    embedding_model: str
    reranker_loaded: bool
    cache: Dict[str, Any]
    fallback_mode: str
