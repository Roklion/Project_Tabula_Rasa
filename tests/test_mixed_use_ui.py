from datetime import date

import pytest

from tabula_rasa.page_renderers.transactions.mixed_use import mixed_use_preview
from tabula_rasa.storage import StorageValidationError


def test_mixed_use_preview_uses_decimal_allocation_and_rationale() -> None:
    preview = mixed_use_preview(
        txn_date=date(2026, 9, 3),
        account="Operating > Checking",
        payee="Vendor",
        category="Office",
        description="Supplies",
        total_expense="123.45",
        business_use_percentage="33.33333",
        allocation_rationale="Measured workspace use",
    )
    assert preview["allocated_amount"] == "41.15"
    assert preview["status"] == "ready"
    assert "Measured workspace use" in preview["description"]


def test_mixed_use_preview_is_safe_for_incomplete_inputs() -> None:
    preview = mixed_use_preview(
        txn_date=None,
        account="",
        payee="",
        category="",
        description="",
        total_expense="",
        business_use_percentage="",
        allocation_rationale="",
    )
    assert preview["allocated_amount"] == "—"
    assert preview["status"] != "ready"
    assert preview["description"] == "—"


def test_generic_create_rejects_fabricated_mixed_use_projection(default_storage) -> None:
    with pytest.raises(StorageValidationError, match="changed through mixed-use"):
        default_storage.create_transaction(
            txn_date="2026-09-03",
            kind="Expense",
            amount="10",
            account_id="missing",
            category_id="missing",
            source_type="mixed_use_expense",
            source_id="source",
        )
