from __future__ import annotations

import csv
import hashlib
import io
import json
import threading
import zipfile
from decimal import Decimal
from unittest.mock import Mock

import pytest

from tabula_rasa.mixed_use import (
    MixedUseAllocationError,
    calculate_allocated_amount,
    validate_mixed_use_allocation,
)
from tabula_rasa.storage import (
    GoogleSheetsStorage,
    StorageConflictError,
    StorageUnavailableError,
    StorageValidationError,
)
from tabula_rasa.storage import google_sheets as google_sheets_module
from tabula_rasa.storage.google_sheets import (
    BACKUP_FORMAT_VERSION,
)
from tests.fakes import FakeWorkbook


def _expense_inputs(storage: GoogleSheetsStorage) -> dict[str, str]:
    account = next(
        account
        for account in storage.list_accounts(active_only=False)
        if account["name"] == "Checking"
    )
    category = next(
        category
        for category in storage.list_categories()
        if category["name"] == "Office"
    )
    payee = storage.create_payee("Office vendor")
    return {
        "txn_date": "2026-09-01",
        "account_id": account["id"],
        "category_id": category["id"],
        "payee_id": payee["id"],
        "description": "Internet service",
        "reference": "INV-119",
    }


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
        **_expense_inputs(default_storage),
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
    assert default_storage._rows("MixedUseExpenses", force_refresh=True)[0].values[
        "tag_ids"
    ] == f'["{tag["id"]}"]'
    assert "payee" not in default_storage._rows(
        "MixedUseExpenses", force_refresh=True
    )[0].values


