"""
Who a tool runs for: set by the chat service from the verified caller, never by the LLM.
"""

# Standard library imports
from dataclasses import dataclass
from typing import Optional

# Local imports
from .caller import ANONYMOUS_LEVEL


@dataclass(frozen=True)
class ToolContext:
    """
    The caller's identity as tools see it.

    ``user_id`` comes only from a verified host token (checklist Invariant 1);
    SQL tools bind it as ``:user_id`` themselves, so no tool argument can name a user.
    """

    user_id: Optional[str] = None
    tier_level: int = ANONYMOUS_LEVEL

    @property
    def logged_in(self) -> bool:
        """True for a signed-in host user."""
        return self.user_id is not None
