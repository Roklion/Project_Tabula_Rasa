from datetime import date

import pytest

from tabula_rasa.recurrence import (
    next_occurrence,
    occurrence_date,
    occurrence_id,
    occurrences_between,
)


def test_month_and_year_anchors_do_not_drift() -> None:
    anchor = date(2024, 1, 31)
    assert occurrence_date(anchor, "month", 1, 1) == date(2024, 2, 29)
    assert occurrence_date(anchor, "month", 1, 2) == date(2024, 3, 31)
    assert occurrence_date(anchor, "month", 1, 3) == date(2024, 4, 30)
    assert occurrence_date(date(2024, 2, 29), "year", 1, 1) == date(2025, 2, 28)


def test_next_occurrence_supports_every_n_days_and_weeks() -> None:
    assert next_occurrence(date(2024, 1, 1), "day", 3, date(2024, 1, 7)) == date(2024, 1, 10)
    assert next_occurrence(date(2024, 1, 1), "week", 2, date(2024, 1, 15)) == date(2024, 1, 29)


def test_next_occurrence_rejects_non_positive_or_fractional_intervals() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        next_occurrence(date(2024, 1, 1), "month", 0, date(2024, 1, 1))
    with pytest.raises(ValueError, match="positive integer"):
        next_occurrence(date(2024, 1, 1), "day", 1.5, date(2024, 1, 1))


def test_occurrences_between_is_inclusive_and_ids_are_stable() -> None:
    values = list(occurrences_between(date(2024, 1, 1), "month", 1, date(2024, 2, 1), date(2024, 4, 1)))
    assert values == [date(2024, 2, 1), date(2024, 3, 1), date(2024, 4, 1)]
    assert occurrence_id("schedule", values[0]) == occurrence_id("schedule", values[0])
    assert occurrence_id("schedule", values[0]) != occurrence_id("schedule", values[1])


def test_occurrences_between_jumps_to_the_first_date_in_range() -> None:
    values = list(
        occurrences_between(
            date(2024, 1, 31), "month", 1, date(2026, 1, 1), date(2026, 3, 31)
        )
    )
    assert values == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)]


@pytest.mark.parametrize("unit", ["hour", "monthss"])
def test_unknown_units_are_rejected(unit: str) -> None:
    with pytest.raises(ValueError):
        occurrence_date(date(2024, 1, 1), unit, 1, 1)
