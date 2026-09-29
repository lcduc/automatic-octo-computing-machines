"""Vietnamese/English periods and money amounts for SQL tool arguments (TOOL-07)."""

from datetime import date
from decimal import Decimal

import pytest

from utils.vietnamese_parsing import parse_amount, parse_period

TODAY = date(2026, 9, 29)  # a Tuesday


@pytest.mark.parametrize(
    "text, start, end",
    [
        ("tháng trước", date(2026, 8, 1), date(2026, 9, 1)),
        ("thang truoc", date(2026, 8, 1), date(2026, 9, 1)),
        ("Last month", date(2026, 8, 1), date(2026, 9, 1)),
        ("tháng này", date(2026, 9, 1), date(2026, 10, 1)),
        ("quý 3", date(2026, 7, 1), date(2026, 10, 1)),
        ("Q4 2025", date(2025, 10, 1), date(2026, 1, 1)),
        ("quý 1 năm 2026", date(2026, 1, 1), date(2026, 4, 1)),
        ("tháng 12/2025", date(2025, 12, 1), date(2026, 1, 1)),
        ("02/2026", date(2026, 2, 1), date(2026, 3, 1)),
        ("năm ngoái", date(2025, 1, 1), date(2026, 1, 1)),
        ("năm 2024", date(2024, 1, 1), date(2025, 1, 1)),
        ("hôm qua", date(2026, 9, 28), date(2026, 9, 29)),
        ("tuần trước", date(2026, 9, 21), date(2026, 9, 28)),
        ("7 ngày qua", date(2026, 9, 23), date(2026, 9, 30)),
        ("last 30 days", date(2026, 8, 31), date(2026, 9, 30)),
        ("2026-01-01..2026-03-31", date(2026, 1, 1), date(2026, 4, 1)),
    ],
)
def test_periods(text, start, end):
    assert parse_period(text, TODAY) == (start, end)


@pytest.mark.parametrize("text", ["sometime", "tháng 13", "quý 5", "2026-03-31..2026-01-01", ""])
def test_unknown_periods_are_none(text):
    assert parse_period(text, TODAY) is None


@pytest.mark.parametrize(
    "text, amount",
    [
        ("1.000.000 đ", Decimal(1_000_000)),
        ("1,000,000", Decimal(1_000_000)),
        ("1.000.000,50 VND", Decimal("1000000.5")),
        ("1,000,000.50", Decimal("1000000.5")),
        ("1,5 triệu", Decimal(1_500_000)),
        ("2tr", Decimal(2_000_000)),
        ("500k", Decimal(500_000)),
        ("500 nghìn", Decimal(500_000)),
        ("3 tỷ", Decimal(3_000_000_000)),
        ("250000", Decimal(250_000)),
        ("12.5", Decimal("12.5")),
    ],
)
def test_amounts(text, amount):
    assert parse_amount(text) == amount


@pytest.mark.parametrize("text", ["abc", "đ", "--5", ""])
def test_non_amounts_are_none(text):
    assert parse_amount(text) is None
