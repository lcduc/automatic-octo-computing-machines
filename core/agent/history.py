"""
Conversation-history sanitizing shared by every prompt builder.
"""

# Standard library imports
from typing import Dict, List, Optional

#: The only roles a replayed history message may carry; anything else (e.g. an
#: injected "system" turn) is dropped so history can never override instructions.
ALLOWED_HISTORY_ROLES = ("user", "assistant")


def recent_history(history: Optional[List[Dict[str, str]]], max_messages: int) -> List[Dict[str, str]]:
    """
    The last ``max_messages`` well-formed user/assistant messages.

    Args:
        history: Prior turns, oldest first; may be ``None``.
        max_messages: Upper bound on messages returned.

    Returns:
        ``[{"role": ..., "content": ...}]`` restricted to allowed roles.
    """
    if not history or max_messages <= 0:
        return []
    cleaned = [
        {"role": message["role"], "content": str(message.get("content", ""))}
        for message in history
        if isinstance(message, dict) and message.get("role") in ALLOWED_HISTORY_ROLES
    ]
    return cleaned[-max_messages:]
