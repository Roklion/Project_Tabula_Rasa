"""Domain rules for cost-based mixed-use expense allocation.

This module deliberately contains no Streamlit or storage concerns.  The
same calculation is used when a mixed-use source is validated for persistence
and when a future UI builds a live preview.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any


CURRENCY_QUANTUM = Decimal("0.01")
PERCENTAGE_QUANTUM = Decimal("0.00001")
MIXED_USE_SOURCE_TYPE = "mixed_use_expense"


class MixedUseAllocationError(ValueError):
    """Raised when mixed-use allocation inputs cannot produce a valid amount."""


@dataclass(frozen=True)
class MixedUseAllocation:
    """Canonical, persisted representation of an allocation."""

    total_expense: str
    business_use_percentage: str
    allocated_amount: str


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value).strip())
    except (AttributeError, InvalidOperation, ValueError):
        raise MixedUseAllocationError(f"{field} must be numeric") from None
    if not result.is_finite():
        raise MixedUseAllocationError(f"{field} must be finite")
    return result


def _decimal_places(value: Decimal) -> int:
    return max(0, -value.as_tuple().exponent)


def _quantize(value: Decimal, quantum: Decimal, field: str) -> Decimal:
    try:
        return value.quantize(quantum)
    except InvalidOperation:
        raise MixedUseAllocationError(f"{field} is too large") from None


def calculate_allocated_amount(
    total_expense: Any,
    business_use_percentage: Any,
) -> Decimal:
    """Return the currency-rounded business portion of a mixed-use expense."""
    total = _decimal(total_expense, "Total expense")
    total = _quantize(total, CURRENCY_QUANTUM, "Total expense")
    percentage = _decimal(
        business_use_percentage, "Business-use percentage"
    ).normalize()
    if total <= 0:
        raise MixedUseAllocationError("Total expense must be greater than zero")
    if percentage <= 0:
        raise MixedUseAllocationError(
            "Business-use percentage must be greater than zero"
        )
    if percentage > 100:
        raise MixedUseAllocationError(
            "Business-use percentage must be no more than 100"
        )
    if _decimal_places(percentage) > 5:
        raise MixedUseAllocationError(
            "Business-use percentage supports at most 5 decimal places"
        )
    with localcontext() as context:
        context.prec = max(
            28,
            len(total.as_tuple().digits) + len(percentage.as_tuple().digits) + 10,
        )
        allocated = _quantize(
            total * percentage / Decimal("100"),
            CURRENCY_QUANTUM,
            "Allocated amount",
        )
    if allocated <= 0:
        raise MixedUseAllocationError(
            "Allocated business amount must be greater than $0.00"
        )
    return allocated


def validate_mixed_use_allocation(
    total_expense: Any,
    business_use_percentage: Any,
) -> MixedUseAllocation:
    """Validate and normalize all persisted allocation values."""
    total = _decimal(total_expense, "Total expense")
    percentage = _decimal(business_use_percentage, "Business-use percentage")
    allocated = calculate_allocated_amount(total, percentage)
    return MixedUseAllocation(
        total_expense=format(_quantize(total, CURRENCY_QUANTUM, "Total expense"), "f"),
        business_use_percentage=format(
            _quantize(
                percentage, PERCENTAGE_QUANTUM, "Business-use percentage"
            ),
        ).rstrip("0").rstrip(".")
        or "0",
        allocated_amount=format(allocated, "f"),
    )
