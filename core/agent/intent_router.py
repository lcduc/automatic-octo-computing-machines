"""
Classifies a chat turn as a RAG lookup or an action/tool-calling command.

Runs before either engine, so the two structurally different pipelines
(``ChatbotService``'s retrieval + generation vs ``ToolCallingAgent``'s
tool-calling) never both have to run for the same turn.
"""

# Standard library imports
import logging
from typing import Any, Dict, List, Optional

# Local imports
from config.settings import Config
from models.intent import IntentType
from .base_llm_provider import BaseLLMProvider
from .tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

#: Fixed preamble; the "action" bucket's tool list is appended per instance
#: from the registry so it never drifts out of sync with what is actually
#: registered (see :meth:`IntentRouter._build_system_prompt`).
_SYSTEM_PROMPT_TEMPLATE = (
    "Bạn là bộ phân loại ý định cho một trợ lý ảo. Với câu hỏi/yêu cầu mới nhất "
    "của người dùng, xác định đây là:\n"
    "- \"rag\": câu hỏi cần tra cứu thông tin từ tài liệu/kho tri thức để trả lời.\n"
    "- \"action\": yêu cầu mà một trong các công cụ sau đây có thể thực hiện "
    "hoặc trả lời:\n"
    "{tool_descriptions}\n"
    "Nếu không công cụ nào phù hợp, hãy trả lời \"rag\".\n"
    "Chỉ trả lời đúng một từ, \"rag\" hoặc \"action\", không kèm giải thích hay "
    "định dạng khác."
)

#: Turns of history included when classifying (most recent last).
_HISTORY_WINDOW = 6


class IntentRouter:
    """Decides whether a turn should go to the RAG engine or the action engine."""

    def __init__(self, client_provider: BaseLLMProvider, tool_registry: ToolRegistry):
        """
        Args:
            client_provider: Shared LLM provider used for the classify call.
            tool_registry: Tools the action engine can actually reach - the
                "action" bucket is described from this, so classification
                never drifts out of sync with what is really registered.
        """
        self._client_provider = client_provider
        self._tool_registry = tool_registry
        self._system_prompt = self._build_system_prompt(tool_registry)

    @staticmethod
    def _build_system_prompt(tool_registry: ToolRegistry) -> str:
        """Render the classifier prompt's tool list from the registry's own schemas."""
        descriptions = "\n".join(
            f"  - {schema['function']['name']}: {schema['function']['description']}"
            for schema in tool_registry.schemas()
        )
        return _SYSTEM_PROMPT_TEMPLATE.format(tool_descriptions=descriptions)

    def _build_messages(
        self, query: str, history: Optional[List[Dict[str, str]]]
    ) -> List[Dict[str, Any]]:
        """Assemble the system prompt, recent history, and the user's turn."""
        messages: List[Dict[str, Any]] = [{"role": "system", "content": self._system_prompt}]
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
        silently skip retrieval for what was actually a real question. Also
        defaults to ``RAG`` without spending a call when no tool is
        registered at all, since there is nothing an "action" could route to.

        Args:
            query: Current turn's user text.
            history: Prior conversation turns, most recent last.

        Returns:
            The classified intent.
        """
        if not self._tool_registry.schemas():
            return IntentType.RAG

        try:
            raw = await self._client_provider.complete_async(
                self._build_messages(query, history),
                model=Config.LLM.ACTIVE_LIGHT_MODEL(),
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
