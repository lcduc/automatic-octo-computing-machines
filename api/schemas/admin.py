"""
Admin (management web) contract: accounts, API keys, settings, conversations,
feedback, handoffs, usage, logs and system status.
"""

# Standard library imports
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional

# Third-party imports
from pydantic import BaseModel, Field

# Local imports
from services.handoff_service import mask_email, mask_phone
from .chat import Citation
from .common import ApiModel

AdminRole = Literal["owner", "editor", "viewer", "support_agent"]
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


#: Scopes an API key can carry (see core/storage/tables/access_tables.py).
ApiKeyScope = Literal["chat", "documents:write", "conversations:read", "admin:read"]


class ApiKeyOut(ApiModel):
    """An API key without its secret."""

    id: uuid.UUID
    name: str
    key_prefix: str
    scopes: List[str]
    created_at: datetime
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    rate_limit_per_minute: int
    rotated_from_id: Optional[uuid.UUID] = None


class ApiKeyCreate(BaseModel):
    """New server-to-server API key."""

    name: str = Field(..., min_length=1, max_length=128)
    scopes: List[ApiKeyScope] = Field(..., min_length=1)
    rate_limit_per_minute: int = Field(60, ge=1, le=10_000)
    #: Days until the key stops working; omitted = no expiry.
    expires_in_days: Optional[int] = Field(None, ge=1, le=3650)


class ApiKeyRotate(BaseModel):
    """Replace a key; the old one keeps working for ``grace_days`` (0 = revoke it now)."""

    grace_days: int = Field(7, ge=0, le=90)


class ApiKeyCreated(ApiKeyOut):
    """A freshly issued key; ``key`` is shown this one time only."""

    key: str


# ---------------------------------------------------------------- SQL tools


class SqlToolOut(ApiModel):
    """A SQL tool as the admin web lists it (its SQL is shown for review, never edited here)."""

    name: str
    description: str
    required_tier: str
    sql_template: str
    allowed_columns: List[str]
    masked_columns: List[str]
    row_limit: int
    enabled: bool
    updated_by: Optional[str] = None
    updated_at: datetime


class SqlToolUpdate(BaseModel):
    """Switch a tool on or off (TOOL-08)."""

    enabled: bool


# ---------------------------------------------------------------- prices


class ModelPriceIn(BaseModel):
    """What one model costs, in USD per million tokens."""

    input_usd_per_million: Decimal = Field(..., ge=0, le=10_000, decimal_places=6)
    output_usd_per_million: Decimal = Field(..., ge=0, le=10_000, decimal_places=6)


class ModelPriceOut(ApiModel):
    """A model's price as stored."""

    model: str
    input_usd_per_million: Decimal
    output_usd_per_million: Decimal
    updated_by: Optional[str] = None
    updated_at: datetime


# ---------------------------------------------------------------- settings


#: Provider model ids ("gpt-5-mini", "claude-sonnet-5", "models/gemini-3.6-flash", ...).
MODEL_NAME_PATTERN = r"^[A-Za-z0-9._:/\-]+$"
MAX_MODEL_NAME = 100
#: Upper bound for top-k and context chunks set from the admin web.
MAX_RETRIEVAL_CHUNKS = 20
#: Upper bounds for limits set from the admin web.
MAX_REQUEST_LIMIT = 100_000
MAX_TOKEN_BUDGET = 1_000_000_000
MAX_SPEND_CAP_USD = 1_000_000
MAX_HOLIDAYS = 100
MAX_TICKET_REPLY_HOURS = 240
MAX_HANDOFF_TOPICS = 100


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
    chat_model: Optional[str] = Field(None, max_length=MAX_MODEL_NAME, pattern=MODEL_NAME_PATTERN)
    light_model: Optional[str] = Field(None, max_length=MAX_MODEL_NAME, pattern=MODEL_NAME_PATTERN)
    similarity_threshold: Optional[float] = Field(None, ge=0.0, le=1.0)
    semantic_weight: Optional[float] = Field(None, ge=0.0, le=1.0)
    retrieval_top_k: Optional[int] = Field(None, ge=1, le=MAX_RETRIEVAL_CHUNKS)
    max_context_chunks: Optional[int] = Field(None, ge=1, le=MAX_RETRIEVAL_CHUNKS)
    # Limits per tier (0 = unlimited) and the monthly spend cap (0 = no cap).
    limit_anonymous_per_minute: Optional[int] = Field(None, ge=0, le=MAX_REQUEST_LIMIT)
    limit_anonymous_per_hour: Optional[int] = Field(None, ge=0, le=MAX_REQUEST_LIMIT)
    tokens_anonymous_per_day: Optional[int] = Field(None, ge=0, le=MAX_TOKEN_BUDGET)
    limit_user_per_minute: Optional[int] = Field(None, ge=0, le=MAX_REQUEST_LIMIT)
    limit_user_per_hour: Optional[int] = Field(None, ge=0, le=MAX_REQUEST_LIMIT)
    tokens_user_per_day: Optional[int] = Field(None, ge=0, le=MAX_TOKEN_BUDGET)
    tokens_ip_per_day: Optional[int] = Field(None, ge=0, le=MAX_TOKEN_BUDGET)
    spend_cap_monthly_usd: Optional[float] = Field(None, ge=0, le=MAX_SPEND_CAP_USD)
    spend_anonymous_cutoff_ratio: Optional[float] = Field(None, ge=0.0, le=1.0)
    # Support calendar (HND-07) and handoff triggers (HND-06), validated by SettingsService.
    support_hours: Optional[Dict[str, str]] = None
    support_holidays: Optional[List[str]] = Field(None, max_length=MAX_HOLIDAYS)
    ticket_reply_hours: Optional[float] = Field(None, gt=0, le=MAX_TICKET_REPLY_HOURS)
    handoff_topics: Optional[List[str]] = Field(None, max_length=MAX_HANDOFF_TOPICS)


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


