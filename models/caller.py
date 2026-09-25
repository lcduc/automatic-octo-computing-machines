"""
Identity of whoever is calling the public chat API.
"""

# Standard library imports
import uuid
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ChatCaller:
    """
    Resolved caller of a chat request.

    ``api_key_id`` identifies the embedding frontend (authenticated), while
    ``end_user_id`` is the opaque visitor id that frontend supplies — used for
    per-visitor limits and to scope conversations, never for authorization
    beyond "a visitor may only read their own conversations".
    """

    api_key_id: uuid.UUID
    end_user_id: str
    client_ip: str
    request_id: Optional[str] = None
