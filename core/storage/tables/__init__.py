"""
ORM table definitions. Importing this package registers every table on ``Base.metadata``.
"""

from .access_tables import AdminUser, ApiKey, AppSetting, HostTokenUse
from .audit_tables import AdminAuditEntry
from .base import Base
from .conversation_tables import Conversation, Feedback, HandoffRequest, Message, TokenUsage
from .knowledge_tables import KnowledgeChunk, KnowledgeDocument, KnowledgeSource
from .usage_tables import ModelPrice, UsageCounter

__all__ = [
    "Base",
    "AdminAuditEntry",
    "AdminUser",
    "ApiKey",
    "AppSetting",
    "HostTokenUse",
    "Conversation",
    "Feedback",
    "HandoffRequest",
    "Message",
    "TokenUsage",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "KnowledgeSource",
    "ModelPrice",
    "UsageCounter",
]
