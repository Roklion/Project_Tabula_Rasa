"""Deterministic quarterly straight-line depreciation calculations."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, Mapping


CURRENCY_QUANTUM = Decimal("0.01")
STRAIGHT_LINE_METHOD = "Straight-line"


class DepreciationError(ValueError):
    """Raised when asset terms cannot produce a valid schedule."""


@dataclass(frozen=True)
class DepreciationPeriod:
    sequence: int
    scheduled_date: date
    depreciation_amount: Decimal
    cumulative_depreciation: Decimal
    remaining_book_value: Decimal
    is_override: bool = False
    override_reason: str = ""
    posting_status: str = "Pending"
    journal_entry_id: str = ""


def currency_decimal(value: Any, field: str) -> Decimal:
    """Return one finite currency value using the application's cent rounding."""
    try:
        result = Decimal(str(value).strip())
    except (AttributeError, InvalidOperation, ValueError):
        raise DepreciationError(f"{field} must be numeric") from None
    if not result.is_finite():
        raise DepreciationError(f"{field} must be finite")
    try:
        return result.quantize(CURRENCY_QUANTUM)
    except InvalidOperation:
        raise DepreciationError(f"{field} is too large") from None


def _quarter_date(anchor: date, offset: int) -> date:
    month_index = anchor.year * 12 + anchor.month - 1 + offset * 3
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(anchor.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _positive_quarters(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise DepreciationError(
            "Useful life must be a positive whole number of quarters"
        )
    return value


def straight_line_schedule(
    cost_basis: Any,
    salvage_value: Any,
    depreciation_start_date: date,
    useful_life_quarters: int,
    *,
    retired_date: date | None = None,
    overrides: Mapping[int, Mapping[str, Any]] | None = None,
) -> list[DepreciationPeriod]:
    """Calculate the quarterly source schedule, including durable overrides.

    An override fixes that period and all earlier periods. Any remaining basis
    is spread evenly over later quarters, with a final-cent true-up.
    """
    cost = currency_decimal(cost_basis, "Cost basis")
    salvage = currency_decimal(salvage_value, "Salvage value")
    quarter_count = _positive_quarters(useful_life_quarters)
    if cost <= 0:
        raise DepreciationError("Cost basis must be greater than $0.00")
    if salvage < 0 or salvage >= cost:
        raise DepreciationError(
            "Salvage value must be at least $0.00 and less than cost basis"
        )
    if not isinstance(depreciation_start_date, date):
        raise DepreciationError("Depreciation start date is invalid")

    normalized_overrides: dict[int, tuple[Decimal, str]] = {}
    for raw_sequence, details in (overrides or {}).items():
        try:
            sequence = int(raw_sequence)
        except (TypeError, ValueError):
            raise DepreciationError("Override period is invalid") from None
        if sequence < 1 or sequence > quarter_count:
            raise DepreciationError("Override period is outside the asset life")
        amount = currency_decimal(details.get("amount"), "Override amount")
        if amount < 0:
            raise DepreciationError("Override amount cannot be negative")
        reason = str(details.get("reason", "") or "").strip()
        if not reason:
            raise DepreciationError("Override reason is required")
        normalized_overrides[sequence] = (amount, reason)
    if retired_date is not None and any(
        _quarter_date(depreciation_start_date, sequence - 1) > retired_date
        for sequence in normalized_overrides
    ):
        raise DepreciationError(
            "Retirement cannot hide a saved depreciation override"
        )

    depreciable_basis = cost - salvage
    with localcontext() as context:
        context.prec = max(28, len(depreciable_basis.as_tuple().digits) + 12)
        standard = (depreciable_basis / quarter_count).quantize(CURRENCY_QUANTUM)

    periods: list[DepreciationPeriod] = []
    cumulative = Decimal("0.00")
    future_amount = standard
    for offset in range(quarter_count):
        sequence = offset + 1
        scheduled_date = _quarter_date(depreciation_start_date, offset)
        if retired_date is not None and scheduled_date > retired_date:
            break
        if sequence in normalized_overrides:
            amount, reason = normalized_overrides[sequence]
        elif sequence == quarter_count:
            amount, reason = depreciable_basis - cumulative, ""
        else:
            amount, reason = min(future_amount, depreciable_basis - cumulative), ""
        if amount > depreciable_basis - cumulative:
            raise DepreciationError(
                "Overrides through this period exceed the depreciable basis"
            )
        cumulative += amount
        periods.append(
            DepreciationPeriod(
                sequence=sequence,
                scheduled_date=scheduled_date,
                depreciation_amount=amount,
                cumulative_depreciation=cumulative,
                remaining_book_value=cost - cumulative,
                is_override=sequence in normalized_overrides,
                override_reason=reason,
            )
        )
        if sequence in normalized_overrides and sequence < quarter_count:
            remaining_basis = depreciable_basis - cumulative
            remaining_count = quarter_count - sequence
            with localcontext() as context:
                context.prec = max(
                    28,
                    len(remaining_basis.as_tuple().digits) + 12,
                )
                future_amount = (remaining_basis / remaining_count).quantize(
                    CURRENCY_QUANTUM
                )
    if len(periods) == quarter_count and cumulative != depreciable_basis:
        raise DepreciationError(
            "Overrides covering the full asset life must total the depreciable basis"
        )
    return periods


__all__ = [
    "CURRENCY_QUANTUM",
    "STRAIGHT_LINE_METHOD",
    "DepreciationError",
    "DepreciationPeriod",
    "currency_decimal",
    "straight_line_schedule",
]
