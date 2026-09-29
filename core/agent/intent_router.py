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
from models.tool_context import ToolContext
from .base_llm_provider import BaseLLMProvider
from .history import recent_history
from .prompts import SystemPrompts
from .tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

#: Turns of history included when classifying (most recent last).
_HISTORY_WINDOW = 6


class IntentRouter:
    """Decides whether a turn should go to the RAG engine or the action engine."""

    def __init__(self, client_provider: BaseLLMProvider, tool_registry: ToolRegistry, login_available: bool = False):
        """
        Args:
            client_provider: Shared LLM provider used for the classify call.
            tool_registry: Tools the action engine can actually reach - the
                "action" bucket is described from this, so classification
                never drifts out of sync with what is really registered.
            login_available: Whether visitors can sign in on the host site; only
                then are tools needing a login described (as "login", never offered).
        """
        self._client_provider = client_provider
        self._tool_registry = tool_registry
        self._login_available = login_available

    def _build_system_prompt(self, context: ToolContext) -> Tuple[Optional[str], bool]:
        """
        The classifier prompt for this caller's tier.

        Returns:
            ``(prompt, login_offered)``; the prompt is ``None`` when no bucket but RAG exists.
        """
        schemas = self._tool_registry.schemas(context)
        locked = self._tool_registry.locked(context) if self._login_available and not context.logged_in else []
        if not schemas and not locked:
            return None, False
        descriptions = "\n".join(
            f"  - {schema['function']['name']}: {schema['function']['description']}" for schema in schemas
        ) or "  (không có)"
        login_option = ""
        answers = '"rag" hoặc "action"'
        if locked:
            login_option = SystemPrompts.INTENT_LOGIN_OPTION.format(
                locked_descriptions="\n".join(f"  - {tool.description}" for tool in locked)
            )
            answers = '"rag", "action" hoặc "login"'
        prompt = SystemPrompts.INTENT_CLASSIFIER.format(
            tool_descriptions=descriptions, login_option=login_option, answers=answers
        )
        return prompt, bool(locked)

    @staticmethod
    def _build_messages(
        system_prompt: str, query: str, history: Optional[List[Dict[str, str]]]
    ) -> List[Dict[str, Any]]:
        """Assemble the system prompt, recent history, and the user's turn."""
        return [
            {"role": "system", "content": system_prompt},
            *recent_history(history, _HISTORY_WINDOW),
            {"role": "user", "content": query},
        ]

    async def classify(
        self,
        query: str,
        history: Optional[List[Dict[str, str]]] = None,
        model: Optional[str] = None,
        context: ToolContext = ToolContext(),
    ) -> Tuple[IntentType, Optional[LLMUsage]]:
        """
        Classify one turn as :attr:`IntentType.RAG`, :attr:`IntentType.ACTION`
        or (anonymous visitors, when a tool needs a login) :attr:`IntentType.LOGIN_REQUIRED`.

        Defaults to ``RAG`` on any failure or unrecognized output: a missed
        action just needs a clearer follow-up, while a false positive would
        silently skip retrieval for what was actually a real question. Also
        defaults to ``RAG`` without spending a call when no tool is
        registered at all, since there is nothing an "action" could route to.

        Args:
            query: Current turn's user text.
            history: Prior conversation turns, most recent last.
            model: Light model to use; defaults to the configured one.
            context: The verified caller; decides which tools are described.

        Returns:
            ``(intent, usage)`` — usage is ``None`` when no call was made.
        """
        system_prompt, login_offered = self._build_system_prompt(context)
        if system_prompt is None:
            return IntentType.RAG, None

        try:
            result = await self._client_provider.complete_async(
                self._build_messages(system_prompt, query, history),
                model=model or Config.LLM.ACTIVE_LIGHT_MODEL(),
            )
        except Exception:
            logger.exception("Intent classification failed; defaulting to RAG")
            return IntentType.RAG, None

        normalized = result.text.strip().lower()
        if normalized.startswith(IntentType.ACTION.value):
            return IntentType.ACTION, result.usage
        if normalized.startswith(IntentType.LOGIN_REQUIRED.value) and login_offered:
            return IntentType.LOGIN_REQUIRED, result.usage
        if not normalized.startswith(IntentType.RAG.value):
            logger.warning("Unrecognized intent classification output %r; defaulting to RAG", result.text)
        return IntentType.RAG, result.usage
