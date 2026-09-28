"""
ORM table definitions. Importing this package registers every table on ``Base.metadata``.
"""

from .access_tables import AdminUser, ApiKey, AppSetting
from .audit_tables import AdminAuditEntry
from .base import Base
from .conversation_tables import Conversation, Feedback, HandoffRequest, Message, TokenUsage
from .knowledge_tables import KnowledgeChunk, KnowledgeDocument, KnowledgeSource

__all__ = [
    "Base",
    "AdminAuditEntry",
    "AdminUser",
    "ApiKey",
    "AppSetting",
    "Conversation",
    "Feedback",
    "HandoffRequest",
    "Message",
    "TokenUsage",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "KnowledgeSource",
]
