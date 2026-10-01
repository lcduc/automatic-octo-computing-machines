"""
Condenses multi-turn follow-up questions into standalone search queries.

Retrieval only ever sees the current turn's text. Without this, a follow-up
like "còn cái kia thì sao?" is searched literally instead of resolved against
the conversation history, so the knowledge-base search silently misses.

The same call restores the accents of Vietnamese typed without them: the
reranker scores such text near zero ("tien phong o duc" ~0.001, "tiền phòng ở
Đức" ~0.6), so an unaccented question would otherwise miss its own answer.
"""

# Standard library imports
import logging
from typing import Dict, List, Optional, Tuple

# Local imports
from config.settings import Config
from models.llm import LLMUsage
from .base_llm_provider import BaseLLMProvider
from .history import recent_history
from .prompts import SystemPrompts
from utils.text_utils import TextUtils

logger = logging.getLogger(__name__)

#: Recent messages given to the rewrite prompt; older context rarely matters.
_HISTORY_WINDOW = 6


class QueryRewriter:
    """Condenses a follow-up question into a standalone query using history."""

    def __init__(self, client_provider: BaseLLMProvider):
        """
        Args:
            client_provider: Shared LLM provider used for the rewrite call.
        """
        self._client_provider = client_provider

    @staticmethod
    def _build_messages(query: str, history: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        Assemble the condense-question prompt from recent history and the query.

        History goes in as a quoted transcript inside one user message, never as
        replayed chat turns: replayed turns make the model continue the chat and
        answer (or ask back) instead of rewriting.
        """
        transcript = "\n".join(
            f"{SystemPrompts.CONDENSE_SPEAKERS[message['role']]}: {message['content']}"
            for message in recent_history(history, _HISTORY_WINDOW)
        ) or SystemPrompts.CONDENSE_NO_HISTORY
        return [
            {"role": "system", "content": SystemPrompts.CONDENSE_QUESTION},
            {"role": "user", "content": SystemPrompts.CONDENSE_QUESTION_INPUT.format(transcript=transcript, query=query)},
        ]

    async def rewrite(
        self, query: str, history: Optional[List[Dict[str, str]]], model: Optional[str] = None
    ) -> Tuple[str, Optional[LLMUsage]]:
        """
        Return a standalone version of ``query`` resolved against ``history``.

        Args:
            query: Current turn's user text.
            history: Prior conversation turns, most recent last. Without
                history and without missing accents there is nothing to fix,
                so no LLM call is made.
            model: Light model to use; defaults to the configured one.

        Returns:
            ``(search_query, usage)``: the rewritten query (or the original on
            failure / no history) and the tokens the rewrite consumed.
        """
        if not recent_history(history, _HISTORY_WINDOW) and not TextUtils.looks_like_unaccented_vietnamese(query):
            return query, None

        try:
            result = await self._client_provider.complete_async(
                self._build_messages(query, history or []),
                model=model or Config.LLM.ACTIVE_LIGHT_MODEL(),
            )
        except Exception:
            logger.exception("Query rewrite failed; falling back to original query")
            return query, None

        if not result.text:
            logger.warning("Query rewrite returned empty text; falling back to original query")
            return query, result.usage
        return result.text, result.usage