HandoffStatusValue = Literal["open", "assigned", "answered", "closed"]


class HandoffOut(BaseModel):
    """A support ticket; contact details are masked (ADM-06)."""

    id: uuid.UUID
    conversation_id: uuid.UUID
    message_id: Optional[uuid.UUID] = None
    reason: str
    status: str
    note: Optional[str] = None
    signed_in: bool
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    has_contact: bool
    consent_at: Optional[datetime] = None
    details: Optional[str] = None
    assigned_to: Optional[str] = None
    answer: Optional[str] = None
    answered_at: Optional[datetime] = None
    emailed_at: Optional[datetime] = None
    due_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_request(cls, request) -> "HandoffOut":
        """Build from a ``HandoffRequest``, masking the contact."""
        return cls(
            id=request.id, conversation_id=request.conversation_id, message_id=request.message_id,
            reason=request.reason, status=request.status, note=request.note, signed_in=request.user_id is not None,
            contact_email=mask_email(request.contact_email), contact_phone=mask_phone(request.contact_phone),
            has_contact=bool(request.contact_email or request.contact_phone), consent_at=request.consent_at,
            details=request.details, assigned_to=request.assigned_to, answer=request.answer,
            answered_at=request.answered_at, emailed_at=request.emailed_at, due_at=request.due_at,
            closed_at=request.closed_at, created_at=request.created_at, updated_at=request.updated_at,
        )


class HandoffUpdate(BaseModel):
    """Assign, re-open or close a ticket, or change its internal note."""

    status: Optional[HandoffStatusValue] = None
    note: Optional[str] = Field(None, max_length=2000)
    #: An admin e-mail, or "" to unassign.
    assigned_to: Optional[str] = Field(None, max_length=255)


class HandoffAnswer(BaseModel):
    """The support team's reply to the visitor."""

    text: str = Field(..., min_length=1, max_length=5000)


class HandoffContactOut(BaseModel):
    """Unmasked contact details (owners only; audit-logged)."""

    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


# ---------------------------------------------------------------- observability


class LogEntry(BaseModel):
    """One application log record."""

    ts: str
    level: str
    logger: str
    message: str
    request_id: str = "-"
    exception: Optional[str] = None


class IngestionQueueStatus(BaseModel):
    """Uploads waiting for or being processed by the ingestion worker."""

    pending: int = Field(description="Uploads not yet ready or failed (includes in_progress)")
    in_progress: int = Field(description="Uploads a live worker is parsing right now")
    oldest_pending_seconds: Optional[float] = Field(
        None, description="How long the oldest pending upload has waited; growing with in_progress=0 means the worker is down"
    )


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
    ingestion_queue: IngestionQueueStatus


# ---------------------------------------------------------------- audit


class AuditEntryOut(ApiModel):
    """One audited admin write or sign-in attempt."""

    id: uuid.UUID
    created_at: datetime
    actor_id: Optional[uuid.UUID] = None
    actor_email: Optional[str] = None
    actor_role: Optional[str] = None
    method: str
    path: str
    status_code: int
    request_id: Optional[str] = None
    client_ip: Optional[str] = None
    request_body: Optional[Any] = None
    response_body: Optional[Any] = None
