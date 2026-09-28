"""
Identity of whoever is calling the public chat API.
"""

# Standard library imports
import uuid
from dataclasses import dataclass
from typing import Optional

#: Tier of every visitor without a verified host token.
TIER_ANONYMOUS = "anonymous"
#: Access level of :data:`TIER_ANONYMOUS`; logged-in tiers rank above it.
ANONYMOUS_LEVEL = 0


@dataclass(frozen=True)
class ChatCaller:
    """
    Resolved caller of a chat request.

    ``api_key_id`` identifies the integrating server's API key (``None`` for
    our own chat widget server, which authenticates with its service token),
    while ``end_user_id`` is the opaque visitor id that frontend supplies — used
    for per-visitor limits and to scope anonymous conversations.

    ``user_id`` and ``tier`` come only from a verified host token (never from
    the request body or an LLM): ``user_id`` is its ``sub``, and ``tier_level``
    ranks the tier for access checks (0 = anonymous).
    """

    api_key_id: Optional[uuid.UUID]
    end_user_id: str
    client_ip: str
    request_id: Optional[str] = None
    user_id: Optional[str] = None
    tier: str = TIER_ANONYMOUS
    tier_level: int = ANONYMOUS_LEVEL

    @property
    def logged_in(self) -> bool:
        """True when a verified host token identified the user."""
        return self.user_id is not None

    def owns(self, conversation_user_id: Optional[str], conversation_end_user_id: str) -> bool:
        """
        Whether this caller may read or continue a conversation.

        A conversation claimed by a logged-in user belongs to that user alone
        (on any device, and never to an anonymous visitor, e.g. after logout);
        an unclaimed one belongs to the visitor who started it.
        """
        if conversation_user_id is not None:
            return self.user_id == conversation_user_id
        return self.end_user_id == conversation_end_user_id
