"""
Screens a user message before any retrieval or LLM work is spent on it.

Rule-based checks run first and cost nothing: prompt-injection phrases,
explicit requests for a human agent and pure greetings/thanks. The optional
moderation call (OpenAI's free endpoint) runs last and fails open, so an
outage of that endpoint never blocks legitimate users.
"""

# Standard library imports
import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, Optional, Pattern, Tuple

# Local imports
from utils.text_utils import TextUtils

logger = logging.getLogger(__name__)


class GuardAction(str, Enum):
    """What the chat pipeline should do with a message."""

    ALLOW = "allow"
    BLOCK = "block"
    HUMAN_REQUESTED = "human_requested"
    GREETING = "greeting"
    THANKS = "thanks"


@dataclass(frozen=True)
class GuardVerdict:
    """Outcome of screening one message."""

    action: GuardAction
    #: Machine-readable cause for blocks (e.g. ``prompt_injection``), else ``None``.
    reason: Optional[str] = None


#: Patterns are matched against lower-cased, accent-free text, so one ASCII
#: pattern covers "bỏ qua" / "bo qua" alike.
_INJECTION_PATTERNS: Tuple[Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|prompts|rules|messages)",
        r"disregard (all |the )?(previous|prior|above|system) (instructions|prompt|rules)",
        r"(reveal|show|print|repeat|output) (me )?(your|the) (system |initial |hidden )?(prompt|instructions)",
        r"\b(developer|dan|god) mode\b",
        r"\bjailbreak",
        r"<\|?(system|im_start|im_end)\|?>",
        r"^\s*(system|assistant)\s*:",
        r"bo qua (tat ca |moi |cac |nhung )?(huong dan|chi dan|chi thi|cau lenh|lenh|quy tac|yeu cau) "
        r"(truoc|tren|ban dau|he thong|cu)",
        r"quen (het |di |tat ca )?(cac |nhung )?(huong dan|quy tac|chi dan) (truoc|tren|ban dau)",
        r"(tiet lo|hien thi|in ra|cho (toi|minh|tao) xem|nhac lai|lap lai) (lai )?"
        r"(system prompt|prompt (he thong|goc)|huong dan (he thong|goc|ban dau)|cau lenh he thong)",
        r"(dong vai|gia vo la|hay tro thanh) .{0,40}(khong (bi )?(gioi han|kiem duyet|rang buoc))",
    )
)

_HUMAN_PATTERNS: Tuple[Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        r"(gap|noi chuyen (voi)?|ket noi (voi)?|chuyen (cho|sang|toi|den)|lien he (voi)?|goi (cho)?)"
        r" ?(mot |1 )?(nhan vien|tu van vien|nguoi that|nguoi ho tro|admin|cskh|tong dai vien|can bo)",
        r"\b(talk|speak|chat) (to|with) (a |an )?(human|real person|agent|staff|operator)\b",
        r"\b(live|human) (agent|support)\b",
    )
)

#: A whole message that is only a greeting / thanks (optionally with a name or emoji).
_GREETING = re.compile(
    r"^(xin chao|chao( ban| bot| em| anh| chi| ad| admin)?|hello|hi|hey|alo|a lo|good (morning|afternoon|evening))"
    r"[\s!.,?~]*$"
)
_THANKS = re.compile(
    r"^(cam on|cam on ban|cam on nhieu|thanks?( you)?|thank you( so much)?|ok cam on|tks|thanks a lot)"
    r"( ban| nhe| nha| nhieu| a| bot| em)*[\s!.,~]*$"
)

Moderator = Callable[[str], Awaitable[bool]]


class InputGuard:
    """Classifies a user message into a :class:`GuardVerdict`."""

    def __init__(self, moderator: Optional[Moderator] = None):
        """
        Args:
            moderator: Async ``text -> flagged`` check (e.g. OpenAI moderation);
                ``None`` disables moderation.
        """
        self._moderator = moderator

    @staticmethod
    def _normalize(text: str) -> str:
        """Lower-case, strip Vietnamese accents and collapse whitespace."""
        folded = TextUtils.strip_vietnamese_accents(text.lower())
        return re.sub(r"\s+", " ", folded).strip()

    def classify_rules(self, text: str) -> GuardVerdict:
        """Rule-only screening (no network), used first and in tests."""
        normalized = self._normalize(text)
        if any(pattern.search(normalized) for pattern in _INJECTION_PATTERNS):
            return GuardVerdict(GuardAction.BLOCK, "prompt_injection")
        if any(pattern.search(normalized) for pattern in _HUMAN_PATTERNS):
            return GuardVerdict(GuardAction.HUMAN_REQUESTED)
        if _GREETING.match(normalized):
            return GuardVerdict(GuardAction.GREETING)
        if _THANKS.match(normalized):
            return GuardVerdict(GuardAction.THANKS)
        return GuardVerdict(GuardAction.ALLOW)

    async def check(self, text: str) -> GuardVerdict:
        """
        Full screening: rules, then moderation for messages still allowed.

        Returns:
            The verdict; moderation failures are logged and treated as allowed.
        """
        verdict = self.classify_rules(text)
        if verdict.action != GuardAction.ALLOW or self._moderator is None:
            return verdict
        try:
            if await self._moderator(text):
                return GuardVerdict(GuardAction.BLOCK, "moderation_flagged")
        except Exception:
            logger.exception("Moderation check failed; allowing message")
        return verdict
