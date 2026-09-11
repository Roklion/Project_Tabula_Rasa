"""Calendar and identity rules for recurring expense schedules.

The recurrence model is intentionally small: a positive interval and one of
day, week, month, or year.  Month and year dates are always calculated from
the original anchor, so a short month never causes a schedule to drift.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from enum import StrEnum
from typing import Iterable
from uuid import NAMESPACE_URL, uuid5


class RecurrenceUnit(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


def normalize_unit(value: str | RecurrenceUnit) -> RecurrenceUnit:
    text = str(value).strip().casefold()
    aliases = {"days": "day", "weeks": "week", "months": "month", "years": "year"}
    text = aliases.get(text, text)
    try:
        return RecurrenceUnit(text)
    except ValueError as exc:
        raise ValueError("recurrence unit must be day, week, month, or year") from exc


def _month_date(anchor: date, months: int) -> date:
    index = anchor.year * 12 + (anchor.month - 1) + months
    year, month_index = divmod(index, 12)
    month = month_index + 1
    return date(year, month, min(anchor.day, calendar.monthrange(year, month)[1]))


def occurrence_date(anchor: date, unit: str | RecurrenceUnit, interval: int, index: int) -> date:
    """Return the zero-based occurrence at *index* from *anchor*."""
    if not isinstance(anchor, date):
        raise TypeError("anchor must be a date")
    if interval < 1 or int(interval) != interval:
        raise ValueError("recurrence interval must be a positive integer")
    if index < 0:
        raise ValueError("occurrence index must not be negative")
    unit = normalize_unit(unit)
    steps = int(interval) * index
    if unit is RecurrenceUnit.DAY:
        return anchor + timedelta(days=steps)
    if unit is RecurrenceUnit.WEEK:
        return anchor + timedelta(days=steps * 7)
    if unit is RecurrenceUnit.MONTH:
        return _month_date(anchor, steps)
    try:
        return date(anchor.year + steps, anchor.month, anchor.day)
    except ValueError:
        # February 29 anchors occur on the last day of February in non-leap years.
        return date(anchor.year + steps, anchor.month, calendar.monthrange(anchor.year + steps, anchor.month)[1])


def next_occurrence(anchor: date, unit: str | RecurrenceUnit, interval: int, after: date) -> date:
    """Return the first occurrence strictly after *after*."""
    if interval < 1 or int(interval) != interval:
        raise ValueError("recurrence interval must be a positive integer")
    unit = normalize_unit(unit)
    if after < anchor:
        return anchor
    if unit is RecurrenceUnit.DAY:
        distance = (after - anchor).days
        index = distance // interval + 1
    elif unit is RecurrenceUnit.WEEK:
        distance = (after - anchor).days // 7
        index = distance // interval + 1
    elif unit is RecurrenceUnit.MONTH:
        distance = (after.year - anchor.year) * 12 + after.month - anchor.month
        index = max(0, distance // interval)
        while occurrence_date(anchor, unit, interval, index) <= after:
            index += 1
    else:
        distance = after.year - anchor.year
        index = max(0, distance // interval)
        while occurrence_date(anchor, unit, interval, index) <= after:
            index += 1
    return occurrence_date(anchor, unit, interval, index)


def occurrences_between(
    anchor: date,
    unit: str | RecurrenceUnit,
    interval: int,
    start: date,
    end: date,
) -> Iterable[date]:
    """Yield scheduled dates in the inclusive ``start``/``end`` range."""
    if end < start:
        return
    unit = normalize_unit(unit)
    current = (
        anchor
        if start <= anchor
        else next_occurrence(anchor, unit, interval, start - timedelta(days=1))
    )
    while current <= end:
        yield current
        current = next_occurrence(anchor, unit, interval, current)


def occurrence_id(schedule_id: str, scheduled_date: date | str, role: str = "expense") -> str:
    """Build a deterministic record ID for a schedule occurrence."""
    value = scheduled_date.isoformat() if isinstance(scheduled_date, date) else str(scheduled_date).strip()
    return str(uuid5(NAMESPACE_URL, f"tabula-rasa:recurring:{schedule_id}:{value}:{role}"))


__all__ = [
    "RecurrenceUnit",
    "normalize_unit",
    "occurrence_date",
    "next_occurrence",
    "occurrences_between",
    "occurrence_id",
]
