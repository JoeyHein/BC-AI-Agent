"""Alberta business days for the purchasing chase clock.

A business day is Monday to Friday, excluding Alberta's general holidays and
Heritage Day (the August civic holiday, which the office takes). When New
Year's Day, Canada Day, Remembrance Day, or Christmas falls on a Sunday, the
following Monday is the day off. A Saturday holiday is not moved.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """nth weekday in a month. weekday: Monday is 0. n is 1-based."""
    first = date(year, month, 1)
    shift = (weekday - first.weekday()) % 7
    return first + timedelta(days=shift + 7 * (n - 1))


def _easter(year: int) -> date:
    """Anonymous Gregorian algorithm. Returns Easter Sunday."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _observe(day: date) -> date:
    """Sunday holidays are taken Monday. Saturday holidays stay on Saturday."""
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


@lru_cache(maxsize=32)
def alberta_holidays(year: int) -> frozenset:
    """Days the office is closed in `year`."""
    easter = _easter(year)
    good_friday = easter - timedelta(days=2)
    days = {
        _observe(date(year, 1, 1)),
        _nth_weekday(year, 2, 0, 3),  # Family Day, third Monday
        good_friday,
        _nth_weekday(year, 5, 0, 4),  # Victoria Day, Monday on or before May 24
        _observe(date(year, 7, 1)),
        _nth_weekday(year, 8, 0, 1),  # Heritage Day
        _nth_weekday(year, 9, 0, 1),  # Labour Day
        _nth_weekday(year, 10, 0, 2),  # Thanksgiving
        _observe(date(year, 11, 11)),
        _observe(date(year, 12, 25)),
    }
    # Victoria Day is the Monday immediately before May 25.
    may_24 = date(year, 5, 24)
    victoria = may_24 - timedelta(days=(may_24.weekday() - 0) % 7)
    if victoria.month != 5:
        victoria = date(year, 5, 18)
    days.discard(_nth_weekday(year, 5, 0, 4))
    days.add(victoria)
    return frozenset(days)


def is_alberta_business_day(day: date) -> bool:
    if day.weekday() >= 5:
        return False
    return day not in alberta_holidays(day.year)


def add_business_days(start: date, days: int) -> date:
    """The date `days` Alberta business days after `start`. `start` is not counted."""
    if days < 0:
        raise ValueError("days must be zero or more")
    cursor = start
    left = days
    while left > 0:
        cursor += timedelta(days=1)
        if is_alberta_business_day(cursor):
            left -= 1
    return cursor


def business_days_between(start: date, end: date) -> int:
    """Alberta business days strictly after `start` and on or before `end`."""
    if end <= start:
        return 0
    count = 0
    cursor = start
    while cursor < end:
        cursor += timedelta(days=1)
        if is_alberta_business_day(cursor):
            count += 1
    return count
