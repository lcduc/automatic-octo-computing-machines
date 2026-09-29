"""
SQL tool registry (TOOL-01): predefined, parameterized queries over the client's business database.

Definitions are written per client by the integrator (``manage.py sync-sql-tools``);
admins only switch tools on and off (TOOL-08). The LLM never writes SQL: it picks
a tool and fills validated arguments (checklist Invariant 2).
"""

# Standard library imports
from datetime import datetime
from typing import Any, Dict, List, Optional

# Third-party imports
from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

# Local imports
from .base import Base, updated_at_column


class SqlToolDefinition(Base):
    """One tool the model may call."""

    __tablename__ = "sql_tools"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: What the model reads to decide when to call it (Vietnamese + English examples).
    description: Mapped[str] = mapped_column(Text, nullable=False)
    #: JSON Schema of the arguments (see core/agent/tools/tool_arguments.py).
    args_schema: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    #: ``anonymous`` or a host tier (``user``, ``premium``…); lower tiers never see the tool.
    required_tier: Mapped[str] = mapped_column(String(16), nullable=False, default="anonymous")
    #: SELECT with bound parameters only (``:name``); ``:user_id`` is bound from the verified caller.
    sql_template: Mapped[str] = mapped_column(Text, nullable=False)
    #: Result columns returned to the model; any other column is dropped.
    allowed_columns: Mapped[List[str]] = mapped_column(JSONB, nullable=False)
    #: Returned columns shown only by their last characters (phones, account numbers).
    masked_columns: Mapped[List[str]] = mapped_column(JSONB, nullable=False, default=list)
    row_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = updated_at_column()
