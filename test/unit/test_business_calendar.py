"""Support working hours, holidays and ticket due times (HND-07, HND-14)."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from services.business_calendar import DEFAULT_HOLIDAYS, DEFAULT_SUPPORT_HOURS, BusinessCalendar, CalendarError

ZONE = ZoneInfo("Asia/Ho_Chi_Minh")
CALENDAR = BusinessCalendar(DEFAULT_SUPPORT_HOURS, [*DEFAULT_HOLIDAYS, "2027-02-06"], "Asia/Ho_Chi_Minh")


def _at(*parts):
    return datetime(*parts, tzinfo=ZONE)


def test_open_during_hours_closed_at_night_on_sundays_and_holidays():
    assert CALENDAR.is_open(_at(2026, 9, 29, 10, 0))  # Tuesday
    assert not CALENDAR.is_open(_at(2026, 9, 29, 18, 0))
    assert not CALENDAR.is_open(_at(2026, 10, 4, 10, 0))  # Sunday
    assert not CALENDAR.is_open(_at(2026, 9, 2, 10, 0))  # National Day
    assert CALENDAR.is_open(_at(2026, 10, 3, 11, 0)) and not CALENDAR.is_open(_at(2026, 10, 3, 13, 0))  # Saturday morning


@pytest.mark.parametrize(
    "start, hours, due",
    [
        (_at(2026, 9, 29, 9, 0), 2, _at(2026, 9, 29, 11, 0)),
        (_at(2026, 9, 29, 16, 30), 2, _at(2026, 9, 30, 9, 0)),  # 1 h today, 1 h tomorrow
        (_at(2026, 9, 29, 20, 0), 1, _at(2026, 9, 30, 9, 0)),  # after hours: starts next morning
        (_at(2026, 10, 3, 11, 0), 2, _at(2026, 10, 5, 9, 0)),  # Saturday half day, Sunday closed
        (_at(2026, 9, 1, 17, 0), 1, _at(2026, 9, 3, 8, 30)),  # 30 min left on 1/9, 2/9 is a holiday
    ],
)
def test_due_time_counts_only_working_hours(start, hours, due):
    assert CALENDAR.add_working_hours(start, hours) == due


def test_malformed_settings_are_refused():
    with pytest.raises(CalendarError):
        BusinessCalendar({"mon": "17:00-08:00"}, [], "UTC")
    with pytest.raises(CalendarError):
        BusinessCalendar({"monday": "08:00-17:00"}, [], "UTC")
    with pytest.raises(CalendarError):
        BusinessCalendar({}, ["31/12"], "UTC")
    with pytest.raises(CalendarError, match="closed every day"):
        BusinessCalendar({}, [], "UTC").add_working_hours(_at(2026, 9, 29, 9, 0), 1)
