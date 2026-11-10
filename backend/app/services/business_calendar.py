"""
Support working hours and holidays (HND-07): when staff can answer, and by when a ticket should be answered.

Hours are per weekday (``"08:00-17:30"``, empty = closed); holidays are either
recurring ``MM-DD`` (30/4, 1/5, 2/9…) or exact ``YYYY-MM-DD`` dates (lunar
holidays such as Tết move every year, so admins add them per year).
"""

# Standard library imports
import re
from datetime import date, datetime, time, timedelta
from typing import Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DEFAULT_SUPPORT_HOURS = {
    "mon": "08:00-17:30", "tue": "08:00-17:30", "wed": "08:00-17:30", "thu": "08:00-17:30",
    "fri": "08:00-17:30", "sat": "08:00-12:00", "sun": "",
}
#: Fixed-date public holidays in Vietnam; Tết and Giỗ Tổ Hùng Vương follow the lunar calendar and are added per year.
DEFAULT_HOLIDAYS = ["01-01", "04-30", "05-01", "09-02"]
_RANGE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-4]):([0-5]\d)$")
_RECURRING = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")
#: Longest look-ahead when searching for the next open period.
MAX_DAYS_AHEAD = 366


class CalendarError(ValueError):
    """Malformed hours or holidays."""


def _parse_range(text: str) -> Optional[Tuple[time, time]]:
    """``"08:00-17:30"`` -> times; empty -> closed."""
    if not text:
        return None
    match = _RANGE.match(text.strip())
    if not match:
        raise CalendarError(f"hours must look like 08:00-17:30, got {text!r}")
    opens = time(int(match.group(1)), int(match.group(2)))
    closes = time.max if match.group(3) == "24" else time(int(match.group(3)), int(match.group(4)))
    if closes <= opens:
        raise CalendarError(f"closing time must be after opening time in {text!r}")
    return opens, closes


class BusinessCalendar:
    """Answers "is support open?" and "N working hours from now is when?"."""

    def __init__(self, hours: Dict[str, str], holidays: Iterable[str], time_zone: str):
        """
        Raises:
            CalendarError: Unknown weekday keys, malformed ranges or holidays.
        """
        unknown = set(hours) - set(WEEKDAYS)
        if unknown:
            raise CalendarError(f"unknown weekdays: {', '.join(sorted(unknown))}")
        self._hours = {day: _parse_range(hours.get(day, "")) for day in WEEKDAYS}
        self._recurring: set = set()
        self._dates: set = set()
        for holiday in holidays:
            holiday = holiday.strip()
            if _RECURRING.match(holiday):
                self._recurring.add(holiday)
            else:
                try:
                    self._dates.add(date.fromisoformat(holiday))
                except ValueError as exc:
                    raise CalendarError(f"holidays are MM-DD or YYYY-MM-DD, got {holiday!r}") from exc
        self._zone = ZoneInfo(time_zone)

    def _open_hours(self, day: date) -> Optional[Tuple[time, time]]:
        """Opening hours of ``day``, or ``None`` when closed (weekday off or holiday)."""
        if day in self._dates or day.strftime("%m-%d") in self._recurring:
            return None
        return self._hours[WEEKDAYS[day.weekday()]]

    def is_open(self, moment: datetime) -> bool:
        """True during working hours."""
        local = moment.astimezone(self._zone)
        hours = self._open_hours(local.date())
        return hours is not None and hours[0] <= local.time() < hours[1]

    def add_working_hours(self, start: datetime, hours: float) -> datetime:
        """
        The moment ``hours`` of working time after ``start`` (skipping nights,
        closed days and holidays).

        Raises:
            CalendarError: No working time in the next year (every day closed).
        """
        remaining = timedelta(hours=hours)
        cursor = start.astimezone(self._zone)
        for _ in range(MAX_DAYS_AHEAD * 2):
            window = self._open_hours(cursor.date())
            if window is not None:
                opens = datetime.combine(cursor.date(), window[0], tzinfo=self._zone)
                closes = datetime.combine(cursor.date(), window[1], tzinfo=self._zone)
                if cursor < opens:
                    cursor = opens
                if cursor < closes:
                    available = closes - cursor
                    if remaining <= available:
                        return cursor + remaining
                    remaining -= available
            cursor = datetime.combine(cursor.date() + timedelta(days=1), time.min, tzinfo=self._zone)
        raise CalendarError("support is closed every day of the next year")

    @staticmethod
    def validate(hours: Dict[str, str], holidays: List[str]) -> None:
        """
        Raises:
            CalendarError: The settings would not build a calendar.
        """
        BusinessCalendar(hours, holidays, "UTC")
