"""
How long each kind of personal data is kept (PRV-04); editable per client by the owner.
"""

# Standard library imports
from dataclasses import dataclass

#: Defaults agreed for launch, in days.
DEFAULT_CHAT_DAYS = 365
DEFAULT_ANONYMOUS_CHAT_DAYS = 90
DEFAULT_TRACE_DAYS = 90
DEFAULT_TICKET_DAYS = 730
DEFAULT_AUDIT_DAYS = 1095
#: Shortest period an owner may set, so a typo cannot wipe recent data.
MIN_RETENTION_DAYS = 7
#: Longest period (ten years).
MAX_RETENTION_DAYS = 3650
#: The audit log is never deleted younger than this, whatever the setting (enforced by a trigger).
MIN_AUDIT_RETENTION_DAYS = 365


@dataclass(frozen=True)
class RetentionPolicy:
    """Days after the last activity (conversations) or creation (the rest) before deletion."""

    #: Conversations of signed-in users.
    chat_days: int
    #: Conversations never tied to a signed-in user.
    anonymous_chat_days: int
    #: Per-answer traces and per-call token usage (the daily rollup keeps the totals).
    trace_days: int
    #: Support tickets, counted from when they were opened.
    ticket_days: int
    #: Admin audit log.
    audit_days: int
