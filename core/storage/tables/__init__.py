"""
ORM table definitions. Importing this package registers every table on ``Base.metadata``.
"""

from .access_tables import AdminUser, ApiKey, AppSetting, HostTokenUse
from .audit_tables import AdminAuditEntry
from .base import Base
from .conversation_tables import Conversation, Feedback, HandoffRequest, Message, TokenUsage
from .knowledge_tables import KnowledgeChunk, KnowledgeDocument, KnowledgeSource
from .observability_tables import AlertState, DailyMetrics, MessageTrace
from .tool_tables import SqlToolDefinition
from .usage_tables import ModelPrice, UsageCounter

__all__ = [
    "Base",
    "AdminAuditEntry",
    "AdminUser",
    "AlertState",
    "ApiKey",
    "AppSetting",
    "HostTokenUse",
    "Conversation",
    "DailyMetrics",
    "Feedback",
    "HandoffRequest",
    "Message",
    "MessageTrace",
    "TokenUsage",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "KnowledgeSource",
    "ModelPrice",
    "SqlToolDefinition",
    "UsageCounter",
]
