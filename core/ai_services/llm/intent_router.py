"""
Classifies a chat turn as a RAG lookup or an action/tool-calling command.

Runs before either engine, so the two structurally different pipelines
(``ChatbotService``'s retrieval + generation vs ``ToolCallingAgent``'s
tool-calling) never both have to run for the same turn.

Not wired into ``ChatService``/``ChatbotService`` yet: ``ToolRegistry`` has
zero concrete tools registered today, so routing a turn to the action engine
has nowhere real to go (see ``tool_calling_agent.py``). Built and tested
standalone so classification quality can be validated ahead of the first
tool landing.
"""

# Standard library imports
import logging
from typing import Any, Dict, List, Optional

# Local imports
from config.settings import Config
from models.intent import IntentType
from .openai_client import OpenAIClientProvider

logger = logging.getLogger(__name__)

#: System prompt describing the two possible intents. The model is asked for
#: exactly one word rather than JSON, since a single token is far less likely
#: to come back malformed than a JSON object.
_SYSTEM_PROMPT = (
    "Bạn là bộ phân loại ý định cho một trợ lý ảo. Với câu hỏi/yêu cầu mới nhất "
    "của người dùng, xác định đây là:\n"
    "- \"rag\": câu hỏi cần tra cứu thông tin để trả lời.\n"
    "- \"action\": yêu cầu thực hiện một hành động hoặc thay đổi trạng thái "
    "(ví dụ: tạo, cập nhật, xoá, gửi, đặt lịch...).\n"
    "Chỉ trả lời đúng một từ, \"rag\" hoặc \"action\", không kèm giải thích hay "
    "định dạng khác."
)

#: Turns of history included when classifying (most recent last).
_HISTORY_WINDOW = 6


class IntentRouter:
    """Decides whether a turn should go to the RAG engine or the action engine."""

    def __init__(self, client_provider: OpenAIClientProvider):
        """
        Args:
            client_provider: Shared OpenAI client owner used for the classify call.
        """
        self._client_provider = client_provider

    def _build_messages(
        self, query: str, history: Optional[List[Dict[str, str]]]
    ) -> List[Dict[str, Any]]:
        """Assemble the system prompt, recent history, and the user's turn."""
        messages: List[Dict[str, Any]] = [{"role": "system", "content": _SYSTEM_PROMPT}]
        for message in (history or [])[-_HISTORY_WINDOW:]:
            if isinstance(message, dict) and "role" in message and "content" in message:
                messages.append(
                    {"role": str(message["role"]), "content": str(message["content"])}
                )
        messages.append({"role": "user", "content": query})
        return messages

    async def classify(
        self, query: str, history: Optional[List[Dict[str, str]]] = None
    ) -> IntentType:
        """
        Classify one turn as :attr:`IntentType.RAG` or :attr:`IntentType.ACTION`.

        Defaults to ``RAG`` on any failure or unrecognized output: a missed
        action just needs a clearer follow-up, while a false positive would
        silently skip retrieval for what was actually a real question.

        Args:
            query: Current turn's user text.
            history: Prior conversation turns, most recent last.

        Returns:
            The classified intent.
        """
        try:
            raw = await self._client_provider.complete_async(
                self._build_messages(query, history),
                model=Config.LLM.OPENAI_LIGHT_MODEL(),
            )
        except Exception:
            logger.exception("Intent classification failed; defaulting to RAG")
            return IntentType.RAG

        normalized = raw.strip().lower()
        if normalized.startswith(IntentType.ACTION.value):
            return IntentType.ACTION
        if not normalized.startswith(IntentType.RAG.value):
            logger.warning("Unrecognized intent classification output %r; defaulting to RAG", raw)
        return IntentType.RAG
