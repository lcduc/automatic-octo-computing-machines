"""
Renders retrieved chunks into the ``<document>`` blocks handed to the LLM.

Each chunk is labelled with its source category, document title and scalar
metadata (url, effective date, …) so the model can weigh and cite sources.
Whole chunks are dropped once the character budget is reached instead of
cutting one mid-sentence.
"""

# Standard library imports
import logging
from typing import Any, Dict, List

# Local imports
from models.knowledge import RetrievedChunk

logger = logging.getLogger(__name__)

#: Metadata values longer than this are not worth spending prompt tokens on.
MAX_METADATA_VALUE_LENGTH = 200
#: At most this many metadata attributes are rendered per chunk.
MAX_METADATA_ATTRIBUTES = 8
#: Internal keys never shown to the model.
HIDDEN_METADATA_KEYS = {"filename"}


def _attribute(value: Any) -> str:
    """Render a value safely inside a double-quoted XML-like attribute."""
    return str(value).replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace("\n", " ")


class ContextAssembler:
    """Turns ranked chunks into a single, budget-bounded documents block."""

    def _metadata_attributes(self, metadata: Dict[str, Any]) -> str:
        """Scalar, short metadata rendered as attributes."""
        rendered = []
        for key, value in metadata.items():
            if key in HIDDEN_METADATA_KEYS or not isinstance(value, (str, int, float, bool)):
                continue
            text = str(value)
            if not text or len(text) > MAX_METADATA_VALUE_LENGTH or not key.replace("_", "").isalnum():
                continue
            rendered.append(f'{key}="{_attribute(text)}"')
            if len(rendered) >= MAX_METADATA_ATTRIBUTES:
                break
        return (" " + " ".join(rendered)) if rendered else ""

    def render_chunk(self, number: int, item: RetrievedChunk) -> str:
        """One ``<document>`` element for a chunk."""
        chunk = item.chunk
        # A chunk containing a closing tag must not be able to end its own element.
        body = chunk.content.replace("</document", "<\\/document")
        return (
            f'<document id="{number}" source="{_attribute(chunk.source)}" '
            f'title="{_attribute(chunk.document_title)}"{self._metadata_attributes(chunk.metadata)}>\n'
            f"{body}\n</document>"
        )

    def build(self, results: List[RetrievedChunk], max_length: int) -> str:
        """
        Build the documents block.

        Args:
            results: Chunks in the order they should be read.
            max_length: Character budget; the first chunk is truncated only if
                it alone exceeds the budget.

        Returns:
            The rendered block (empty when there are no results).
        """
        rendered: List[str] = []
        used = 0
        for number, item in enumerate(results, start=1):
            block = self.render_chunk(number, item)
            if max_length > 0 and used + len(block) > max_length:
                if not rendered:
                    rendered.append(block[:max_length])
                logger.debug("Context budget reached after %d of %d chunks", len(rendered), len(results))
                break
            rendered.append(block)
            used += len(block) + 1
        return "\n".join(rendered)
