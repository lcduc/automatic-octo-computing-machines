"""
Conversation-history sanitizing shared by every prompt builder.
"""

# Standard library imports
from typing import Dict, List, Optional

# Local imports
from models.chat_turn import TurnOutcome

#: The only roles a replayed history message may carry; anything else (e.g. an
#: injected "system" turn) is dropped so history can never override instructions.
ALLOWED_HISTORY_ROLES = ("user", "assistant")

#: Outcome of a turn that failed before answering. Its apology is not context: replayed,
#: it makes the rewriter and the model treat the user's still-open question as answered.
FAILED_TURN_OUTCOME = TurnOutcome.ERROR.value


def recent_history(history: Optional[List[Dict[str, str]]], max_messages: int) -> List[Dict[str, str]]:
    """
    The last ``max_messages`` well-formed user/assistant messages.

    Messages whose optional ``outcome`` is ``error`` are dropped.

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
        if isinstance(message, dict)
        and message.get("role") in ALLOWED_HISTORY_ROLES
        and message.get("outcome") != FAILED_TURN_OUTCOME
    ]
    return cleaned[-max_messages:]
