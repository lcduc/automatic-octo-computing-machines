"""
Data classes exchanged between the chat service and the chat pipeline.
"""

# Standard library imports
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

# Local imports
from .llm import LLMUsage

FALLBACK_MODE_DENY = "deny"
FALLBACK_MODE_HANDOFF = "handoff"
FALLBACK_MODES = (FALLBACK_MODE_DENY, FALLBACK_MODE_HANDOFF)


class TurnOutcome(str, Enum):
    """How an assistant turn ended; stored on the message and shown in the admin web."""

    ANSWERED = "answered"
    #: Canned reply to a greeting/thanks — no retrieval, no LLM call.
    SMALLTALK = "smalltalk"
    #: No relevant knowledge; replied with the configured deny message (no LLM call).
    DENIED = "denied"
    #: Transferred to a human agent (no LLM call).
    HANDOFF = "handoff"
    #: Rejected by the guardrails (no LLM call).
    BLOCKED = "blocked"
    ERROR = "error"


class HandoffReason(str, Enum):
    """Why a conversation was handed to a human."""

    NO_KNOWLEDGE = "no_knowledge"
    USER_REQUEST = "user_request"


@dataclass(frozen=True)
class ChatPolicy:
    """Runtime chat behaviour, editable by admins without a restart."""

    fallback_mode: str
    deny_message: str
    handoff_message: str
    guard_block_message: str
    greeting_message: str
    thanks_message: str
    #: Extra system-prompt instructions (persona, scope, tone); may be empty.
    assistant_instructions: str = ""


@dataclass(frozen=True)
class TurnRequest:
    """Everything the pipeline needs to answer one user message."""

    #: The user's message, already PII-redacted when redaction is enabled.
    query: str
    #: Prior messages (oldest first) as ``{"role", "content"}`` dicts.
    history: List[Dict[str, str]]
    policy: ChatPolicy
    #: Restrict retrieval to these source names; ``None`` searches all.
    sources: Optional[Sequence[str]] = None


@dataclass(frozen=True)
class TurnDelta:
    """A piece of answer text to forward to the client."""

    text: str


@dataclass(frozen=True)
class TurnUsage:
    """Tokens consumed by one LLM call during the turn (never sent to the client)."""

    purpose: str
    usage: LLMUsage


@dataclass
class TurnResult:
    """Terminal event of a turn: the full answer and its diagnostics."""

    outcome: TurnOutcome
    text: str
    citations: List[Dict[str, Any]] = field(default_factory=list)
    confidence: Optional[float] = None
    cached: bool = False
    model: Optional[str] = None
    rewritten_query: Optional[str] = None
    guard_reason: Optional[str] = None
    handoff_reason: Optional[HandoffReason] = None
