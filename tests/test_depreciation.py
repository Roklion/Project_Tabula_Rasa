from datetime import date
from decimal import Decimal

import pytest

from tabula_rasa.depreciation import DepreciationError, straight_line_schedule


def test_quarterly_schedule_preserves_anchor_and_true_up() -> None:
    schedule = straight_line_schedule("100.00", "0", date(2026, 1, 31), 3)

    assert [item.scheduled_date for item in schedule] == [
        date(2026, 1, 31),
        date(2026, 4, 30),
        date(2026, 7, 31),
    ]
    assert [item.depreciation_amount for item in schedule] == [
        Decimal("33.33"),
        Decimal("33.33"),
        Decimal("33.34"),
    ]
    assert schedule[-1].cumulative_depreciation == Decimal("100.00")
    assert schedule[-1].remaining_book_value == Decimal("0.00")


def test_past_override_rebalances_future_quarters() -> None:
    schedule = straight_line_schedule(
        "110.00",
        "10.00",
        date(2025, 1, 15),
        4,
        overrides={2: {"amount": "10", "reason": "Prior schedule"}},
    )

    assert [item.depreciation_amount for item in schedule] == [
        Decimal("25.00"),
        Decimal("10.00"),
        Decimal("32.50"),
        Decimal("32.50"),
    ]
    assert schedule[1].is_override is True
    assert schedule[1].override_reason == "Prior schedule"
    assert schedule[-1].remaining_book_value == Decimal("10.00")


def test_retirement_stops_future_quarters_without_writeoff() -> None:
    schedule = straight_line_schedule(
        "100.00",
        "0.00",
        date(2026, 1, 1),
        4,
        retired_date=date(2026, 4, 1),
    )

    assert len(schedule) == 2
    assert schedule[-1].remaining_book_value == Decimal("50.00")


def test_full_life_overrides_must_reconcile_to_basis() -> None:
    with pytest.raises(DepreciationError, match="must total"):
        straight_line_schedule(
            "100",
            "0",
            date(2025, 1, 1),
            2,
            overrides={
                1: {"amount": "10", "reason": "Imported"},
                2: {"amount": "10", "reason": "Imported"},
            },
        )


@pytest.mark.parametrize(
    ("cost", "salvage", "quarters", "message"),
    [
        ("0", "0", 4, "greater than"),
        ("100", "100", 4, "less than cost"),
        ("100", "0", 0, "positive whole number"),
    ],
)
def test_invalid_schedule_terms_are_rejected(
    cost: str, salvage: str, quarters: int, message: str
) -> None:
    with pytest.raises(DepreciationError, match=message):
        straight_line_schedule(cost, salvage, date(2026, 1, 1), quarters)
