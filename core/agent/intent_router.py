"""
Classifies a chat turn as a RAG lookup or an action/tool-calling command.

Runs before either engine, so the two structurally different pipelines
(``ChatbotService``'s retrieval + generation vs ``ToolCallingAgent``'s
tool-calling) never both have to run for the same turn.
"""

# Standard library imports
import logging
from typing import Any, Dict, List, Optional, Tuple

# Local imports
from config.settings import Config
from models.intent import IntentType
from models.llm import LLMUsage
from .base_llm_provider import BaseLLMProvider
from .history import recent_history
from .prompts import SystemPrompts
from .tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

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
        return SystemPrompts.INTENT_CLASSIFIER.format(tool_descriptions=descriptions)

    def _build_messages(
        self, query: str, history: Optional[List[Dict[str, str]]]
    ) -> List[Dict[str, Any]]:
        """Assemble the system prompt, recent history, and the user's turn."""
        return [
            {"role": "system", "content": self._system_prompt},
            *recent_history(history, _HISTORY_WINDOW),
            {"role": "user", "content": query},
        ]

    async def classify(
        self, query: str, history: Optional[List[Dict[str, str]]] = None
    ) -> Tuple[IntentType, Optional[LLMUsage]]:
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
            ``(intent, usage)`` — usage is ``None`` when no call was made.
        """
        if not self._tool_registry.schemas():
            return IntentType.RAG, None

        try:
            result = await self._client_provider.complete_async(
                self._build_messages(query, history),
                model=Config.LLM.ACTIVE_LIGHT_MODEL(),
            )
        except Exception:
            logger.exception("Intent classification failed; defaulting to RAG")
            return IntentType.RAG, None

        normalized = result.text.strip().lower()
        if normalized.startswith(IntentType.ACTION.value):
            return IntentType.ACTION, result.usage
        if not normalized.startswith(IntentType.RAG.value):
            logger.warning("Unrecognized intent classification output %r; defaulting to RAG", result.text)
        return IntentType.RAG, result.usage
