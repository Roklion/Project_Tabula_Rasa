from __future__ import annotations

from decimal import Decimal

import pytest

from tabula_rasa.mixed_use import (
    MixedUseAllocationError,
    calculate_allocated_amount,
    validate_mixed_use_allocation,
)
from tabula_rasa.storage import (
    GoogleSheetsStorage,
    StorageConflictError,
)
from tests.mixed_use_storage._support import expense_inputs


def test_allocation_uses_decimal_currency_rounding_and_five_places() -> None:
    assert calculate_allocated_amount("123.45", "33.33333") == Decimal("41.15")
    normalized = validate_mixed_use_allocation("123.45", "33.33333")
    assert normalized.total_expense == "123.45"
    assert normalized.business_use_percentage == "33.33333"
    assert normalized.allocated_amount == "41.15"


def test_allocation_accepts_trailing_zero_percentage_precision() -> None:
    normalized = validate_mixed_use_allocation("100", "12.340000")

    assert normalized.business_use_percentage == "12.34"
    assert normalized.allocated_amount == "12.34"


def test_allocation_preserves_precision_before_currency_rounding() -> None:
    assert calculate_allocated_amount(
        "3165809505055861412909.65", "35.52850"
    ) == Decimal("1124764630003771722085.61")


@pytest.mark.parametrize("percentage", ["0", "-1", "100.00001", "0.000001"])
def test_allocation_rejects_percentage_boundaries_and_precision(
    percentage: str,
) -> None:
    with pytest.raises(MixedUseAllocationError):
        validate_mixed_use_allocation("100", percentage)


@pytest.mark.parametrize(
    "percentage",
    [
        "1e1000000000",
        "99.9999999999999999999999999999",
        "100.00000000000000000000000000001",
    ],
)
def test_allocation_rejects_large_or_overprecise_percentages(
    percentage: str,
) -> None:
    with pytest.raises(MixedUseAllocationError):
        validate_mixed_use_allocation("100", percentage)


def test_allocation_rejects_result_that_rounds_to_zero() -> None:
    with pytest.raises(MixedUseAllocationError, match=r"\$0.00"):
        validate_mixed_use_allocation("0.01", "0.00001")


def test_allocation_rejects_values_that_exceed_decimal_context() -> None:
    with pytest.raises(MixedUseAllocationError, match="too large"):
        validate_mixed_use_allocation("1e28", "50")


def test_mixed_use_create_persists_one_allocated_projection(
    default_storage: GoogleSheetsStorage,
) -> None:
    tag = default_storage.create_tag("Project")
    source = default_storage.create_mixed_use_expense(
        **expense_inputs(default_storage),
        total_expense="125.00",
        business_use_percentage="40.00000",
        allocation_rationale="Dedicated office percentage",
        tag_ids=[tag["id"]],
    )

    transactions = default_storage.list_transactions()
    assert len(default_storage.list_mixed_use_expenses()) == 1
    assert len(transactions) == 1
    assert transactions[0]["amount"] == "50.00"
    assert transactions[0]["source_type"] == "mixed_use_expense"
    assert transactions[0]["source_id"] == source["id"]
    assert transactions[0]["description"] == (
        "Internet service\nAllocation rationale: Dedicated office percentage"
    )
    assert source["linked_transaction_id"] == transactions[0]["id"]
    assert source["allocated_amount"] == "50.00"
    assert source["tag_ids"] == [tag["id"]]
    assert (
        default_storage._rows("MixedUseExpenses", force_refresh=True)[0].values[
            "tag_ids"
        ]
        == f'["{tag["id"]}"]'
    )
    assert (
        "payee"
        not in default_storage._rows("MixedUseExpenses", force_refresh=True)[0].values
    )


def test_mixed_use_validation_accepts_insignificant_sheet_number_formatting(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    source_sheet = default_storage._worksheet("MixedUseExpenses")
    headers = default_storage._headers("MixedUseExpenses")
    row = source_sheet.rows[1]
    row[headers.index("total_expense")] = "100"
    row[headers.index("business_use_percentage")] = "50"
    row[headers.index("allocated_amount")] = "50"
    default_storage._invalidate("MixedUseExpenses")

    listed = default_storage.list_mixed_use_expenses()

    assert listed[0]["id"] == source["id"]
    assert listed[0]["total_expense"] == "100"
    assert listed[0]["business_use_percentage"] == "50"
    assert listed[0]["allocated_amount"] == "50"


def test_transaction_edit_canonicalizes_padded_id(
    default_storage: GoogleSheetsStorage,
) -> None:
    transaction = default_storage.create_transaction(
        **expense_inputs(default_storage),
        kind="Expense",
        amount="20",
    )

    edited = default_storage.edit_transaction(
        f"  {transaction['id']}  ", description="Updated"
    )

    assert edited["id"] == transaction["id"]
    assert edited["description"] == "Updated"


def test_mixed_use_edit_updates_same_projection_and_detects_stale_source(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="25",
        allocation_rationale="Quarterly measured usage",
    )
    original_projection_created_at = default_storage.list_transactions()[0][
        "created_at"
    ]
    edited = default_storage.edit_mixed_use_expense(
        source["id"],
        expected_source=source,
        total_expense="200",
        business_use_percentage="12.5",
        reference="UPDATED-119",
        allocation_rationale="Updated quarterly measurement",
    )

    assert edited["id"] == source["id"]
    assert edited["linked_transaction_id"] == source["linked_transaction_id"]
    transaction = default_storage.list_transactions()[0]
    assert transaction["id"] == source["linked_transaction_id"]
    assert transaction["amount"] == "25.00"
    assert transaction["reference"] == "UPDATED-119"
    assert transaction["created_at"] == original_projection_created_at
    assert transaction["description"].endswith(
        "Allocation rationale: Updated quarterly measurement"
    )
    with pytest.raises(StorageConflictError, match="changed"):
        default_storage.edit_mixed_use_expense(
            source["id"], expected_source=source, total_expense="300"
        )


def test_mixed_use_edit_preserves_projection_tags_when_omitted(
    default_storage: GoogleSheetsStorage,
) -> None:
    tag = default_storage.create_tag("Project")
    source = default_storage.create_mixed_use_expense(
        **expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured business use",
        tag_ids=[tag["id"]],
    )

    default_storage.edit_mixed_use_expense(
        source["id"], allocation_rationale="Updated measurement"
    )

    projection = default_storage.list_transactions()[0]
    assert projection["tag_ids"] == [tag["id"]]
