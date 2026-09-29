"""
Matches configured sensitive topics (HND-06) in a message, ignoring case and Vietnamese accents.
"""

# Standard library imports
import re
from typing import Iterable, Optional

# Local imports
from utils.text_utils import TextUtils


def _fold(text: str) -> str:
    """Lower-case, accent-free, single-spaced."""
    return " ".join(TextUtils.strip_vietnamese_accents(text.lower().replace("đ", "d")).split())


def matching_topic(message: str, topics: Iterable[str]) -> Optional[str]:
    """The first topic appearing in ``message`` as whole words, or ``None``."""
    folded = _fold(message)
    for topic in topics:
        needle = _fold(topic)
        if needle and re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", folded):
            return topic
    return None
