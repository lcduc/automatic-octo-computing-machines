"""
Pydantic model for one audit trail record - the durable log of an answered chat turn.
Data class only; writing it to disk is :class:`AuditTrailService`'s job.
"""

# Standard library imports
from datetime import datetime
from typing import Optional

# Third-party imports
from pydantic import BaseModel, Field


class AuditEntry(BaseModel):
    """One answered chat turn: what was asked, retrieved, and answered."""

    timestamp: datetime = Field(default_factory=datetime.now, description="When the turn was answered")
    query_id: str = Field(..., description="Short stable identifier for the query")
    query: str = Field(..., description="Original user query")
    rewritten_query: Optional[str] = Field(
        None, description="Standalone query used for retrieval, if different from ``query``"
    )
    response: str = Field(..., description="Text returned to the user")
    confidence_score: float = Field(..., description="Overall confidence score (0.0-1.0)")
    confidence_level: str = Field(..., description="Human-readable confidence level")
    source_count: int = Field(..., description="Number of retrieved chunks used as context")
    cached: bool = Field(..., description="Whether the response was served from cache")
    latency_ms: float = Field(..., description="Wall-clock time to answer, in milliseconds")
    success: bool = Field(..., description="Whether the turn completed without error")
    error: Optional[str] = Field(None, description="Error text when ``success`` is False")
    intent_ms: Optional[float] = Field(
        None, description="Time spent classifying rag/action intent, in milliseconds (tool-calling only)"
    )
    retrieval_ms: Optional[float] = Field(
        None, description="Time spent on hybrid search + context assembly, in milliseconds"
    )
    generation_ms: Optional[float] = Field(
        None, description="Time spent generating the LLM response (cache lookup included), in milliseconds"
    )
