"""
Assembles retrieved chunks into the context string handed to the LLM.

The same "label each chunk, join, truncate to budget" logic was previously
repeated in the chatbot service and the chat service; both now call this.
"""

# Standard library imports
import logging
from typing import Any, Dict, List, Optional

# Local imports
from config.settings import Config

logger = logging.getLogger(__name__)


class ContextAssembler:
    """Turns ranked search results into a single, budget-bounded context block."""

    #: Template applied to each retrieved chunk.
    CHUNK_TEMPLATE = "[Chunk {index}]\n{document}\n"

    def build(
        self,
        search_results: Optional[List[Dict[str, Any]]],
        max_length: Optional[int] = None,
    ) -> str:
        """
        Build the context string for a set of retrieved chunks.

        Args:
            search_results: Ranked chunks, each with ``index`` and ``document``.
            max_length: Character budget; falls back to ``MAX_CONTEXT_LENGTH``.

        Returns:
            The joined context, truncated to the budget. Empty when there are
            no results.
        """
        if not search_results:
            return ""

        budget = max_length if max_length is not None else Config.LLM.MAX_CONTEXT_LENGTH()
        chunks = [
            self.CHUNK_TEMPLATE.format(
                index=result.get("index"), document=result.get("document", "")
            )
            for result in search_results
        ]
        context = "\n".join(chunks)

        if budget > 0 and len(context) > budget:
            logger.debug(
                "Context truncated: %d -> %d characters", len(context), budget
            )
            context = context[:budget]
        return context