def test_mixed_use_validation_accepts_insignificant_sheet_number_formatting(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
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
        **_expense_inputs(default_storage),
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
        **_expense_inputs(default_storage),
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
        **_expense_inputs(default_storage),
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


def test_category_kind_change_rejects_mixed_use_references(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured business use",
    )

    with pytest.raises(StorageConflictError, match="mixed-use expense"):
        default_storage.edit_category(
            f" {source['category_id']} ", kind="Income"
        )

    category = next(
        item
        for item in default_storage.list_categories()
        if item["id"] == source["category_id"]
    )
    assert category["kind"] == "Expense"


def test_category_edit_shares_mixed_use_creation_lock(
    default_storage: GoogleSheetsStorage,
) -> None:
    category = next(
        item for item in default_storage.list_categories() if item["name"] == "Office"
    )
    started = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    def edit_category() -> None:
        started.set()
        try:
            default_storage.edit_category(category["id"], name="Office updated")
        except BaseException as error:  # pragma: no cover - assertion below reports it
            errors.append(error)
        finally:
            finished.set()

    worker = threading.Thread(target=edit_category)
    with google_sheets_module._MIXED_USE_CREATE_LOCK:
        worker.start()
        assert started.wait(1)
        assert not finished.wait(0.1)
    assert finished.wait(1)
    worker.join(timeout=1)
    assert not errors


def test_mixed_use_edit_shares_mixed_use_creation_lock(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    started = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    def edit_mixed_use() -> None:
        started.set()
        try:
            default_storage.edit_mixed_use_expense(
                source["id"], allocation_rationale="Updated use"
            )
        except BaseException as error:  # pragma: no cover - assertion below reports it
            errors.append(error)
        finally:
            finished.set()

    worker = threading.Thread(target=edit_mixed_use)
    with google_sheets_module._MIXED_USE_CREATE_LOCK:
        worker.start()
        assert started.wait(1)
        assert not finished.wait(0.1)
    assert finished.wait(1)
    worker.join(timeout=1)
    assert not errors


def test_transaction_edit_shares_mixed_use_creation_lock(
    default_storage: GoogleSheetsStorage,
) -> None:
    transaction = default_storage.create_transaction(
        **_expense_inputs(default_storage), kind="Expense", amount="10"
    )
    started = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    def edit_transaction() -> None:
        started.set()
        try:
            default_storage.edit_transaction(transaction["id"], description="Updated")
        except BaseException as error:  # pragma: no cover - assertion below reports it
            errors.append(error)
        finally:
            finished.set()

    worker = threading.Thread(target=edit_transaction)
    with google_sheets_module._MIXED_USE_CREATE_LOCK:
        worker.start()
        assert started.wait(1)
        assert not finished.wait(0.1)
    assert finished.wait(1)
    worker.join(timeout=1)
    assert not errors


def test_bulk_category_change_shares_mixed_use_creation_lock(
    default_storage: GoogleSheetsStorage,
) -> None:
    transaction = default_storage.create_transaction(
        **_expense_inputs(default_storage), kind="Expense", amount="10"
    )
    category = next(
        item
        for item in default_storage.list_categories()
        if item["kind"] == "Expense" and item["id"] != transaction["category_id"]
    )
    started = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    def change_category() -> None:
        started.set()
        try:
            default_storage.bulk_change_transaction_category(
                [transaction["id"]],
                expected_transactions=[transaction],
                category_id=category["id"],
            )
        except BaseException as error:  # pragma: no cover - assertion below reports it
            errors.append(error)
        finally:
            finished.set()

    worker = threading.Thread(target=change_category)
    with google_sheets_module._MIXED_USE_CREATE_LOCK:
        worker.start()
        assert started.wait(1)
        assert not finished.wait(0.1)
    assert finished.wait(1)
    worker.join(timeout=1)
    assert not errors


def test_transaction_receipt_setter_shares_mixed_use_creation_lock(
    default_storage: GoogleSheetsStorage,
) -> None:
    transaction = default_storage.create_transaction(
        **_expense_inputs(default_storage), kind="Expense", amount="10"
    )
    started = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    def set_receipt() -> None:
        started.set()
        try:
            default_storage.set_transaction_receipt_references(
                transaction["id"], []
            )
        except BaseException as error:  # pragma: no cover - assertion below reports it
            errors.append(error)
        finally:
            finished.set()

    worker = threading.Thread(target=set_receipt)
    with google_sheets_module._MIXED_USE_CREATE_LOCK:
        worker.start()
        assert started.wait(1)
        assert not finished.wait(0.1)
    assert finished.wait(1)
    worker.join(timeout=1)
    assert not errors


def test_transaction_receipt_unlink_shares_mixed_use_creation_lock(
    default_storage: GoogleSheetsStorage,
) -> None:
    transaction = default_storage.create_transaction(
        **_expense_inputs(default_storage), kind="Expense", amount="10"
    )
    started = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    def unlink_receipt() -> None:
        started.set()
        try:
            default_storage.unlink_transaction_receipt(
                transaction["id"], file_id="missing-file"
            )
        except BaseException as error:  # pragma: no cover - assertion below reports it
            errors.append(error)
        finally:
            finished.set()

    worker = threading.Thread(target=unlink_receipt)
    with google_sheets_module._MIXED_USE_CREATE_LOCK:
        worker.start()
        assert started.wait(1)
        assert not finished.wait(0.1)
    assert finished.wait(1)
    worker.join(timeout=1)
    assert not errors


def test_legacy_receipt_initialization_shares_mixed_use_creation_lock(
    default_storage: GoogleSheetsStorage,
) -> None:
    transaction = default_storage.create_transaction(
        **_expense_inputs(default_storage), kind="Expense", amount="10"
    )
    transaction_sheet = default_storage._worksheet("Transactions")
    transaction_headers = default_storage._headers("Transactions")
    transaction_sheet.rows[1][transaction_headers.index("receipt_references")] = ""
    default_storage._invalidate("Transactions")
    reference = {
        "id": "legacyreceipt01",
        "name": "receipt.pdf",
        "receipt_id": "0123456789abcdef0123456789abcdef",
        "original_filename": "receipt.pdf",
        "mime_type": "application/pdf",
        "byte_size": 1,
        "sha256": "a" * 64,
    }
    started = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    def initialize_receipt() -> None:
        started.set()
        try:
            default_storage.initialize_legacy_transaction_receipts(
                transaction["id"], references=[reference]
            )
        except BaseException as error:  # pragma: no cover - assertion below reports it
            errors.append(error)
        finally:
            finished.set()

    worker = threading.Thread(target=initialize_receipt)
    with google_sheets_module._MIXED_USE_CREATE_LOCK:
        worker.start()
        assert started.wait(1)
        assert not finished.wait(0.1)
    assert finished.wait(1)
    worker.join(timeout=1)
    assert not errors


def test_receipt_remap_shares_mixed_use_creation_lock(
    default_storage: GoogleSheetsStorage,
) -> None:
    transaction = default_storage.create_transaction(
        **_expense_inputs(default_storage), kind="Expense", amount="10"
    )
    old_reference = {
        "id": "oldreceipt01",
        "name": "old.pdf",
        "receipt_id": "fedcba9876543210fedcba9876543210",
        "original_filename": "old.pdf",
        "mime_type": "application/pdf",
        "byte_size": 1,
        "sha256": "a" * 64,
    }
    new_reference = {**old_reference, "id": "newreceipt01", "name": "new.pdf"}
    default_storage.set_transaction_receipt_references(
        transaction["id"], [old_reference]
    )
    started = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    def remap_receipt() -> None:
        started.set()
        try:
            default_storage.remap_transaction_receipt(
                transaction["id"],
                old_file_id=old_reference["id"],
                reference=new_reference,
            )
        except BaseException as error:  # pragma: no cover - assertion below reports it
            errors.append(error)
        finally:
            finished.set()

    worker = threading.Thread(target=remap_receipt)
    with google_sheets_module._MIXED_USE_CREATE_LOCK:
        worker.start()
        assert started.wait(1)
        assert not finished.wait(0.1)
    assert finished.wait(1)
    worker.join(timeout=1)
    assert not errors


def test_mixed_use_delete_shares_mixed_use_creation_lock(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    started = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    def delete_mixed_use() -> None:
        started.set()
        try:
            default_storage.delete_mixed_use_expense(source["id"])
        except BaseException as error:  # pragma: no cover - assertion below reports it
            errors.append(error)
        finally:
            finished.set()

    worker = threading.Thread(target=delete_mixed_use)
    with google_sheets_module._MIXED_USE_CREATE_LOCK:
        worker.start()
        assert started.wait(1)
        assert not finished.wait(0.1)
    assert finished.wait(1)
    worker.join(timeout=1)
    assert not errors


def test_category_delete_shares_mixed_use_creation_lock(
    default_storage: GoogleSheetsStorage,
) -> None:
    category = default_storage.create_category("Unused category", "Expense")
    started = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    def delete_category() -> None:
        started.set()
        try:
            default_storage.delete_category(category["id"])
        except BaseException as error:  # pragma: no cover - assertion below reports it
            errors.append(error)
        finally:
            finished.set()

    worker = threading.Thread(target=delete_category)
    with google_sheets_module._MIXED_USE_CREATE_LOCK:
        worker.start()
        assert started.wait(1)
        assert not finished.wait(0.1)
    assert finished.wait(1)
    worker.join(timeout=1)
    assert not errors


def test_transaction_delete_shares_mixed_use_creation_lock(
    default_storage: GoogleSheetsStorage,
) -> None:
    transaction = default_storage.create_transaction(
        **_expense_inputs(default_storage), kind="Expense", amount="10"
    )
    started = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    def delete_transaction() -> None:
        started.set()
        try:
            default_storage.delete_transaction(transaction["id"])
        except BaseException as error:  # pragma: no cover - assertion below reports it
            errors.append(error)
        finally:
            finished.set()

    worker = threading.Thread(target=delete_transaction)
    with google_sheets_module._MIXED_USE_CREATE_LOCK:
        worker.start()
        assert started.wait(1)
        assert not finished.wait(0.1)
    assert finished.wait(1)
    worker.join(timeout=1)
    assert not errors


def test_bulk_transaction_delete_shares_mixed_use_creation_lock(
    default_storage: GoogleSheetsStorage,
) -> None:
    transaction = default_storage.create_transaction(
        **_expense_inputs(default_storage), kind="Expense", amount="10"
    )
    started = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    def delete_transaction() -> None:
        started.set()
        try:
            default_storage.bulk_delete_transactions(
                [transaction["id"]], expected_transactions=[transaction]
            )
        except BaseException as error:  # pragma: no cover - assertion below reports it
            errors.append(error)
        finally:
            finished.set()

    worker = threading.Thread(target=delete_transaction)
    with google_sheets_module._MIXED_USE_CREATE_LOCK:
        worker.start()
        assert started.wait(1)
        assert not finished.wait(0.1)
    assert finished.wait(1)
    worker.join(timeout=1)
    assert not errors


def test_category_delete_rejects_orphaned_mixed_use_source(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    transaction_sheet = default_storage._worksheet("Transactions")
    transaction_sheet.rows.pop(1)
    default_storage._invalidate("Transactions")

    with pytest.raises(StorageConflictError, match="mixed-use expenses"):
        default_storage.delete_category(source["category_id"])


def test_generic_transaction_mutations_reject_mixed_use_projections(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured business use",
    )
    projection = default_storage.list_transactions()[0]
    replacement = next(
        category
        for category in default_storage.list_categories()
        if category["kind"] == "Expense"
        and category["id"] != projection["category_id"]
    )

    with pytest.raises(StorageValidationError, match="mixed-use expense APIs"):
        default_storage.edit_transaction(projection["id"], description="Changed")
    with pytest.raises(StorageValidationError, match="mixed-use expense APIs"):
        default_storage.delete_transaction(projection["id"])
    with pytest.raises(StorageValidationError, match="mixed-use expense APIs"):
        default_storage.bulk_change_transaction_category(
            [projection["id"]],
            expected_transactions=[projection],
            category_id=replacement["id"],
        )
    with pytest.raises(StorageValidationError, match="mixed-use expense APIs"):
        default_storage.bulk_delete_transactions(
            [projection["id"]], expected_transactions=[projection]
        )

    assert default_storage.get_mixed_use_expense(source["id"])["linked_transaction_id"] == projection[
        "id"
    ]


def test_mixed_use_create_rejects_transaction_collision_before_creating_payee(
    default_storage: GoogleSheetsStorage,
) -> None:
    transaction = default_storage.create_transaction(
        **_expense_inputs(default_storage), kind="Expense", amount="10"
    )
    mixed_use_inputs = _expense_inputs(default_storage)
    payees_before = default_storage.list_payees(active_only=False)
    mixed_use_inputs.update(
        payee_id="",
        new_payee_name="Should not be created",
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
        linked_transaction_id=transaction["id"],
    )

    with pytest.raises(StorageConflictError, match="already in use"):
        default_storage.create_mixed_use_expense(**mixed_use_inputs)

    assert default_storage.list_payees(active_only=False) == payees_before


def test_mixed_use_writes_reject_receipts_owned_by_another_transaction(
    default_storage: GoogleSheetsStorage,
) -> None:
    owner = default_storage.create_transaction(
        **_expense_inputs(default_storage), kind="Expense", amount="10"
    )
    reference = {"id": "ownedreceipt01", "name": "Receipt.pdf"}
    default_storage.set_transaction_receipt_references(owner["id"], [reference])
    mixed_inputs = _expense_inputs(default_storage)
    mixed_inputs["receipt_references"] = [reference]

    with pytest.raises(StorageConflictError, match="already linked"):
        default_storage.create_mixed_use_expense(
            **mixed_inputs,
            total_expense="100",
            business_use_percentage="50",
            allocation_rationale="Measured use",
        )

    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    with pytest.raises(StorageConflictError, match="already linked"):
        default_storage.edit_mixed_use_expense(
            source["id"], receipt_references=[reference]
        )


def test_mixed_use_receipt_remap_rejects_receipt_owned_by_another_transaction(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    old_reference = {
        "id": "remap-old-receipt",
        "name": "Old.pdf",
        "receipt_id": "0123456789abcdef0123456789abcdef",
        "original_filename": "Old.pdf",
        "mime_type": "application/pdf",
        "byte_size": 1,
        "sha256": "a" * 64,
    }
    replacement = {
        **old_reference,
        "id": "remap-owned-receipt",
        "name": "Replacement.pdf",
        "receipt_id": "fedcba9876543210fedcba9876543210",
        "original_filename": "Replacement.pdf",
        "sha256": "b" * 64,
    }
    default_storage.set_mixed_use_receipt_references(
        source["id"], [old_reference], expected_source=source
    )
    owner = default_storage.create_transaction(
        **_expense_inputs(default_storage), kind="Expense", amount="10"
    )
    default_storage.set_transaction_receipt_references(owner["id"], [replacement])
    refreshed_source = default_storage.get_mixed_use_expense(source["id"])

    with pytest.raises(StorageConflictError, match="already linked"):
        default_storage.remap_mixed_use_receipt(
            source["id"],
            old_file_id=old_reference["id"],
            reference=replacement,
            expected_source=refreshed_source,
        )

    assert default_storage.get_mixed_use_expense(source["id"])[
        "receipt_references"
    ] == refreshed_source["receipt_references"]


def test_generic_receipt_setter_rejects_receipts_owned_by_another_transaction(
    default_storage: GoogleSheetsStorage,
) -> None:
    owner = default_storage.create_transaction(
        **_expense_inputs(default_storage), kind="Expense", amount="10"
    )
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    reference = {"id": "setterowned01", "name": "Receipt.pdf"}
    default_storage.set_transaction_receipt_references(owner["id"], [reference])

    with pytest.raises(StorageValidationError, match="changed through mixed-use"):
        default_storage.set_transaction_receipt_references(
            source["linked_transaction_id"], [reference]
        )


@pytest.mark.parametrize(
    "operation",
    [
        "set_transaction_receipt_references",
        "initialize_legacy_transaction_receipts",
        "link_transaction_receipt",
        "remap_transaction_receipt",
        "unlink_transaction_receipt",
    ],
)
def test_every_generic_receipt_mutation_rejects_mixed_use_projection(
    default_storage: GoogleSheetsStorage, operation: str
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    transaction_id = source["linked_transaction_id"]
    reference = {"id": "generic-guard-receipt", "name": "Receipt.pdf"}

    with pytest.raises(StorageValidationError, match="changed through mixed-use"):
        if operation == "set_transaction_receipt_references":
            default_storage.set_transaction_receipt_references(
                transaction_id, [reference]
            )
        elif operation == "initialize_legacy_transaction_receipts":
            default_storage.initialize_legacy_transaction_receipts(
                transaction_id, references=[reference]
            )
        elif operation == "link_transaction_receipt":
            default_storage.link_transaction_receipt(
                transaction_id, reference=reference
            )
        elif operation == "remap_transaction_receipt":
            default_storage.remap_transaction_receipt(
                transaction_id, old_file_id="old-receipt", reference=reference
            )
        else:
            default_storage.unlink_transaction_receipt(
                transaction_id, file_id="old-receipt"
            )


def test_mixed_use_create_rejects_source_link_mismatch_before_payee_creation(
    default_storage: GoogleSheetsStorage,
) -> None:
    inputs = _expense_inputs(default_storage)
    inputs.update(
        payee_id="",
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
        source_id="source-link-mismatch",
        linked_transaction_id="transaction-link-mismatch",
    )
    source = default_storage.create_mixed_use_expense(**inputs)
    payees_before = default_storage.list_payees(active_only=False)
    retry_inputs = {
        **inputs,
        "linked_transaction_id": "different-linked-transaction",
        "new_payee_name": "Should not be created",
    }

    with pytest.raises(StorageConflictError, match="another transaction ID"):
        default_storage.create_mixed_use_expense(**retry_inputs)

    assert default_storage.list_payees(active_only=False) == payees_before
    assert default_storage.get_mixed_use_expense(source["id"])[
        "linked_transaction_id"
    ] == "transaction-link-mismatch"


def test_mixed_use_projection_rejects_destination_account(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    destination = next(
        account
        for account in default_storage.list_accounts(active_only=False)
        if account["id"] != source["account_id"]
    )
    transaction_sheet = default_storage._worksheet("Transactions")
    headers = default_storage._headers("Transactions")
    transaction_sheet.rows[1][headers.index("to_account_id")] = destination["id"]
    default_storage._invalidate("Transactions")

    with pytest.raises(StorageValidationError, match="destination account"):
        default_storage.list_mixed_use_expenses()


def test_generic_transaction_mutations_reject_half_populated_provenance(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured business use",
    )
    transaction_sheet = default_storage._worksheet("Transactions")
    headers = default_storage._headers("Transactions")
    transaction_sheet.rows[1][headers.index("source_type")] = ""
    default_storage._invalidate("Transactions")
    transaction = dict(default_storage._rows("Transactions", force_refresh=True)[0].values)

    with pytest.raises(StorageValidationError, match="provided together"):
        default_storage.delete_transaction(transaction["id"])
    with pytest.raises(StorageValidationError, match="provided together"):
        default_storage.bulk_delete_transactions(
            [transaction["id"]], expected_transactions=[transaction]
        )

    sources = default_storage._rows("MixedUseExpenses", force_refresh=True)
    assert sources[0].values["id"] == source["id"]
    assert sources[0].values["linked_transaction_id"] == transaction["id"]


def test_receipt_mutations_reject_half_populated_provenance(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured business use",
    )
    transaction = default_storage.list_transactions()[0]
    transaction_sheet = default_storage._worksheet("Transactions")
    headers = default_storage._headers("Transactions")
    transaction_sheet.rows[1][headers.index("source_type")] = ""
    transaction_sheet.rows[1][headers.index("receipt_references")] = (
        '[{"id":"oldreceipt01","name":"Receipt"}]'
    )
    default_storage._invalidate("Transactions")

    with pytest.raises(StorageValidationError, match="provided together"):
        default_storage.set_transaction_receipt_references(
            transaction["id"], []
        )
    with pytest.raises(StorageValidationError, match="provided together"):
        default_storage.unlink_transaction_receipt(
            transaction["id"], file_id="oldreceipt01"
        )

    sources = default_storage._rows("MixedUseExpenses", force_refresh=True)
    assert sources[0].values["id"] == source["id"]


def test_receipt_link_scans_for_duplicate_ownership_inside_lock(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    scan_started = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []
    original_list_transactions = default_storage.list_transactions

    def list_transactions(*args: object, **kwargs: object) -> list[dict[str, str]]:
        scan_started.set()
        return original_list_transactions(*args, **kwargs)

    default_storage.list_transactions = list_transactions  # type: ignore[method-assign]

    def link_receipt() -> None:
        try:
            default_storage.link_mixed_use_receipt(
                source["id"],
                reference={"id": "receipt-lock-check", "name": "Receipt"},
            )
        except BaseException as error:  # pragma: no cover - assertion below reports it
            errors.append(error)
        finally:
            finished.set()

    with google_sheets_module._MIXED_USE_CREATE_LOCK:
        worker = threading.Thread(target=link_receipt)
        worker.start()
        assert not scan_started.wait(0.1)
        assert not finished.wait(0.1)
    assert finished.wait(1)
    worker.join(timeout=1)
    assert not errors


def test_receipt_recovery_rejects_half_populated_provenance(
    default_storage: GoogleSheetsStorage,
) -> None:
    default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured business use",
    )
    expected_transaction = default_storage.list_transactions()[0]
    transaction_sheet = default_storage._worksheet("Transactions")
    headers = default_storage._headers("Transactions")
    transaction_sheet.rows[1][headers.index("source_type")] = ""
    default_storage._invalidate("Transactions")

    with pytest.raises(
        StorageValidationError, match="incomplete transaction provenance"
    ):
        default_storage.apply_receipt_recovery_plan(
            [expected_transaction], {expected_transaction["id"]: []}
        )


def test_mixed_use_delete_removes_source_and_projection(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured business use",
    )


    default_storage.delete_mixed_use_expense(source["id"], expected_source=source)

    assert default_storage.list_mixed_use_expenses() == []
    assert default_storage.list_transactions() == []


def test_mixed_use_delete_rejects_stale_source_baseline(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured business use",
    )
    updated = default_storage.edit_mixed_use_expense(
        source["id"],
        expected_source=source,
        allocation_rationale="Updated business use",
    )

    with pytest.raises(StorageConflictError, match="changed"):
        default_storage.delete_mixed_use_expense(
            source["id"], expected_source=source
        )

    assert default_storage.get_mixed_use_expense(source["id"]) == updated
    assert len(default_storage.list_transactions()) == 1


def test_mixed_use_source_baseline_includes_projection_tags(
    default_storage: GoogleSheetsStorage,
) -> None:
    first_tag = default_storage.create_tag("Original tag")
    second_tag = default_storage.create_tag("Concurrent tag")
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured business use",
        tag_ids=[first_tag["id"]],
    )
    transaction_sheet = default_storage._worksheet("Transactions")
    headers = default_storage._headers("Transactions")
    transaction_sheet.rows[1][headers.index("tag_ids")] = (
        f'["{second_tag["id"]}"]'
    )
    default_storage._invalidate("Transactions")

    with pytest.raises(StorageValidationError, match="tags do not match"):
        default_storage.list_mixed_use_expenses()

    with pytest.raises(StorageConflictError, match="changed"):
        default_storage.edit_mixed_use_expense(
            source["id"],
            expected_source=source,
            allocation_rationale="Updated business use",
        )

    with pytest.raises(StorageConflictError, match="changed"):
        default_storage.delete_mixed_use_expense(
            source["id"], expected_source=source
        )


def test_sheet_id_validation_is_consistent_for_mixed_use_worksheets(
    default_storage: GoogleSheetsStorage,
) -> None:
    worksheet = default_storage._worksheet("MixedUseExpenses")
    worksheet.id = "not-an-integer"

    with pytest.raises(StorageValidationError, match="invalid sheet ID"):
        default_storage._sheet_id("MixedUseExpenses")


def test_replace_rows_rebuilds_ranges_after_rows_shift_during_retry(
    default_storage: GoogleSheetsStorage,
) -> None:
    account = default_storage.create_account("Retry target", "Bank")
    row = default_storage._find_row("Accounts", account["id"])
    worksheet = default_storage._worksheet("Accounts")
    original_batch_update = worksheet.batch_update
    calls = 0

    def insert_row_then_fail(data: list[dict[str, object]], **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            worksheet.rows.insert(1, list(worksheet.rows[1]))
            worksheet.rows[1][0] = "inserted-before-retry"
            raise OSError("temporary failure")
        original_batch_update(data, **kwargs)

    worksheet.batch_update = insert_row_then_fail  # type: ignore[method-assign]
    replacement = {**row.values, "name": "Retry target updated"}

    default_storage._replace_rows("Accounts", [(row, replacement)])

    rows = default_storage._rows("Accounts", force_refresh=True)
    assert next(item for item in rows if item.values["id"] == account["id"]).values[
        "name"
    ] == "Retry target updated"
    assert rows[0].values["id"] == "inserted-before-retry"


def test_replace_rows_reports_conflict_when_row_changes_during_retry(
    default_storage: GoogleSheetsStorage,
) -> None:
    account = default_storage.create_account("Retry conflict", "Bank")
    row = default_storage._find_row("Accounts", account["id"])
    worksheet = default_storage._worksheet("Accounts")
    original_batch_update = worksheet.batch_update

    def change_then_timeout(data: list[dict[str, object]], **kwargs: object) -> None:
        del data, kwargs
        worksheet.rows[row.row_number - 1][worksheet.rows[0].index("name")] = (
            "Changed elsewhere"
        )
        raise OSError("temporary response lost")

    worksheet.batch_update = change_then_timeout  # type: ignore[method-assign]

    with pytest.raises(StorageUnavailableError, match="could not confirm"):
        default_storage._replace_rows(
            "Accounts", [(row, {**row.values, "name": "Retry conflict updated"})]
        )

    worksheet.batch_update = original_batch_update  # type: ignore[method-assign]


def test_replace_rows_refreshes_positions_after_retry_backoff(
    default_storage: GoogleSheetsStorage,
) -> None:
    account = default_storage.create_account("Backoff refresh", "Bank")
    row = default_storage._find_row("Accounts", account["id"])
    worksheet = default_storage._worksheet("Accounts")
    original_batch_update = worksheet.batch_update
    calls = 0

    def shift_then_timeout(data: list[dict[str, object]], **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            worksheet.rows.insert(1, list(worksheet.rows[1]))
            worksheet.rows[1][0] = "inserted-during-backoff"
            raise OSError("temporary response lost")
        original_batch_update(data, **kwargs)

    worksheet.batch_update = shift_then_timeout  # type: ignore[method-assign]
    default_storage._replace_rows(
        "Accounts", [(row, {**row.values, "name": "Backoff refresh updated"})]
    )

    rows = default_storage._rows("Accounts", force_refresh=True)
    assert next(item for item in rows if item.values["id"] == account["id"]).values[
        "name"
    ] == "Backoff refresh updated"
    assert rows[0].values["id"] == "inserted-during-backoff"


def test_replace_rows_stops_on_duplicate_id_in_uncertain_readback(
    default_storage: GoogleSheetsStorage,
) -> None:
    account = default_storage.create_account("Duplicate readback", "Bank")
    row = default_storage._find_row("Accounts", account["id"])
    worksheet = default_storage._worksheet("Accounts")
    original_batch_update = worksheet.batch_update
    calls = 0

    def duplicate_then_timeout(data: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            worksheet.rows.append(list(worksheet.rows[1]))
            raise OSError("temporary response lost")
        original_batch_update(data, **kwargs)

    worksheet.batch_update = duplicate_then_timeout  # type: ignore[method-assign]
    with pytest.raises(StorageUnavailableError, match="could not confirm"):
        default_storage._replace_rows(
            "Accounts", [(row, {**row.values, "name": "Should not retry"})]
        )

    assert calls == 1


def test_replace_rows_refreshes_positions_after_retry_guard(
    default_storage: GoogleSheetsStorage,
) -> None:
    account = default_storage.create_account("Guard refresh", "Bank")
    row = default_storage._find_row("Accounts", account["id"])
    worksheet = default_storage._worksheet("Accounts")
    original_batch_update = worksheet.batch_update
    calls = 0

    def shift_during_guard() -> None:
        worksheet.rows.insert(1, list(worksheet.rows[1]))
        worksheet.rows[1][0] = "inserted-during-guard"

    def fail_then_retry(data: list[dict[str, object]], **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("temporary response lost")
        original_batch_update(data, **kwargs)

    worksheet.batch_update = fail_then_retry  # type: ignore[method-assign]
    default_storage._replace_rows(
        "Accounts",
        [(row, {**row.values, "name": "Guard refresh updated"})],
        before_retry=shift_during_guard,
    )

    rows = default_storage._rows("Accounts", force_refresh=True)
    assert next(item for item in rows if item.values["id"] == account["id"]).values[
        "name"
    ] == "Guard refresh updated"
    assert rows[0].values["id"] == "inserted-during-guard"


def test_mixed_use_backup_round_trip_includes_source_and_linkage(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="80",
        business_use_percentage="12.5",
        allocation_rationale="Home office calculation",
    )
    backup = default_storage.export_backup_zip(
        {"business_profile_key": "test", "receipts": [], "schema_version": 1}
    )
    with zipfile.ZipFile(io.BytesIO(backup)) as archive:
        assert "MixedUseExpenses.csv" in archive.namelist()
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["format_version"] == BACKUP_FORMAT_VERSION
        assert manifest["row_counts"]["MixedUseExpenses"] == 1

    target = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    target.restore_backup_zip(backup)
    restored = target.get_mixed_use_expense(source["id"])
    assert restored["linked_transaction_id"] == source["linked_transaction_id"]
    assert target.list_transactions()[0]["source_id"] == source["id"]


def test_current_backup_rejects_orphaned_mixed_use_projection(
    default_storage: GoogleSheetsStorage,
) -> None:
    default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="80",
        business_use_percentage="12.5",
        allocation_rationale="Home office calculation",
    )
    backup = default_storage.export_backup_zip(
        {"business_profile_key": "test", "receipts": [], "schema_version": 1}
    )
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(backup)) as source, zipfile.ZipFile(
        output, "w"
    ) as destination:
        contents = {name: source.read(name) for name in source.namelist()}
        rows = list(csv.reader(io.StringIO(contents["Transactions.csv"].decode())))
        rows[1][rows[0].index("source_id")] = "missing-source"
        csv_buffer = io.StringIO(newline="")
        csv.writer(csv_buffer, lineterminator="\n").writerows(rows)
        contents["Transactions.csv"] = csv_buffer.getvalue().encode()
        manifest = json.loads(contents["manifest.json"])
        manifest["sha256"]["Transactions.csv"] = hashlib.sha256(
            contents["Transactions.csv"]
        ).hexdigest()
        contents["manifest.json"] = json.dumps(manifest).encode()
        for name, content in contents.items():
            destination.writestr(name, content)

    with pytest.raises(StorageValidationError, match="unknown source"):
        GoogleSheetsStorage.validate_backup_zip(output.getvalue())



def test_mixed_use_retry_ignores_its_persisted_receipt_owner(
    default_storage: GoogleSheetsStorage,
) -> None:
    inputs = {
        **_expense_inputs(default_storage),
        "total_expense": "100",
        "business_use_percentage": "50",
        "allocation_rationale": "Measured use",
        "source_id": "source-receipt-retry",
        "linked_transaction_id": "transaction-receipt-retry",
        "receipt_references": [{"id": "retryreceipt01", "name": "Receipt.pdf"}],
    }

    created = default_storage.create_mixed_use_expense(**inputs)
    retried = default_storage.create_mixed_use_expense(**inputs)

    assert retried["id"] == created["id"]
    assert retried["linked_transaction_id"] == created["linked_transaction_id"]
    assert len(default_storage._rows("MixedUseExpenses", force_refresh=True)) == 1
    assert len(default_storage._rows("Transactions", force_refresh=True)) == 1


def test_mixed_use_create_retry_reuses_pair_after_account_deactivation(
    default_storage: GoogleSheetsStorage,
) -> None:
    inputs = {
        **_expense_inputs(default_storage),
        "total_expense": "100",
        "business_use_percentage": "50",
        "allocation_rationale": "Measured use",
        "source_id": "source-deactivated-retry",
        "linked_transaction_id": "transaction-deactivated-retry",
    }
    created = default_storage.create_mixed_use_expense(**inputs)
    default_storage.deactivate_account(inputs["account_id"])
    default_storage.edit_payee(inputs["payee_id"], active=False)

    retry_inputs = {
        key: value
        for key, value in inputs.items()
        if key != "linked_transaction_id"
    }
    retried = default_storage.create_mixed_use_expense(**retry_inputs)

    assert retried == created


def test_mixed_use_append_rechecks_receipt_ownership_before_retry(
    default_storage: GoogleSheetsStorage, monkeypatch
) -> None:
    inputs = {
        **_expense_inputs(default_storage),
        "total_expense": "100",
        "business_use_percentage": "50",
        "allocation_rationale": "Measured use",
        "source_id": "source-receipt-concurrent",
        "linked_transaction_id": "transaction-receipt-concurrent",
        "receipt_references": [{"id": "concurrent-receipt", "name": "Receipt.pdf"}],
    }
    source_sheet = default_storage._worksheet("MixedUseExpenses")
    original_append = source_sheet.append_row
    calls = 0

    def add_owner_then_timeout(values: list[str], **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            default_storage.create_transaction(
                txn_date=inputs["txn_date"],
                kind="Expense",
                amount="50",
                account_id=inputs["account_id"],
                category_id=inputs["category_id"],
                payee_id=inputs["payee_id"],
                receipt_references=inputs["receipt_references"],
            )
            raise OSError("temporary response lost")
        original_append(values, **kwargs)

    monkeypatch.setattr(source_sheet, "append_row", add_owner_then_timeout)
    with pytest.raises(StorageConflictError, match="already linked"):
        default_storage.create_mixed_use_expense(**inputs)

    assert calls == 1
    assert default_storage.list_mixed_use_expenses() == []


def test_mixed_use_create_verifies_uncertain_source_payload_before_projection(
    default_storage: GoogleSheetsStorage,
) -> None:
    inputs = {
        **_expense_inputs(default_storage),
        "total_expense": "100",
        "business_use_percentage": "50",
        "allocation_rationale": "Measured use",
        "source_id": "source-payload-conflict",
        "linked_transaction_id": "transaction-payload-conflict",
    }
    original_append = default_storage._append

    def append_conflicting_source(title: str, record: dict[str, str]) -> None:
        if title == "MixedUseExpenses":
            conflicting = {**record, "allocation_rationale": "Other use"}
            original_append(title, conflicting)
            return
        original_append(title, record)

    default_storage._append = append_conflicting_source  # type: ignore[method-assign]
    with pytest.raises(StorageConflictError, match="different data"):
        default_storage.create_mixed_use_expense(**inputs)

    assert default_storage._rows("Transactions", force_refresh=True) == []


def test_mixed_use_create_failure_invalidates_both_pair_caches(
    default_storage: GoogleSheetsStorage,
) -> None:
    inputs = {
        **_expense_inputs(default_storage),
        "total_expense": "100",
        "business_use_percentage": "50",
        "allocation_rationale": "Measured use",
        "source_id": "source-cache-invalidation",
        "linked_transaction_id": "transaction-cache-invalidation",
    }
    default_storage._row_cache["MixedUseExpenses"] = []
    default_storage._row_cache["Transactions"] = []
    original_append = default_storage._append

    def fail_projection_append(title: str, record: dict[str, str]) -> None:
        if title == "Transactions":
            raise StorageUnavailableError("projection write failed", retryable=True)
        original_append(title, record)

    default_storage._append = fail_projection_append  # type: ignore[method-assign]
    with pytest.raises(StorageUnavailableError, match="could not confirm"):
        default_storage.create_mixed_use_expense(**inputs)

    assert "MixedUseExpenses" not in default_storage._row_cache
    assert "Transactions" not in default_storage._row_cache


def test_mixed_use_create_returns_success_when_final_response_is_lost(
    default_storage: GoogleSheetsStorage,
) -> None:
    inputs = {
        **_expense_inputs(default_storage),
        "total_expense": "100",
        "business_use_percentage": "50",
        "allocation_rationale": "Measured use",
        "source_id": "source-final-write",
        "linked_transaction_id": "transaction-final-write",
    }
    original_append = default_storage._append
    calls = 0

    def append_then_lose_final_result(title: str, record: dict[str, str]) -> None:
        nonlocal calls
        original_append(title, record)
        calls += 1
        if calls == 2:
            raise StorageUnavailableError("response lost", retryable=True)

    default_storage._append = append_then_lose_final_result  # type: ignore[method-assign]
    result = default_storage.create_mixed_use_expense(**inputs)

    assert result["id"] == inputs["source_id"]
    assert len(default_storage.list_transactions()) == 1


def test_mixed_use_edit_returns_success_when_final_response_is_lost(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    original_replace = default_storage._replace_rows_atomically

    def replace_then_lose_final_result(updates: object) -> None:
        original_replace(updates)  # type: ignore[arg-type]
        raise StorageUnavailableError("response lost", retryable=True)

    default_storage._replace_rows_atomically = replace_then_lose_final_result  # type: ignore[method-assign]
    result = default_storage.edit_mixed_use_expense(
        source["id"],
        total_expense="200",
        business_use_percentage="25",
        allocation_rationale="Updated use",
    )

    assert result["allocated_amount"] == "50.00"


def test_mixed_use_edit_replaces_pair_in_one_spreadsheet_batch(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    original_batch = default_storage._batch_update_spreadsheet
    batches: list[object] = []

    def record_batch(requests: object) -> None:
        batches.append(requests)
        original_batch(requests)  # type: ignore[arg-type]

    default_storage._batch_update_spreadsheet = record_batch  # type: ignore[method-assign]
    default_storage.edit_mixed_use_expense(
        source["id"],
        total_expense="200",
        business_use_percentage="25",
        allocation_rationale="Updated use",
    )

    assert len(batches) == 1
    requests = batches[0]
    assert isinstance(requests, list)
    assert len(requests) == 2
    assert {
        request["updateCells"]["range"]["sheetId"]
        for request in requests
    } == {
        default_storage._sheet_id("Transactions"),
        default_storage._sheet_id("MixedUseExpenses"),
    }


def test_mixed_use_edit_revalidates_references_before_retry(
    default_storage: GoogleSheetsStorage,
    monkeypatch,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    target = default_storage.create_category("Retry mixed target", "Expense")
    calls = 0

    def delete_target_during_backoff(_: float) -> None:
        default_storage.delete_category(target["id"])

    def fail_once(_: object) -> None:
        nonlocal calls
        calls += 1
        raise StorageUnavailableError("temporary response lost", retryable=True)

    monkeypatch.setattr(default_storage, "_sleeper", delete_target_during_backoff)
    monkeypatch.setattr(default_storage, "_batch_update_spreadsheet", fail_once)

    with pytest.raises(StorageValidationError, match="Category does not exist"):
        default_storage.edit_mixed_use_expense(
            source["id"], category_id=target["id"]
        )

    assert calls == 1
    assert default_storage.get_mixed_use_expense(source["id"])["category_id"] != target["id"]


def test_mixed_use_edit_revalidates_inline_created_payee_before_retry(
    default_storage: GoogleSheetsStorage,
    monkeypatch,
) -> None:
    inputs = {**_expense_inputs(default_storage), "payee_id": ""}
    source = default_storage.create_mixed_use_expense(
        **inputs,
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    calls = 0

    def delete_inline_payee_during_backoff(_: float) -> None:
        payee = next(
            item
            for item in default_storage.list_payees(active_only=False)
            if item["name"] == "Retry inline payee"
        )
        row = default_storage._find_row("Payees", payee["id"])
        default_storage._worksheet("Payees").delete_rows(row.row_number)
        default_storage._invalidate("Payees")

    def fail_once(_: object) -> None:
        nonlocal calls
        calls += 1
        raise StorageUnavailableError("temporary response lost", retryable=True)

    monkeypatch.setattr(default_storage, "_sleeper", delete_inline_payee_during_backoff)
    monkeypatch.setattr(default_storage, "_batch_update_spreadsheet", fail_once)

    with pytest.raises(StorageValidationError, match="Payee does not exist"):
        default_storage.edit_mixed_use_expense(
            source["id"], new_payee_name="Retry inline payee"
        )

    assert calls == 1


def test_mixed_use_edit_rejects_receipt_drift_before_replacing_rows(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    original_find = default_storage._find_row
    calls = 0

    def find_after_receipt_update(title: str, record_id: str) -> object:
        nonlocal calls
        if calls == 0:
            transaction_sheet = default_storage._worksheet("Transactions")
            source_sheet = default_storage._worksheet("MixedUseExpenses")
            transaction_headers = default_storage._headers("Transactions")
            source_headers = default_storage._headers("MixedUseExpenses")
            reference = '[{"id":"oldreceipt01","name":"Receipt"}]'
            transaction_sheet.rows[1][transaction_headers.index("receipt_references")] = reference
            source_sheet.rows[1][source_headers.index("receipt_references")] = reference
        calls += 1
        return original_find(title, record_id)

    default_storage._find_row = find_after_receipt_update  # type: ignore[method-assign]
    with pytest.raises(StorageConflictError, match="changed"):
        default_storage.edit_mixed_use_expense(
            source["id"], allocation_rationale="Updated use"
        )


def test_mixed_use_receipt_update_rejects_pair_drift_before_writing(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    original_find = default_storage._find_row
    calls = 0

    def find_after_concurrent_receipt_update(title: str, record_id: str) -> object:
        nonlocal calls
        if calls == 1:
            reference = '[{"id":"concurrent-receipt","name":"Receipt"}]'
            transaction_sheet = default_storage._worksheet("Transactions")
            source_sheet = default_storage._worksheet("MixedUseExpenses")
            transaction_headers = default_storage._headers("Transactions")
            source_headers = default_storage._headers("MixedUseExpenses")
            transaction_sheet.rows[1][transaction_headers.index("receipt_references")] = reference
            source_sheet.rows[1][source_headers.index("receipt_references")] = reference
            default_storage._invalidate("Transactions")
            default_storage._invalidate("MixedUseExpenses")
        calls += 1
        return original_find(title, record_id)

    default_storage._find_row = find_after_concurrent_receipt_update  # type: ignore[method-assign]
    with pytest.raises(StorageConflictError, match="receipt pair changed"):
        default_storage.set_mixed_use_receipt_references(
            source["id"], [], expected_source=source
        )


def test_mixed_use_receipt_update_refreshes_row_position_before_writing(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    original_find = default_storage._find_row
    calls = 0

    def find_after_transaction_row_shift(title: str, record_id: str) -> object:
        nonlocal calls
        if calls == 1:
            worksheet = default_storage._worksheet("Transactions")
            worksheet.rows.insert(1, list(worksheet.rows[1]))
            worksheet.rows[1][0] = "unrelated-transaction"
            default_storage._invalidate("Transactions")
        calls += 1
        return original_find(title, record_id)

    default_storage._find_row = find_after_transaction_row_shift  # type: ignore[method-assign]
    updated = default_storage.set_mixed_use_receipt_references(
        source["id"], [], expected_source=source
    )

    assert updated["id"] == source["linked_transaction_id"]
    rows = default_storage._rows("Transactions", force_refresh=True)
    assert [
        (item.row_number, item.values["id"], item.values["receipt_references"])
        for item in rows
    ] == [(2, "unrelated-transaction", "[]"), (3, source["linked_transaction_id"], "[]")]
    assert rows[0].values["id"] == "unrelated-transaction"
    assert rows[0].values["receipt_references"] == "[]"
    assert rows[1].values["id"] == source["linked_transaction_id"]
    assert rows[1].values["receipt_references"] == "[]"


def test_receipt_recovery_restarts_after_mixed_use_pair_drift(
    default_storage: GoogleSheetsStorage,
) -> None:
    default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    transaction = default_storage.list_transactions()[0]
    original_rows = default_storage._rows
    calls = 0

    def rows_after_concurrent_receipt_update(
        title: str, *, force_refresh: bool = False
    ) -> list[object]:
        nonlocal calls
        if title == "MixedUseExpenses":
            reference = '[{"id":"recovery-concurrent","name":"Receipt"}]'
            transaction_sheet = default_storage._worksheet("Transactions")
            source_sheet = default_storage._worksheet("MixedUseExpenses")
            transaction_headers = default_storage._headers("Transactions")
            source_headers = default_storage._headers("MixedUseExpenses")
            transaction_sheet.rows[1][transaction_headers.index("receipt_references")] = reference
            source_sheet.rows[1][source_headers.index("receipt_references")] = reference
            default_storage._invalidate("Transactions")
            default_storage._invalidate("MixedUseExpenses")
        calls += 1
        return original_rows(title, force_refresh=force_refresh)

    default_storage._rows = rows_after_concurrent_receipt_update  # type: ignore[method-assign]
    applied, fresh_transactions = default_storage.apply_receipt_recovery_plan(
        [transaction], {transaction["id"]: []}
    )

    assert applied is False
    assert fresh_transactions[0]["id"] == transaction["id"]
    assert fresh_transactions[0]["receipt_references"] == (
        '[{"id":"recovery-concurrent","name":"Receipt"}]'
    )
    assert calls == 3


def test_receipt_recovery_refreshes_transaction_rows_with_source_snapshot(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
        receipt_references=[{"id": "old-receipt", "name": "Receipt"}],
    )
    transaction_id = source["linked_transaction_id"]
    expected_transactions = default_storage.list_transactions()
    original_snapshot = default_storage._snapshot
    final_snapshot_seen = False

    def snapshot_with_transaction_row_shift(
        titles: object, *, force_refresh: bool = False
    ) -> dict[str, object]:
        nonlocal final_snapshot_seen
        titles_list = list(titles)  # type: ignore[arg-type]
        if titles_list == ["Transactions", "MixedUseExpenses"]:
            final_snapshot_seen = True
            worksheet = default_storage._worksheet("Transactions")
            inserted = [""] * len(worksheet.rows[1])
            worksheet.rows.insert(1, inserted)
            default_storage._invalidate("Transactions")
        return original_snapshot(titles_list, force_refresh=force_refresh)

    default_storage._snapshot = snapshot_with_transaction_row_shift  # type: ignore[method-assign]
    applied, _ = default_storage.apply_receipt_recovery_plan(
        expected_transactions,
        {transaction_id: [{"id": "new-receipt", "name": "Receipt"}]},
    )

    assert applied is True
    assert final_snapshot_seen is True
    rows = default_storage._rows("Transactions", force_refresh=True)
    assert [
        (row.row_number, row.values["id"], row.values["receipt_references"])
        for row in rows
    ] == [
        (3, transaction_id, '[{"id":"new-receipt","name":"Receipt"}]'),
    ]


def test_receipt_recovery_restarts_after_unrelated_receipt_drift_during_final_read(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
        receipt_references=[{"id": "old-receipt", "name": "Receipt"}],
    )
    unrelated = default_storage.create_transaction(
        **_expense_inputs(default_storage),
        kind="Expense",
        amount="20",
    )
    expected_transactions = default_storage.list_transactions()
    original_snapshot = default_storage._snapshot
    final_snapshot_seen = False

    def snapshot_with_unrelated_receipt_drift(
        titles: object, *, force_refresh: bool = False
    ) -> dict[str, object]:
        nonlocal final_snapshot_seen
        titles_list = list(titles)  # type: ignore[arg-type]
        if titles_list == ["Transactions", "MixedUseExpenses"]:
            final_snapshot_seen = True
            worksheet = default_storage._worksheet("Transactions")
            headers = default_storage._headers("Transactions")
            unrelated_row = next(
                row
                for row in worksheet.rows[1:]
                if row[headers.index("id")] == unrelated["id"]
            )
            unrelated_row[headers.index("receipt_references")] = (
                '[{"id":"unrelated-receipt","name":"Receipt"}]'
            )
            default_storage._invalidate("Transactions")
        return original_snapshot(titles_list, force_refresh=force_refresh)

    default_storage._snapshot = snapshot_with_unrelated_receipt_drift  # type: ignore[method-assign]
    applied, fresh_transactions = default_storage.apply_receipt_recovery_plan(
        expected_transactions,
        {
            source["linked_transaction_id"]: [
                {"id": "new-receipt", "name": "Receipt"}
            ]
        },
    )

    assert applied is False
    assert final_snapshot_seen is True
    assert next(
        row for row in fresh_transactions if row["id"] == unrelated["id"]
    )["receipt_references"] == '[{"id":"unrelated-receipt","name":"Receipt"}]'
    assert next(
        row
        for row in fresh_transactions
        if row["id"] == source["linked_transaction_id"]
    )["receipt_references"] == source["receipt_references"]


def test_receipt_recovery_restarts_after_mixed_use_provenance_drift(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    expected_transactions = default_storage.list_transactions()
    transaction_sheet = default_storage._worksheet("Transactions")
    headers = default_storage._headers("Transactions")
    transaction_sheet.rows[1][headers.index("source_type")] = ""
    transaction_sheet.rows[1][headers.index("source_id")] = ""
    default_storage._invalidate("Transactions")

    applied, fresh_transactions = default_storage.apply_receipt_recovery_plan(
        expected_transactions,
        {source["linked_transaction_id"]: []},
    )

    assert applied is False
    assert fresh_transactions[0]["source_type"] == ""
    assert fresh_transactions[0]["source_id"] == ""


def test_receipt_recovery_rejects_unrelated_receipt_drift(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    unrelated = default_storage.create_transaction(
        **_expense_inputs(default_storage),
        kind="Expense",
        amount="20",
    )
    expected_transactions = default_storage.list_transactions()
    transaction_sheet = default_storage._worksheet("Transactions")
    headers = default_storage._headers("Transactions")
    unrelated_row = next(
        row
        for row in transaction_sheet.rows[1:]
        if row[headers.index("id")] == unrelated["id"]
    )
    unrelated_row[headers.index("receipt_references")] = (
        '[{"id":"unrelatedreceipt","name":"Receipt"}]'
    )
    default_storage._invalidate("Transactions")

    applied, fresh_transactions = default_storage.apply_receipt_recovery_plan(
        expected_transactions,
        {
            source["linked_transaction_id"]: [
                {"id": "recoveredreceipt", "name": "Receipt"}
            ]
        },
    )

    assert applied is False
    assert next(
        item for item in fresh_transactions if item["id"] == unrelated["id"]
    )["receipt_references"] == '[{"id":"unrelatedreceipt","name":"Receipt"}]'
    assert next(
        item
        for item in fresh_transactions
        if item["id"] == source["linked_transaction_id"]
    )["receipt_references"] == "[]"


def test_mixed_use_delete_rejects_pair_drift_before_deleting_rows(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    original_find = default_storage._find_row
    calls = 0

    def find_after_receipt_update(title: str, record_id: str) -> object:
        nonlocal calls
        if calls == 0:
            transaction_sheet = default_storage._worksheet("Transactions")
            source_sheet = default_storage._worksheet("MixedUseExpenses")
            transaction_headers = default_storage._headers("Transactions")
            source_headers = default_storage._headers("MixedUseExpenses")
            reference = '[{"id":"oldreceipt01","name":"Receipt"}]'
            transaction_sheet.rows[1][transaction_headers.index("receipt_references")] = reference
            source_sheet.rows[1][source_headers.index("receipt_references")] = reference
        calls += 1
        return original_find(title, record_id)

    default_storage._find_row = find_after_receipt_update  # type: ignore[method-assign]
    with pytest.raises(StorageConflictError, match="changed"):
        default_storage.delete_mixed_use_expense(source["id"])

    assert len(default_storage._rows("Transactions", force_refresh=True)) == 1
    assert len(default_storage._rows("MixedUseExpenses", force_refresh=True)) == 1

def test_mixed_use_delete_confirms_final_delete_after_lost_response(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    original_batch_update = default_storage._workbook.batch_update

    def delete_then_lose_response(body: object) -> None:
        original_batch_update(body)
        raise OSError("response lost after delete")

    default_storage._workbook.batch_update = delete_then_lose_response

    default_storage.delete_mixed_use_expense(source["id"])

    assert default_storage.list_mixed_use_expenses() == []
    assert default_storage.list_transactions() == []


@pytest.mark.parametrize("mutation", ["edit", "delete"])
def test_mixed_use_batch_requires_final_readback_after_success(
    default_storage: GoogleSheetsStorage, monkeypatch, mutation: str
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    batch_update = Mock()
    monkeypatch.setattr(default_storage, "_batch_update_spreadsheet", batch_update)

    with pytest.raises(StorageUnavailableError, match="could not confirm"):
        if mutation == "edit":
            default_storage.edit_mixed_use_expense(
                source["id"], allocation_rationale="Updated use"
            )
        else:
            default_storage.delete_mixed_use_expense(source["id"])

    assert batch_update.call_count == 1
    assert "Transactions" not in default_storage._row_cache
    assert "MixedUseExpenses" not in default_storage._row_cache


def test_mixed_use_delete_partial_pair_stops_without_retry(
    default_storage: GoogleSheetsStorage,
    monkeypatch,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    original_batch_update = default_storage._workbook.batch_update
    calls = 0

    def partial_then_lose_response(body: dict[str, object]) -> None:
        nonlocal calls
        calls += 1
        original_batch_update({"requests": body["requests"][:1]})
        raise OSError("response lost after partial deletion")

    monkeypatch.setattr(
        default_storage._workbook, "batch_update", partial_then_lose_response
    )

    with pytest.raises(StorageUnavailableError, match="could not confirm"):
        default_storage.delete_mixed_use_expense(source["id"])

    assert calls == 1
    assert "Transactions" not in default_storage._row_cache
    assert "MixedUseExpenses" not in default_storage._row_cache


def test_mixed_use_append_does_not_replay_when_confirmation_read_fails(
    default_storage: GoogleSheetsStorage,
) -> None:
    worksheet = default_storage._worksheet("MixedUseExpenses")
    original_append_row = worksheet.append_row
    original_rows = default_storage._rows
    calls = 0

    def append_then_lose_response(values: list[str], **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        original_append_row(values, **kwargs)
        raise OSError("response lost after append")

    def rows_unavailable_after_append(
        title: str, *, force_refresh: bool = False
    ) -> list[object]:
        if title == "MixedUseExpenses" and force_refresh:
            raise StorageUnavailableError("confirmation read unavailable", retryable=True)
        return original_rows(title, force_refresh=force_refresh)

    worksheet.append_row = append_then_lose_response  # type: ignore[method-assign]
    default_storage._rows = rows_unavailable_after_append  # type: ignore[method-assign]
    default_storage._retry_attempts = 2

    with pytest.raises(StorageUnavailableError, match="could not confirm"):
        default_storage._append("MixedUseExpenses", {"id": "ambiguous-append"})

    default_storage._rows = original_rows  # type: ignore[method-assign]
    assert calls == 1
    assert len(default_storage._rows("MixedUseExpenses", force_refresh=True)) == 1
