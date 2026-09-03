from datetime import date

import pytest

from tabula_rasa.page_renderers.transactions.mixed_use import (
    _MixedUseReceiptStorage,
    mixed_use_preview,
)
from tabula_rasa.page_renderers.transactions.ledger import transaction_is_mixed_use
from tabula_rasa.storage import (
    decode_receipt_references,
    StorageConflictError,
    StorageValidationError,
)


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


def test_only_phase_a_mixed_use_provenance_is_protected() -> None:
    assert transaction_is_mixed_use(
        {"source_type": "mixed_use_expense", "source_id": "source-1"}
    )
    assert not transaction_is_mixed_use(
        {"source_type": "transaction_copy", "source_id": "transaction-1"}
    )
    assert not transaction_is_mixed_use(
        {"source_type": "mixed_use_expense", "source_id": ""}
    )


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


def test_source_aware_receipt_path_preserves_pair_and_generic_path_rejects(
    default_storage,
) -> None:
    account = default_storage.create_account("Mixed Checking", "Bank")
    category = default_storage.create_category("Mixed Office", "Expense")
    source = default_storage.create_mixed_use_expense(
        txn_date="2026-09-03",
        total_expense="100",
        business_use_percentage="50",
        account_id=account["id"],
        category_id=category["id"],
        allocation_rationale="Measured use",
    )
    reference = {"id": "a" * 32, "name": "receipt.pdf"}
    default_storage.link_mixed_use_receipt(
        source["id"], reference=reference, expected_source=source
    )
    projection = default_storage.list_transactions()[0]
    refreshed = default_storage.get_mixed_use_expense(source["id"])
    assert projection["receipt_references"] == refreshed["receipt_references"]
    with pytest.raises(StorageValidationError, match="changed through mixed-use"):
        default_storage.link_transaction_receipt(
            source["linked_transaction_id"],
            reference={"id": "b" * 32, "name": "other.pdf"},
        )
    with pytest.raises(StorageConflictError, match="changed"):
        default_storage.set_mixed_use_receipt_references(
            source["id"], [], expected_source=source
        )


def test_source_receipt_adapter_refreshes_snapshot_for_multiple_receipts(
    default_storage,
) -> None:
    account = default_storage.create_account("Adapter Checking", "Bank")
    category = default_storage.create_category("Adapter Office", "Expense")
    source = default_storage.create_mixed_use_expense(
        txn_date="2026-09-03",
        total_expense="100",
        business_use_percentage="50",
        account_id=account["id"],
        category_id=category["id"],
        allocation_rationale="Measured use",
    )
    adapter = _MixedUseReceiptStorage(default_storage, source["id"], source)
    adapter.link_transaction_receipt(
        source["linked_transaction_id"],
        reference={"id": "c" * 32, "name": "one.pdf"},
    )
    adapter.link_transaction_receipt(
        source["linked_transaction_id"],
        reference={"id": "d" * 32, "name": "two.pdf"},
    )
    refreshed = default_storage.get_mixed_use_expense(source["id"])
    assert len(decode_receipt_references(refreshed["receipt_references"])) == 2
