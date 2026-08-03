"""
Condenses multi-turn follow-up questions into standalone search queries.

Retrieval only ever sees the current turn's text. Without this, a follow-up
like "còn cái kia thì sao?" is searched literally instead of resolved against
the conversation history, so the knowledge-base search silently misses.
"""

# Standard library imports
import logging
from typing import Dict, List, Optional

# Local imports
from .openai_client import OpenAIClientProvider

logger = logging.getLogger(__name__)

#: Instruction for turning a follow-up + history into one standalone question.
_CONDENSE_SYSTEM_PROMPT = (
    "Bạn sẽ nhận được lịch sử hội thoại và câu hỏi tiếp theo của người dùng. "
    "Viết lại câu hỏi tiếp theo thành một câu hỏi độc lập, đầy đủ ý nghĩa mà "
    "không cần lịch sử hội thoại để hiểu, giữ nguyên ngôn ngữ và ý định gốc. "
    "Chỉ trả về câu hỏi đã viết lại, không kèm giải thích hay định dạng khác."
)

#: Turns of history included when condensing (most recent last).
_HISTORY_WINDOW = 6


class QueryRewriter:
    """Condenses a follow-up question into a standalone query using history."""

    def __init__(self, client_provider: OpenAIClientProvider):
        """
        Args:
            client_provider: Shared OpenAI client owner used for the rewrite call.
        """
        self._client_provider = client_provider

    def _build_messages(
        self, query: str, history: List[Dict[str, str]]
    ) -> List[Dict[str, str]]:
        """Assemble the condense-question prompt from recent history and the query."""
        messages = [{"role": "system", "content": _CONDENSE_SYSTEM_PROMPT}]
        for message in history[-_HISTORY_WINDOW:]:
            if isinstance(message, dict) and "role" in message and "content" in message:
                messages.append(
                    {"role": str(message["role"]), "content": str(message["content"])}
                )
        messages.append(
            {"role": "user", "content": f"Câu hỏi tiếp theo: {query}"}
        )
        return messages

    def rewrite(self, query: str, history: Optional[List[Dict[str, str]]]) -> str:
        """
        Return a standalone version of ``query`` resolved against ``history``.

        Args:
            query: Current turn's user text.
            history: Prior conversation turns, most recent last. No history
                means there is nothing to resolve, so the query is returned
                unchanged without spending an LLM call.

        Returns:
            The rewritten standalone query, or the original ``query`` when
            there is no history or the rewrite call fails.
        """
        if not history:
            return query

        try:
            rewritten = self._client_provider.complete(
                self._build_messages(query, history)
            )
        except Exception:
            logger.exception("Query rewrite failed; falling back to original query")
            return query

        if not rewritten:
            logger.warning("Query rewrite returned empty text; falling back to original query")
            return query

        if rewritten != query:
            logger.debug("Query rewritten: %r -> %r", query, rewritten)
        return rewritten
