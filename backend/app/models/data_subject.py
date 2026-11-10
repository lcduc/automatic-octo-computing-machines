"""
The person behind a data-subject request (PRV-03).
"""

# Standard library imports
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DataSubject:
    """Any of the identifiers the person is known by; at least one is set."""

    #: Host-site user id (``sub`` of their host token).
    user_id: Optional[str] = None
    #: Anonymous visitor id (from the widget cookie).
    visitor_id: Optional[str] = None
    #: Contact e-mail left on a ticket.
    email: Optional[str] = None

    def __post_init__(self) -> None:
        """
        Raises:
            ValueError: No identifier given.
        """
        if not (self.user_id or self.visitor_id or self.email):
            raise ValueError("A data subject needs a user id, visitor id or e-mail")
