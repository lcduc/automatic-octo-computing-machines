"""
Parse the periods and money amounts users type, in Vietnamese or English (TOOL-07).

Pure helpers used by SQL tool arguments: ``"tháng trước"`` becomes a
``[start, end)`` date range, ``"1.000.000 đ"`` becomes ``Decimal(1000000)``.
Diacritics are optional ("thang truoc" works too).
"""

# Standard library imports
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional, Tuple

# Local imports
from .text_utils import TextUtils

DateRange = Tuple[date, date]

_MONTH_WORDS = r"(?:thang|month)"
_QUARTER_WORDS = r"(?:quy|q|quarter)"
_YEAR_WORDS = r"(?:nam|year)"
#: Multipliers for amount suffixes (checked longest first).
_AMOUNT_UNITS = (
    ("trieu", Decimal(1_000_000)), ("ty", Decimal(1_000_000_000)), ("ti", Decimal(1_000_000_000)),
    ("nghin", Decimal(1_000)), ("ngan", Decimal(1_000)), ("tr", Decimal(1_000_000)),
    ("k", Decimal(1_000)), ("m", Decimal(1_000_000)), ("b", Decimal(1_000_000_000)),
)
_CURRENCY_MARKS = ("vnd", "vnđ", "dong", "đ", "d")


def _normalise(text: str) -> str:
    """Lower-case, accent-free, single-spaced."""
    return " ".join(TextUtils.strip_vietnamese_accents(text.lower().replace("đ", "d")).split())


def _month_range(year: int, month: int) -> DateRange:
    """``[first day of the month, first day of the next month)``."""
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, end


def _year_from(match: Optional[str], today: date) -> int:
    """An explicit four-digit year, else this year."""
    return int(match) if match else today.year


def parse_period(text: str, today: date) -> Optional[DateRange]:
    """
    A ``[start, end)`` date range for a period like "tháng trước", "quý 3", "năm 2025",
    "7 ngày qua", "last month" or "2026-01-01..2026-03-31".

    Returns:
        ``None`` when the text is not a period this parser knows.
    """
    phrase = _normalise(text)
    explicit = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\s*(?:\.\.|den|to|-|–)\s*(\d{4}-\d{2}-\d{2})", phrase)
    if explicit:
        start, last = date.fromisoformat(explicit.group(1)), date.fromisoformat(explicit.group(2))
        return (start, last + timedelta(days=1)) if start <= last else None
    if phrase in ("hom nay", "today"):
        return today, today + timedelta(days=1)
    if phrase in ("hom qua", "yesterday"):
        return today - timedelta(days=1), today
    if phrase in ("tuan nay", "this week"):
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=7)
    if phrase in ("tuan truoc", "tuan roi", "last week"):
        start = today - timedelta(days=today.weekday() + 7)
        return start, start + timedelta(days=7)
    if phrase in ("thang nay", "this month"):
        return _month_range(today.year, today.month)
    if phrase in ("thang truoc", "thang roi", "last month"):
        previous = today.replace(day=1) - timedelta(days=1)
        return _month_range(previous.year, previous.month)
    if phrase in ("nam nay", "this year"):
        return date(today.year, 1, 1), date(today.year + 1, 1, 1)
    if phrase in ("nam ngoai", "nam truoc", "last year"):
        return date(today.year - 1, 1, 1), date(today.year, 1, 1)
    recent = re.fullmatch(r"(\d{1,3}) (?:ngay|days?) (?:qua|gan day|gan nhat|vua qua|past|last)?", phrase) or \
        re.fullmatch(r"(?:last|past) (\d{1,3}) days?", phrase)
    if recent:
        return today - timedelta(days=int(recent.group(1)) - 1), today + timedelta(days=1)
    month = re.fullmatch(rf"{_MONTH_WORDS} (\d{{1,2}})(?:[ /-](?:{_YEAR_WORDS} )?(\d{{4}}))?", phrase) or \
        re.fullmatch(r"(\d{1,2})[/-](\d{4})", phrase)
    if month and 1 <= int(month.group(1)) <= 12:
        return _month_range(_year_from(month.group(2), today), int(month.group(1)))
    quarter = re.fullmatch(rf"{_QUARTER_WORDS} ?([1-4])(?:[ /-](?:{_YEAR_WORDS} )?(\d{{4}}))?", phrase)
    if quarter:
        year, first_month = _year_from(quarter.group(2), today), (int(quarter.group(1)) - 1) * 3 + 1
        return date(year, first_month, 1), _month_range(year, first_month + 2)[1]
    year = re.fullmatch(rf"(?:{_YEAR_WORDS} )?(\d{{4}})", phrase)
    if year:
        return date(int(year.group(1)), 1, 1), date(int(year.group(1)) + 1, 1, 1)
    return None


def parse_amount(text: str) -> Optional[Decimal]:
    """
    A money amount from "1.000.000 đ", "1,000,000", "1,5 triệu", "500k", "2tr" or "3 tỷ".

    Vietnamese style (``.`` thousands, ``,`` decimals) and English style are both
    read correctly: groups of exactly three digits after a separator are thousands.

    Returns:
        ``None`` when no number is found.
    """
    phrase = _normalise(text).replace(" ", "")
    for mark in _CURRENCY_MARKS:
        if phrase.endswith(mark) and len(phrase) > len(mark) and not phrase[: -len(mark)][-1:].isalpha():
            phrase = phrase[: -len(mark)]
            break
    multiplier = Decimal(1)
    for unit, factor in _AMOUNT_UNITS:
        if phrase.endswith(unit) and phrase[: -len(unit)][-1:].isdigit():
            phrase, multiplier = phrase[: -len(unit)], factor
            break
    if not re.fullmatch(r"\d[\d.,]*", phrase):
        return None
    try:
        return _number(phrase) * multiplier
    except InvalidOperation:
        return None


def _number(digits: str) -> Decimal:
    """Read separators: repeated or 3-digit-grouped ones are thousands, a lone other one is decimal."""
    separators = [char for char in digits if char in ".,"]
    if not separators:
        return Decimal(digits)
    groups = re.split(r"[.,]", digits)
    if len(set(separators)) == 2:
        decimal_mark = digits[max(digits.rfind("."), digits.rfind(","))]
        whole, fraction = digits.rsplit(decimal_mark, 1)
        return Decimal(re.sub(r"[.,]", "", whole) + "." + fraction)
    if len(separators) > 1 or len(groups[-1]) == 3:
        return Decimal("".join(groups))
    return Decimal(groups[0] + "." + groups[1])
