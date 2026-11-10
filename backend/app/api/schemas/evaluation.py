"""
Request/response models of the admin eval-set routes (ADM-12).
"""

# Standard library imports
import uuid
from datetime import datetime
from typing import List, Optional

# Third-party imports
from pydantic import BaseModel, Field

# Local imports
from .common import ApiModel

#: Longest expected answer an admin may type.
MAX_EXPECTED_ANSWER = 5000


class EvalCaseCreate(BaseModel):
    """Optional corrections when adding an answer to the eval set."""

    expected_answer: Optional[str] = Field(None, min_length=1, max_length=MAX_EXPECTED_ANSWER)
    note: Optional[str] = Field(None, max_length=1000)


class EvalCaseOut(ApiModel):
    """One golden question (personal data already masked)."""

    id: uuid.UUID
    question: str
    expected_answer: str
    expected_sources: List[str]
    document_ids: List[str]
    note: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime
