"""
Rule-based redaction of personal data common in Vietnamese user messages.

Recognizes e-mail addresses, Vietnamese phone numbers, citizen ID numbers
(12-digit CCCD always; 9-digit CMND only next to an ID keyword), payment card
numbers (Luhn-validated) and bank account / tax codes next to their keywords.
Keyword-gated patterns avoid masking ordinary numbers such as salaries.
"""

# Standard library imports
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Pattern, Tuple

#: Placeholders substituted for each kind of personal data.
TAG_EMAIL = "[EMAIL]"
TAG_PHONE = "[PHONE]"
TAG_ID = "[ID_NUMBER]"
TAG_CARD = "[CARD_NUMBER]"
TAG_BANK_ACCOUNT = "[BANK_ACCOUNT]"
TAG_TAX_CODE = "[TAX_CODE]"

#: Payment card numbers have 13-19 digits.
MIN_CARD_DIGITS = 13
MAX_CARD_DIGITS = 19


def _luhn_valid(digits: str) -> bool:
    """True when ``digits`` passes the Luhn checksum used by card numbers."""
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _is_card_number(match: "re.Match[str]") -> bool:
    """Accept a digit run as a card number only if its length and checksum fit."""
    digits = re.sub(r"\D", "", match.group(0))
    return MIN_CARD_DIGITS <= len(digits) <= MAX_CARD_DIGITS and _luhn_valid(digits)


@dataclass(frozen=True)
class _Rule:
    """One recognizer: a pattern, its placeholder and an optional validator."""

    tag: str
    pattern: Pattern[str]
    #: Capture group holding the sensitive part (0 = whole match).
    group: int = 0
    validator: Optional[Callable[["re.Match[str]"], bool]] = None


@dataclass
class RedactionResult:
    """Redacted text and how many items of each kind were masked."""

    text: str
    counts: Dict[str, int] = field(default_factory=dict)

    @property
    def redacted(self) -> bool:
        """True when anything was masked."""
        return bool(self.counts)


class PiiRedactor:
    """Masks personal data in free text. Stateless and safe to share."""

    _RULES: Tuple[_Rule, ...] = (
        _Rule(TAG_EMAIL, re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
        _Rule(TAG_CARD, re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)"), validator=_is_card_number),
        _Rule(TAG_ID, re.compile(r"(?<!\d)\d{12}(?!\d)")),
        _Rule(
            TAG_ID,
            re.compile(r"(?i)(?:cmnd|cmt|chứng minh(?: nhân dân| thư)?)\D{0,15}(\d{9})(?!\d)"),
            group=1,
        ),
        _Rule(
            TAG_TAX_CODE,
            re.compile(r"(?i)(?:mst|mã số thuế)\D{0,10}(\d{10}(?:-\d{3})?)(?!\d)"),
            group=1,
        ),
        _Rule(
            TAG_BANK_ACCOUNT,
            re.compile(r"(?i)(?:stk|số tài khoản|tài khoản(?: ngân hàng)?)\D{0,15}(\d{6,16})(?!\d)"),
            group=1,
        ),
        _Rule(TAG_PHONE, re.compile(r"(?<![\d+])(?:\+84|84|0)(?:[\s.-]?\d){8,10}(?!\d)")),
    )

    def redact(self, text: str) -> RedactionResult:
        """
        Replace every recognized item with its placeholder.

        Args:
            text: Free text, e.g. a user message.

        Returns:
            The redacted text and per-tag counts.
        """
        if not text:
            return RedactionResult(text or "")
        counts: Dict[str, int] = {}
        for rule in self._RULES:
            text = self._apply(rule, text, counts)
        return RedactionResult(text, counts)

    @staticmethod
    def _apply(rule: _Rule, text: str, counts: Dict[str, int]) -> str:
        """Run one rule, substituting only its sensitive capture group."""
        pieces: List[str] = []
        cursor = 0
        for match in rule.pattern.finditer(text):
            if rule.validator is not None and not rule.validator(match):
                continue
            start, end = match.span(rule.group)
            pieces.append(text[cursor:start])
            pieces.append(rule.tag)
            cursor = end
            counts[rule.tag] = counts.get(rule.tag, 0) + 1
        if not pieces:
            return text
        pieces.append(text[cursor:])
        return "".join(pieces)
