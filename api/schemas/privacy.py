"""
Request/response models of the admin privacy routes (legal hold, data-subject requests).
"""

# Standard library imports
from typing import Any, Dict, List, Optional

# Third-party imports
from pydantic import BaseModel, Field, model_validator

# Local imports
from models.data_subject import DataSubject
from .admin import EMAIL_PATTERN

#: Longest user or visitor id accepted (matches the id columns).
MAX_SUBJECT_ID_LENGTH = 128


class LegalHoldUpdate(BaseModel):
    """Set (``true``) or clear (``false``) a legal hold."""

    held: bool


class LegalHoldOut(BaseModel):
    """The item's hold after the change."""

    id: str
    legal_hold: bool


class DataSubjectQuery(BaseModel):
    """Who the request is about; give at least one identifier."""

    user_id: Optional[str] = Field(None, min_length=1, max_length=MAX_SUBJECT_ID_LENGTH)
    visitor_id: Optional[str] = Field(None, min_length=1, max_length=MAX_SUBJECT_ID_LENGTH)
    email: Optional[str] = Field(None, pattern=EMAIL_PATTERN, max_length=320)

    @model_validator(mode="after")
    def _one_identifier(self) -> "DataSubjectQuery":
        """Refuse an empty query (it would match nobody, or everybody)."""
        if not (self.user_id or self.visitor_id or self.email):
            raise ValueError("Give a user_id, visitor_id or email")
        return self

    def to_subject(self) -> DataSubject:
        """The internal model."""
        return DataSubject(user_id=self.user_id, visitor_id=self.visitor_id, email=self.email)


class DataSubjectExport(BaseModel):
    """Everything stored about the person."""

    conversations: List[Dict[str, Any]]
    tickets: List[Dict[str, Any]]


class DataSubjectDeleted(BaseModel):
    """What a deletion removed, and what legal hold kept."""

    conversations: int
    tickets: int
    token_usage: int
    kept_on_hold: int
